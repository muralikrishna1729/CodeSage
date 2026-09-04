import os
import sys
import time
import requests
import argparse

# Allow running this file directly as a script (python app/agent/llm_client.py)
# by ensuring the project root is on sys.path so the `app` package can be imported.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import settings

class RateLimitError(Exception):
    pass


class LLMClient:
    def __init__(self):
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"
        self.openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        self.gemini_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-1.5-flash:generateContent"
        )

    def _call_groq(self, messages: list, temperature: float) -> str:
        resp = requests.post(
            self.groq_url,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={"model": settings.groq_model, "messages": messages, "temperature": temperature},
            timeout=30,
        )
        if resp.status_code == 429:
            raise RateLimitError("Groq rate limit hit")
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_openrouter(self, messages: list, temperature: float) -> str:
        resp = requests.post(
            self.openrouter_url,
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            json={"model": settings.openrouter_model, "messages": messages, "temperature": temperature},
            timeout=30,
        )
        if resp.status_code == 429:
            raise RateLimitError("OpenRouter rate limit hit")
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_gemini(self, messages: list, temperature: float) -> str:
        prompt = "\n".join(m["content"] for m in messages)
        resp = requests.post(
            f"{self.gemini_url}?key={settings.gemini_api_key}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    def chat(self, messages: list, temperature: float = 0.2) -> str:
        for name, fn in [("groq", self._call_groq), ("openrouter", self._call_openrouter), ("gemini", self._call_gemini)]:
            try:
                return fn(messages, temperature)
            except RateLimitError:
                print(f"[llm_client] {name} rate-limited, falling back...")
                time.sleep(1)
                continue
            except requests.HTTPError as e:
                print(f"[llm_client] {name} failed: {e}, falling back...")
                continue
        raise RuntimeError("All LLM providers failed or rate-limited")


llm_client = LLMClient()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="Say hello in exactly 3 words.")
    args = parser.parse_args()
    print("Response:", llm_client.chat([{"role": "user", "content": args.prompt}]))

if __name__ == "__main__":
    main()