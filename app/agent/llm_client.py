import os
import sys
import time
import requests
import argparse

from langsmith import traceable

# Allow running this file directly as a script (python app/agent/llm_client.py)
# by ensuring the project root is on sys.path so the `app` package can be imported.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import settings

class RateLimitError(Exception):
    pass


RATE_LIMIT_RETRY_BACKOFF = 25  # seconds; free-tier TPM windows reset within 60s

GEMINI_CHAT_MODEL = "gemini-1.5-flash"  # the Gemini REST URL embeds the model name


# ----------------------------------------------------------------------
# LangSmith tracing of the provider calls
# ----------------------------------------------------------------------
# Each provider call is published as a LangSmith `llm` run, so the exact prompt,
# the raw provider response (including token usage) and the rate-limit/auth
# failures that drive the fallback chain are visible in the trace — not just the
# enclosing LangGraph node spans. Tracing is inert unless the LANGSMITH_*/
# LANGCHAIN_* env vars are set (loaded into os.environ by app/config.py), and a
# tracing failure never breaks a request — langsmith logs it and carries on.

def _traced_llm(provider: str, default_model: str):
    """Decorator factory: publish one provider call as a LangSmith `llm` run."""

    def process_inputs(inputs: dict) -> dict:
        # Keep only the chat payload — drop `self` and the rest of the call plumbing.
        return {
            "messages": inputs.get("messages"),
            "temperature": inputs.get("temperature"),
            "model": inputs.get("model") or default_model,
            "provider": provider,
        }

    def process_outputs(output: dict) -> dict:
        # Groq/OpenRouter already answer in OpenAI chat-completion shape.
        if not isinstance(output, dict) or "choices" in output:
            return output
        # Gemini answers with candidates/usageMetadata — normalise it so the UI can
        # render the completion and report token usage.
        try:
            text = output["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            return output
        usage = output.get("usageMetadata") or {}
        return {
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {
                "prompt_tokens": usage.get("promptTokenCount"),
                "completion_tokens": usage.get("candidatesTokenCount"),
                "total_tokens": usage.get("totalTokenCount"),
            },
            "raw": output,
        }

    return traceable(
        run_type="llm",
        name=provider,
        metadata={"provider": provider},
        process_inputs=process_inputs,
        process_outputs=process_outputs,
    )


class LLMClient:
    def __init__(self):
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"
        self.openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        self.gemini_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_CHAT_MODEL}:generateContent"
        )

    @_traced_llm("groq", settings.groq_model)
    def _invoke_groq(self, messages: list, temperature: float, model: str | None = None) -> dict:
        """Raw Groq chat-completion payload (the traced unit of work)."""
        target_model = model or settings.groq_model
        resp = requests.post(
            self.groq_url,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={"model": target_model, "messages": messages, "temperature": temperature},
            timeout=30,
        )
        if resp.status_code == 429:
            raise RateLimitError("Groq rate limit hit")
        resp.raise_for_status()
        return resp.json()

    def _call_groq(self, messages: list, temperature: float, model: str | None = None) -> str:
        return self._invoke_groq(messages, temperature, model=model)["choices"][0]["message"]["content"]

    @_traced_llm("openrouter", settings.openrouter_model)
    def _invoke_openrouter(self, messages: list, temperature: float, model: str | None = None) -> dict:
        """Raw OpenRouter chat-completion payload (the traced unit of work)."""
        target_model = model or settings.openrouter_model
        resp = requests.post(
            self.openrouter_url,
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            json={"model": target_model, "messages": messages, "temperature": temperature},
            timeout=30,
        )
        if resp.status_code == 429:
            raise RateLimitError("OpenRouter rate limit hit")
        resp.raise_for_status()
        return resp.json()

    def _call_openrouter(self, messages: list, temperature: float, model: str | None = None) -> str:
        return self._invoke_openrouter(messages, temperature, model=model)["choices"][0]["message"]["content"]

    @_traced_llm("gemini", GEMINI_CHAT_MODEL)
    def _invoke_gemini(self, messages: list, temperature: float, model: str | None = None) -> dict:
        """Raw Gemini generateContent payload (the traced unit of work)."""
        prompt = "\n".join(m["content"] for m in messages)
        resp = requests.post(
            f"{self.gemini_url}?key={settings.gemini_api_key}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _call_gemini(self, messages: list, temperature: float, model: str | None = None) -> str:
        payload = self._invoke_gemini(messages, temperature, model=model)
        return payload["candidates"][0]["content"]["parts"][0]["text"]

    def chat(self, messages: list, temperature: float = 0.2, model: str | None = None) -> str:
        last_rate_limited = None
        for name, fn in [("groq", self._call_groq), ("openrouter", self._call_openrouter), ("gemini", self._call_gemini)]:
            try:
                return fn(messages, temperature, model=model)
            except RateLimitError:
                last_rate_limited = (name, fn)
                print(f"[llm_client] {name} rate-limited, falling back...")
                time.sleep(1)
                continue
            except requests.HTTPError as e:
                print(f"[llm_client] {name} failed: {e}, falling back...")
                continue
        # Every provider failed. If the last failure was a rate limit (not an
        # auth error), the quota window typically resets within a minute —
        # wait once and retry that provider before surfacing the failure.
        if last_rate_limited is not None:
            name, fn = last_rate_limited
            print(f"[llm_client] all providers exhausted; retrying {name} once after {RATE_LIMIT_RETRY_BACKOFF}s backoff...")
            time.sleep(RATE_LIMIT_RETRY_BACKOFF)
            try:
                return fn(messages, temperature, model=model)
            except RateLimitError:
                print(f"[llm_client] {name} still rate-limited after backoff, giving up")
            except requests.HTTPError as e:
                print(f"[llm_client] {name} failed: {e}, giving up")
        raise RuntimeError("All LLM providers failed or rate-limited")


llm_client = LLMClient()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="Say hello in exactly 3 words.")
    args = parser.parse_args()
    print("Response:", llm_client.chat([{"role": "user", "content": args.prompt}]))

if __name__ == "__main__":
    main()