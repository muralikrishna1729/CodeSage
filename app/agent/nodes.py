from app.agent.llm_client import llm_client
from app.ingestion.embed_store import search as kb_search
from app.tools.web_search import web_search_tool

ROUTER_PROMPT = """Classify this question into exactly one category. Reply with ONLY the category word, nothing else.

Categories:
- kb: question about specific code, functions, or how this codebase works
- web: question about external errors, library versions, or things outside this codebase
- direct: general programming knowledge question not specific to this codebase

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

def retrieve_kb_node(state: dict) -> dict:
    results = kb_search(state["question"], top_k=5)
    return {"kb_results": results}

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

def generate_kb_node(state: dict) -> dict:
    context = "\n\n".join(
        f"{r['file_path']}:{r['start_line']}-{r['end_line']}\n{r.get('content', '')}"
        for r in state["kb_results"]
    )
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