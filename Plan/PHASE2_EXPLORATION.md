# Phase 2 — Exploration Guide (Agent Core: Router → Grade → Generate → Web Fallback)

> For each stage: a **think-first question**, then a code snippet to check
> yourself against, then a test with expected output. Try to answer/write
> before revealing the snippet — the value here is in the reasoning, not the
> paste. Every file also gets a `main()` guarded by
> `if __name__ == "__main__":`, driven by `argparse`, so you can smoke-test
> it from the terminal without a separate `test_*.py` file.

---

# PART A — `app/agent/state.py`

## Stage 0 — Think first

LangGraph passes a state object between every node in the graph. Each node
reads some fields, writes others.

**Question:** what does *every* node need to know or be able to write?
Router needs to write a route decision, KB retrieval needs to write
results, grading needs to write a verdict, generation needs to write an
answer. List the fields yourself before looking below.

## Reveal

```python
from typing import TypedDict, Optional


class AgentState(TypedDict):
    question: str
    route: Optional[str]              # "kb" | "web" | "direct"
    kb_results: Optional[list[dict]]
    kb_grade: Optional[str]           # "good" | "weak"
    web_results: Optional[list[dict]]
    web_grade: Optional[str]          # "good" | "weak"
    answer: Optional[str]
    source: Optional[str]             # "kb" | "web" | "fallback" | "direct"
```

**Question to check your understanding:** why `TypedDict` instead of a
regular dataclass, given this project already uses dataclasses elsewhere
(`CodeChunk` in Phase 1)? Think about what LangGraph's internals do with
this object between node calls — it merges partial dict updates. A
dataclass instance isn't a dict; `TypedDict` gives type hints while the
runtime object stays a plain dict, which is what LangGraph expects.

**Self-test:**
```python
if __name__ == "__main__":
    sample: AgentState = {
        "question": "how does auth work?",
        "route": None, "kb_results": None, "kb_grade": None,
        "web_results": None, "web_grade": None, "answer": None, "source": None,
    }
    print(sample)
```
Nothing to break yet — just confirms the shape is usable.

---

# PART B — `app/agent/llm_client.py`

## Stage 0 — Think first

Free LLM APIs (Groq, OpenRouter, Gemini) all rate-limit. This agent makes
several LLM calls per single user question (router, grade, generate — maybe
doubled if web fallback fires). During testing you WILL hit Groq's
per-minute cap.

**Question:** rather than the whole request failing when that happens, what
should happen instead? Sketch the control flow yourself — try provider A,
on failure try B, then C — before the reveal. What exception would you
raise yourself vs. what would you just catch from `requests`?

## Reveal

```python
import time
import requests
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
```

**Question to check your understanding:** what happens if ALL three
providers fail? Trace the loop yourself — does it silently return `None`,
or something else? (Look *after* the `for` loop, not inside it.) A silent
`None` would let broken downstream code fail confusingly instead of one
clear error.

**Self-test — don't just run the happy path:**
```python
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="Say hello in exactly 3 words.")
    args = parser.parse_args()
    print("Response:", llm_client.chat([{"role": "user", "content": args.prompt}]))

if __name__ == "__main__":
    main()
```
```bash
python -m app.agent.llm_client --prompt "What is 2+2?"
```
**Now deliberately break it:** temporarily set `GROQ_API_KEY` in `.env` to
garbage and re-run. You should see `[llm_client] groq failed...`, then a
real answer still comes from OpenRouter or Gemini. **If it crashes
instead**, the fallback isn't catching the right exception for a 401 — check
what `resp.raise_for_status()` actually raises there vs. the 429 you handle
explicitly. Restore your real key afterward.

---

# PART C — `app/tools/web_search.py`

## Stage 0 — Think first

You already compared Tavily vs DuckDuckGo earlier — Tavily gives cleaner,
LLM-ready content; DuckDuckGo is a free unofficial fallback.

**Question:** how similar should this be to `llm_client.py`'s cascade? Try
writing `search()`'s try/except shape yourself first. Does this need a
custom `RateLimitError` too, or is a broad `except` defensible given
there's only one fallback hop here, not a three-way chain?

## Reveal

```python
import requests
from duckduckgo_search import DDGS
from app.config import settings


class RateLimitError(Exception):
    pass


class WebSearchTool:
    def __init__(self):
        self.tavily_url = "https://api.tavily.com/search"

    def _search_tavily(self, query: str, max_results: int) -> list[dict]:
        resp = requests.post(
            self.tavily_url,
            json={"api_key": settings.tavily_api_key, "query": query, "max_results": max_results, "include_answer": False},
            timeout=15,
        )
        if resp.status_code == 429:
            raise RateLimitError("Tavily rate limit hit")
        resp.raise_for_status()
        data = resp.json()
        return [{"title": r["title"], "url": r["url"], "content": r["content"]} for r in data.get("results", [])]

    def _search_duckduckgo(self, query: str, max_results: int) -> list[dict]:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
        return [{"title": r.get("title", ""), "url": r.get("href", ""), "content": r.get("body", "")} for r in results]

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        try:
            return self._search_tavily(query, max_results)
        except Exception as e:
            print(f"[web_search] Tavily failed ({e}), falling back to DuckDuckGo...")
            return self._search_duckduckgo(query, max_results)


web_search_tool = WebSearchTool()
```

**Self-test:**
```python
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="python asyncio best practices")
    parser.add_argument("--max_results", type=int, default=3)
    args = parser.parse_args()
    for r in web_search_tool.search(args.query, args.max_results):
        print(f"- {r['title']} ({r['url']})")
        print(f"  {r['content'][:150]}...")

if __name__ == "__main__":
    main()
```
```bash
python -m app.tools.web_search --query "FastAPI dependency injection"
```
**Actually check, don't just confirm it ran:** are results genuinely about
FastAPI dependency injection, or generic/off-topic? Then force the
fallback — set `TAVILY_API_KEY` to garbage temporarily and re-run. Compare:
does DuckDuckGo's output look rawer/less clean than Tavily's, matching your
earlier comparison?

---

# PART D — `app/agent/nodes.py`

## Stage 0 — Think first: what IS a node, mechanically?

**Question:** given `AgentState` is a dict LangGraph merges updates into,
should a node return the *entire* state, or just changed fields? What
problem would returning the full state risk if two nodes run with stale
copies of shared fields?

(Check: a node returns a **partial dict** — only the keys it updates.
LangGraph merges that into running state. Returning the full state isn't
fatal, but risks a node overwriting a field it never meant to touch.)

## Stage 1 — Router node

**Think first:** the router picks one of three categories via an LLM call.
What makes a classification prompt reliable vs. flaky? Should the LLM
explain its reasoning, or just output one word? What `temperature` fits a
task where you want the *same* answer every time for the same input, not
creative variation? Write the prompt and function yourself, then compare.

```python
from app.agent.llm_client import llm_client

ROUTER_PROMPT = """Classify this question into exactly one category. Reply with ONLY the category word, nothing else.

Categories:
- kb: question about specific code, functions, or how this codebase works
- web: question about external errors, library versions, or things outside this codebase
- direct: general programming knowledge question not specific to this codebase

Question: {question}

Category:"""


def router_node(state: dict) -> dict:
    prompt = ROUTER_PROMPT.format(question=state["question"])
    response = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.0)
    route = response.strip().lower()
    if route not in ("kb", "web", "direct"):
        route = "kb"  # safe default — prefer trying the codebase first
    return {"route": route}
```

**Question:** why default to `"kb"` specifically when parsing fails, rather
than `"web"` or `"direct"`? Which default fails "safest" if classification
comes back garbled?

**Self-test:**
```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default="How does the login function work?")
    args = parser.parse_args()
    print(router_node({"question": args.question}))
```
```bash
python -m app.agent.nodes --question "What does ECONNREFUSED mean?"
```
Try 3 questions yourself — one obviously KB, one obviously web, one general
knowledge — and check routing matches your intuition before trusting it in
the full graph.

## Stage 2 — KB retrieval node

**Think first:** you already built and tested `search()` in Phase 1. What's
the minimum wrapper needed here — does this node need new logic, or is it
purely glue?

```python
from app.ingestion.embed_store import search as kb_search

def retrieve_kb_node(state: dict) -> dict:
    results = kb_search(state["question"], top_k=5)
    return {"kb_results": results}
```

If Phase 1's `search()` already worked, almost nothing new can break here —
the useful check is confirming the field name (`kb_results`) matches what
`grade_kb_node` expects to read next.

## Stage 3 — Grade KB evidence node

**Think first — this is the most important node in the system.** Naive RAG
trusts top-k retrieval blindly. This node's job is to NOT trust it — does
the retrieved context actually answer the question, or did it just come
back for being topically similar? Before coding: what should the *default*
verdict be when grading output is ambiguous — `"good"` or `"weak"`? This is
the opposite question from Stage 1's router default — think about why the
safe direction flips here.

```python
GRADE_PROMPT = """Given this question and retrieved code context, decide if the context is sufficient to answer the question well.
Reply with ONLY "good" or "weak".

Question: {question}

Retrieved context:
{context}

Verdict:"""


def grade_kb_node(state: dict) -> dict:
    context = "\n\n".join(
        f"{r['file_path']}:{r['start_line']}-{r['end_line']}\n{r.get('content', '')}"
        for r in state["kb_results"]
    )
    prompt = GRADE_PROMPT.format(question=state["question"], context=context)
    response = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.0)
    grade = response.strip().lower()
    if grade not in ("good", "weak"):
        grade = "weak"  # safe default — prefer falling back over false confidence
    return {"kb_grade": grade}
```

Did you predict `"weak"`? Ambiguous grading should push the agent to do
*more* work (try web search) rather than confidently generate from context
that might be insufficient — false confidence is worse than an extra hop.

**Self-test — deliberately feed it thin, fake context:**
```python
if __name__ == "__main__":
    fake_state = {
        "question": "how does the login flow work",
        "kb_results": [{"file_path": "auth.py", "start_line": 1, "end_line": 10, "content": "def login(): pass"}],
    }
    print(grade_kb_node(fake_state))
```
**Predict the output before running it.** A one-line stub shouldn't be
enough to explain a "login flow." If you get `{'kb_grade': 'good'}` instead
of `'weak'`, the grading prompt is too lenient and needs tightening before
you trust it downstream.

## Stage 4 — Generate from KB node

**Think first:** what's the one non-negotiable instruction this prompt
needs, given the citation story this whole project is built around? Write
it yourself, then compare.

```python
GENERATE_KB_PROMPT = """Answer the question using ONLY the provided code context. Cite file paths and line numbers for every claim.

Question: {question}

Context:
{context}

Answer:"""


def generate_kb_node(state: dict) -> dict:
    context = "\n\n".join(
        f"{r['file_path']}:{r['start_line']}-{r['end_line']}\n{r.get('content', '')}"
        for r in state["kb_results"]
    )
    prompt = GENERATE_KB_PROMPT.format(question=state["question"], context=context)
    answer = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.2)
    return {"answer": answer, "source": "kb"}
```

**Worth thinking about, not required yet:** the prompt *asks* for citations
but doesn't *enforce* them. What would a simple enforcement check look like —
a regex checking for something like `\w+\.py:\d+`? Consider adding that as a
retry-trigger once the base flow works.

## Stage 5 — Web search + grade + generate (mirror Stage 2–4 yourself)

**Think first, before looking:** these three nodes should closely mirror
`retrieve_kb_node` / `grade_kb_node` / `generate_kb_node` — same shape,
different data source. Try writing `web_search_node`, `grade_web_node`, and
`generate_web_node` yourself using the KB versions as a template, then
compare.

```python
from app.tools.web_search import web_search_tool

def web_search_node(state: dict) -> dict:
    results = web_search_tool.search(state["question"], max_results=5)
    return {"web_results": results}


GRADE_WEB_PROMPT = """Given this question and web search results, decide if they are sufficient to answer well.
Reply with ONLY "good" or "weak".

Question: {question}

Web results:
{context}

Verdict:"""


def grade_web_node(state: dict) -> dict:
    context = "\n\n".join(f"{r['title']}\n{r['content']}" for r in state["web_results"])
    prompt = GRADE_WEB_PROMPT.format(question=state["question"], context=context)
    response = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.0)
    grade = response.strip().lower()
    return {"web_grade": grade if grade in ("good", "weak") else "weak"}


GENERATE_WEB_PROMPT = """Answer the question using the web search results below. Cite source URLs.

Question: {question}

Web results:
{context}

Answer:"""


def generate_web_node(state: dict) -> dict:
    context = "\n\n".join(f"{r['title']} ({r['url']})\n{r['content']}" for r in state["web_results"])
    prompt = GENERATE_WEB_PROMPT.format(question=state["question"], context=context)
    answer = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.2)
    return {"answer": answer, "source": "web"}
```

Did your version differ meaningfully? A common gap: forgetting to change
the citation instruction from "file path and line number" to "source URLs"
— citation *style* has to match what's actually available in each context.

## Stage 6 — Fallback node

**Think first:** this node only fires when BOTH kb_grade and web_grade came
back "weak." What is this node's job, philosophically, different from the
other generate nodes — best possible answer, or honesty about uncertainty?
Can it do both? Write it, then compare.

```python
FALLBACK_PROMPT = """Neither the codebase nor web search returned strong evidence for this question.
Give your best general answer, but explicitly state that this is not grounded in verified sources.

Question: {question}

Answer:"""


def fallback_node(state: dict) -> dict:
    prompt = FALLBACK_PROMPT.format(question=state["question"])
    answer = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.3)
    return {"answer": answer, "source": "fallback"}
```

This is the node that makes the "agentic" story credible in an interview —
the difference between a system that silently hallucinates and one that's
honest about the limits of its own evidence.

## Stage 7 — Direct-answer node

**Think first:** for the `"direct"` route (general programming knowledge,
nothing repo-specific), does this node need retrieval or grading at all?
What's the simplest possible implementation?

```python
DIRECT_PROMPT = """Answer this general programming question directly and concisely.

Question: {question}

Answer:"""


def direct_node(state: dict) -> dict:
    prompt = DIRECT_PROMPT.format(question=state["question"])
    answer = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.3)
    return {"answer": answer, "source": "direct"}
```

## Full self-test block for this file

```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", choices=["router", "grade_kb", "grade_web", "fallback"], required=True)
    parser.add_argument("--question", default="How does the login function work?")
    args = parser.parse_args()

    if args.test == "router":
        print(router_node({"question": args.question}))
    elif args.test == "grade_kb":
        fake = {"question": args.question, "kb_results": [{"file_path": "x.py", "start_line": 1, "end_line": 2, "content": "def x(): pass"}]}
        print(grade_kb_node(fake))
    elif args.test == "grade_web":
        fake = {"question": args.question, "web_results": [{"title": "irrelevant", "content": "unrelated content"}]}
        print(grade_web_node(fake))
    elif args.test == "fallback":
        print(fallback_node({"question": args.question}))
```
```bash
python -m app.agent.nodes --test router --question "why is my docker build failing"
python -m app.agent.nodes --test fallback --question "what's the meaning of life"
```

---

# PART E — `app/agent/graph.py`

## Stage 0 — Think first: fixed edges vs. conditional edges

You have 9 node functions now, none wired together. LangGraph's
`StateGraph` connects them via two kinds of edges: fixed hops (always A to
B) and conditional hops (A to B or C depending on a state value).

**Question, before looking at the code:** go back to your original
architecture diagram. Which arrows are fixed, and which are conditional
(`good`/`weak` branches)? List router's outgoing edges, grade_kb's outgoing
edges, grade_web's outgoing edges — before looking at the reveal.

## Reveal

```python
from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes import (
    router_node, retrieve_kb_node, grade_kb_node, generate_kb_node,
    web_search_node, grade_web_node, generate_web_node,
    fallback_node, direct_node,
)


def route_decision(state: dict) -> str:
    return state["route"]


def kb_grade_decision(state: dict) -> str:
    return "good" if state["kb_grade"] == "good" else "weak"


def web_grade_decision(state: dict) -> str:
    return "good" if state["web_grade"] == "good" else "weak"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("router", router_node)
    graph.add_node("retrieve_kb", retrieve_kb_node)
    graph.add_node("grade_kb", grade_kb_node)
    graph.add_node("generate_kb", generate_kb_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("grade_web", grade_web_node)
    graph.add_node("generate_web", generate_web_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("direct", direct_node)

    graph.set_entry_point("router")

    graph.add_conditional_edges("router", route_decision, {
        "kb": "retrieve_kb",
        "web": "web_search",
        "direct": "direct",
    })

    graph.add_edge("retrieve_kb", "grade_kb")
    graph.add_conditional_edges("grade_kb", kb_grade_decision, {
        "good": "generate_kb",
        "weak": "web_search",   # KB insufficient -> fall through to web
    })

    graph.add_edge("web_search", "grade_web")
    graph.add_conditional_edges("grade_web", web_grade_decision, {
        "good": "generate_web",
        "weak": "fallback",
    })

    graph.add_edge("generate_kb", END)
    graph.add_edge("generate_web", END)
    graph.add_edge("fallback", END)
    graph.add_edge("direct", END)

    return graph.compile()


agent_graph = build_graph()
```

**Question to check your understanding — the one thing most people miss on
first pass:** `web_search` has exactly one node in the graph, but two
different paths lead into it — router sending a `"web"`-classified question
directly, AND `grade_kb`'s `"weak"` branch. Why is this reuse correct
instead of needing two separate web-search nodes? Is there any meaningful
difference in what the node itself needs to do, once running, based on how
it got there?

**Self-test:**
```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    args = parser.parse_args()
    result = agent_graph.invoke({"question": args.question})
    print(f"\nRoute path led to source: {result['source']}")
    print(f"\nAnswer:\n{result['answer']}")
```
```bash
python -m app.agent.graph --question "How does the router node decide where to send a question?"
```

**Before running, predict:** given you likely haven't ingested a matching
repo into Qdrant yet, what `source` do you expect — `kb`, `web`, or
`fallback`? Run it and check your prediction.

**Then deliberately test the fallback path:**
```bash
python -m app.agent.graph --question "asdkjaslkdjaslkdj nonsense query xyz123"
```
**Predict first:** should this land on `fallback`? If it instead confidently
answers from `kb` or `web`, that's a signal your grading prompts are too
lenient — go back and tighten Stage 3/Stage 5 before trusting this graph.

---

# A note on this testing pattern vs. a real test suite

The `argparse`-driven `main()` blocks are **smoke tests** — fast manual
checks run right where the code lives, useful while actively editing.
They're not a substitute for a `tests/` directory with `pytest` and fixed
assertions, worth adding once the graph stabilizes (especially for RAGAS
eval work later). Keep both roles distinct: the in-file `main()` answers
"did I just break this," a `pytest` suite answers "does the whole system
still work reliably, without me manually running things."

---

# Phase 2 "Done" checklist

- [ ] `state.py`: shape confirmed, imports cleanly
- [ ] `llm_client.py`: cascade tested with a deliberately broken Groq key —
      confirmed it actually falls through, not just trusted the happy path
- [ ] `web_search.py`: compared real Tavily vs. forced-DuckDuckGo output on
      the same query, confirmed the quality difference you'd expect
- [ ] `nodes.py`: router correctly classifies 3 distinct question types
      chosen by you; grade_kb correctly marked a deliberately thin fake
      context as "weak", not "good"
- [ ] `graph.py`: predicted the `source` outcome before running, for both a
      KB-eligible question and a nonsense question, and confirmed against
      actual output
- [ ] Explained to yourself (or written down) why `web_search` is one node
      reused from two different edges, not two separate nodes
