import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.agent.llm_client import llm_client
from app.ingestion.embed_store import search as kb_search, get_repo_map_chunk
from app.tools.web_search import web_search_tool
from app.agent.context_budget import build_context_text

KB_TOP_K = 3
PROJECT_LEVEL_KEYWORDS = [
    "this project", "the project", "this repo", "the repo", "the codebase",
    "overall", "structure", "architecture", "workflow", "how is this",
    "explain this project", "what does this do",
]
ROUTER_PROMPT = """Classify this question into exactly one category. Reply with ONLY the category word, nothing else.

Categories:
- kb: question about specific code, functions, how this codebase works, OR asking to summarize/explain/describe the ingested project itself
- web: question about external errors, library versions, or things outside this codebase
- direct: general programming knowledge or career/interview advice not requiring any specifics about this codebase

Question: {question}

Category:
"""

GRADE_PROMPT = """Given this question and retrieved code context, decide if the context is sufficient to answer the question well.
Reply with ONLY "good" or "weak".

Question: {question}

Retrieved context:
{context}

Verdict:
"""
GENERATE_KB_PROMPT = """Answer the question using ONLY the provided code context. Cite file paths and line numbers for every claim.

Question: {question}

Context:
{context}

Answer:
"""

GRADE_WEB_PROMPT = """Given this question and web search results, decide if they are sufficient to answer well.
Reply with ONLY "good" or "weak".

Question: {question}

Web results:
{context}

Verdict:"""

GENERATE_WEB_PROMPT = """Answer the question using the web search results below. Cite source URLs.

Question: {question}

Web results:
{context}

Answer:"""

FALLBACK_PROMPT = """Neither the codebase nor web search returned strong evidence for this question.
Give your best general answer, but explicitly state that this is not grounded in verified sources.

Question: {question}

Answer:"""

DIRECT_PROMPT = """Answer this general programming question directly and concisely.

Question: {question}

Answer:"""


def router_node(state: dict) -> dict:
    prompt = ROUTER_PROMPT.format(question=state["question"])
    response = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.0)
    route = response.strip().lower()
    if route not in ("kb", "web", "direct"):
        route = "kb"  # safe default — prefer trying the codebase first
    return {"route": route}

def _is_project_level_question(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in PROJECT_LEVEL_KEYWORDS)

def retrieve_kb_node(state: dict) -> dict:
    repo_name = state["repo_name"]

    results = kb_search(state["question"], repo_name=repo_name, top_k=KB_TOP_K)
    repo_map_chunk = get_repo_map_chunk(repo_name) if _is_project_level_question(state["question"]) else None
    if repo_map_chunk:
        results = [repo_map_chunk]+ results
    return {"kb_results": results}

CONTEXT_CHAR_LIMIT = 20000  # ~5k tokens: keeps grade+generate within free-tier TPM budgets

def _format_context(results: list[dict], max_chars: int = CONTEXT_CHAR_LIMIT) -> str:
    """Assemble retrieval results into one context string, capped at max_chars.

    Both the grader and the generator embed the full context, so an oversized
    context doubles token usage per request and can trip free-tier
    tokens-per-minute limits (seen as Groq 429s on generate_kb).
    """
    blocks: list[str] = []
    total = 0
    for r in results:
        block = f"{r['file_path']}:{r['start_line']}-{r['end_line']}\n{r.get('content', '')}"
        if total + len(block) > max_chars:
            remaining = max_chars - total
            if remaining > 200:  # only append a fragment if it's still useful
                blocks.append(block[:remaining] + "\n… [truncated]")
            break
        blocks.append(block)
        total += len(block) + 2
    return "\n\n".join(blocks)

KB_GRADE_HIGH_CONFIDENCE = 0.50
KB_GRADE_LOW_CONFIDENCE = 0.20
def grade_kb_node(state: dict) -> dict:
    # Grade on CODE chunk scores only — the REPO_MAP sentinel is prepended with
    # a synthetic score of 1.0 (no real similarity), which would otherwise make
    # every project-level question auto-pass the confidence shortcut.
    code_scores = [r["score"] for r in state["kb_results"] if r.get("file_path") != "REPO_MAP"]
    top_score = max(code_scores) if code_scores else 0.0
    has_repo_map = any(r.get("file_path") == "REPO_MAP" for r in state["kb_results"])

    if top_score >= KB_GRADE_HIGH_CONFIDENCE:
        return {"kb_grade": "good"}  # skip the LLM call entirely
    # Only condemn weak code scores when there is no structural context to lean
    # on: broad project-level questions ("what is this project about") always
    # score low against individual code chunks, but the REPO_MAP retrieved for
    # them may well answer the question — let the LLM grader judge that
    # instead of short-circuiting to "weak".
    if top_score <= KB_GRADE_LOW_CONFIDENCE and not has_repo_map:
        return {"kb_grade": "weak"}  # skip the LLM call entirely
    # ambiguous zone — fall through to the actual LLM judgment
    context = build_context_text(state["kb_results"])
    prompt = GRADE_PROMPT.format(question=state["question"], context=context)
    #print("LLM CALL FIRED", flush=True)
    response = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.0)
    grade = response.strip().lower()
    if grade not in ("good", "weak"):
        grade = "weak"  # safe default — prefer falling back over false confidence
    return {"kb_grade": grade}

def generate_kb_node(state: dict) -> dict:
    context = build_context_text(state["kb_results"])
    prompt = GENERATE_KB_PROMPT.format(question=state["question"], context=context)
    answer = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.2)
    return {"answer": answer, "source": "kb"}

def web_search_node(state: dict) -> dict:
    results = web_search_tool.search(state["question"], max_results=5)
    return {"web_results": results}

def grade_web_node(state: dict) -> dict:
    context = "\n\n".join(
        f"{r['title']}\n{r['content']}\n{r['url']}"
        for r in state["web_results"]
    )
    prompt = GRADE_WEB_PROMPT.format(question=state["question"], context=context)
    response = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.0)
    grade = response.strip().lower()
    if grade not in ("good", "weak"):
        grade = "weak"  # safe default — prefer falling back over false confidence
    return {"web_grade": grade if grade in ("good", "weak") else "weak"}


def generate_web_node(state: dict) -> dict:
    context = "\n\n".join(
        f"{r['title']}\n{r['content']}\n{r['url']}"
        for r in state["web_results"]
    )
    prompt = GENERATE_WEB_PROMPT.format(question=state["question"], context=context)
    answer = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.2)
    return {"answer": answer, "source": "web"}

def fallback_node(state: dict) -> dict:
    prompt = FALLBACK_PROMPT.format(question=state["question"])
    answer = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.3)
    return {"answer": answer, "source": "fallback"}

def direct_node(state: dict) -> dict:
    prompt = DIRECT_PROMPT.format(question=state["question"])
    answer = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.3)
    return {"answer": answer, "source": "direct"}


#if __name__ == "__main__":
    # import argparse
    # parser = argparse.ArgumentParser()
    # # parser.add_argument("--test", choices=["router", "grade_kb", "grade_web", "fallback"], required=True)
    # parser.add_argument("--question", default="How does the login function work?")
    # args = parser.parse_args()

    # if args.test == "router":
    #     print(router_node({"question": args.question}))
    # elif args.test == "grade_kb":
    #     fake = {"question": args.question, "kb_results": [{"file_path": "x.py", "start_line": 1, "end_line": 2, "content": "def x(): pass"}]}
    #     print(grade_kb_node(fake))
    # elif args.test == "grade_web":
    #     fake = {"question": args.question, "web_results": [{"title": "irrelevant", "content": "unrelated content"}]}
    #     print(grade_web_node(fake))
    # elif args.test == "fallback":
    #     print(fallback_node({"question": args.question}))


    # result = retrieve_kb_node({"question": args.question})
    # for r in result["kb_results"]:
    #     print(r["file_path"], "-", r["function_name"])

if __name__ == "__main__":
    # test_cases = [
    #     ("what does this project do overall", True),
    #     ("what does parse_config do", False),
    #     ("how do I explain this project in an interview", True),
    #     ("what does validate_token do", False),
    #     ("how does the router work", False),  # borderline — decide what you WANT here
    # ]
    # for q, expected in test_cases:
    #     got = _is_project_level_question(q)
    #     status = "OK" if got == expected else "MISMATCH"
    #     print(f"[{status}] '{q}' -> {got} (expected {expected})")

    high = {"question": "x", "kb_results": [{"score": 0.62, "content": "...", "file_path": "a.py", "start_line": 1, "end_line": 1}]}
    low = {"question": "x", "kb_results": [{"score": 0.12, "content": "...", "file_path": "a.py", "start_line": 1, "end_line": 1}]}
    mid = {"question": "x", "kb_results": [{"score": 0.30, "content": "...", "file_path": "a.py", "start_line": 1, "end_line": 1}]}
    print("high:", grade_kb_node(high))   # should return instantly, no LLM call
    print("low:", grade_kb_node(low))     # should return instantly, no LLM call
    print("mid:", grade_kb_node(mid))     # should make a real LLM call, take longer