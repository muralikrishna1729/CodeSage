# Phase 4 — Exploration Guide (Structural Context → Frontend → Final Packaging)

> Same format: think-first question, reveal, self-test. This is the last
> planned phase — after this, the project is demo-ready end to end.

**What's left, and why it's Phase 4:** Phase 1 built `repo_map.py`
(directory tree + README/key files) but it was never actually wired into
retrieval — `retrieve_kb_node` in Phase 2 only pulls code chunks. That gap
matters: "how does the auth flow work" needs the structural layer, not just
function-level chunks. This phase closes that gap, adds a usable frontend
and packages the whole
thing so it runs with one command for a demo.

---

# PART A — Wiring structural context into retrieval

## Stage 0 — Think first

Go back to your own architecture notes: "3 layers of understanding" —
file-level chunks, structural understanding, retrieval-time context
assembly. Layer 3 was always meant to inject the repo-map alongside normal
top-k chunks for architecture-flavored questions.

**Question:** how would you decide, at query time, whether a question needs
the structural layer added in? Two options to weigh yourself before looking
at the reveal:
1. Always inject the repo-map into every KB query, regardless of question
2. Only inject it when some signal suggests the question is about
   architecture/flow rather than a single function

Think about the cost/tradeoff of each — what does option 1 cost you in
every single prompt, and what does option 2 risk missing if the signal is
wrong?

## Reveal — storing the repo map as a retrievable chunk

First, decide: should the repo map be embedded and searched like any other
chunk (so it competes in the normal top-k), or injected separately and
unconditionally alongside whatever top-k already returns? The second is
simpler and avoids the repo-map "losing" to more specific code chunks in a
similarity ranking it was never meant to compete in.

```python
# addition to app/ingestion/embed_store.py

from app.ingestion.repo_map import build_repo_map

def store_repo_map(repo_path: str, repo_name: str, collection: str = "codebase_chunks"):
    rm = build_repo_map(repo_path)
    summary_text = "DIRECTORY STRUCTURE:\n" + rm["directory_tree"] + "\n\n"
    for fname, content in rm["key_files"].items():
        summary_text += f"--- {fname} ---\n{content}\n\n"

    vector = model.encode(summary_text).tolist()
    point = PointStruct(
        id=str(uuid.uuid4()),
        vector=vector,
        payload={
            "repo": repo_name,
            "file_path": "REPO_MAP",
            "function_name": "STRUCTURE",
            "start_line": 0,
            "end_line": 0,
            "content": summary_text,
        },
    )
    client.upsert(collection_name=collection, points=[point])
```

**Question:** why give it a sentinel `file_path="REPO_MAP"` the same way
Phase 1's chunker used `function_name="FILE"` as a sentinel? Think about how
you'd later filter or specifically fetch this one chunk versus letting it
compete blindly in every top-k search.

## Reveal — updating retrieve_kb_node to always include it

```python
# updated app/agent/nodes.py — retrieve_kb_node

from app.ingestion.embed_store import search as kb_search, get_repo_map_chunk

def retrieve_kb_node(state: dict) -> dict:
    results = kb_search(state["question"], top_k=5)
    repo_map_chunk = get_repo_map_chunk()  # fetched separately, not via similarity search
    if repo_map_chunk:
        results = [repo_map_chunk] + results
    return {"kb_results": results}
```

You'll need a small `get_repo_map_chunk()` helper in `embed_store.py` that
does a direct payload filter (`file_path == "REPO_MAP"`) rather than a
vector search — since you decided above this shouldn't compete in
similarity ranking.

**Question to check your understanding:** does this change affect
`grade_kb_node` at all? Trace through what `grade_kb_node` does with
`state["kb_results"]` — does having the repo-map chunk always present risk
making the LLM grader too lenient (always seeing "some" context, even for
questions the repo genuinely doesn't answer)? Is that a real risk or not?

**Self-test:**
```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default="How does the router node decide where to send a question?")
    args = parser.parse_args()
    result = retrieve_kb_node({"question": args.question})
    for r in result["kb_results"]:
        print(r["file_path"], "-", r["function_name"])
```
```bash
python -m app.agent.nodes --question "how is this project structured overall"
```
**Predict first:** should the repo-map chunk noticeably help THIS
particular question compared to before you wired it in? Compare the
generated answer before/after this change on a deliberately architecture-
flavored question — that's the actual test, not just confirming the chunk
appears in the list.

---

# PART B — Chainlit frontend

## Stage 0 — Think first

You already have working `/ingest` and `/chat` endpoints from Phase 3. A
frontend here is just a thin UI calling those two endpoints — no new agent
logic. Chainlit is purpose-built for this: chat UI, message history, and
step-by-step reasoning display all come from a handful of decorators rather
than hand-rolled session-state management.

**Question:** Chainlit's two core decorators are `@cl.on_chat_start` and
`@cl.on_message`. Given what each name implies, which one should hold your
one-time setup (like prompting for a repo URL to ingest) versus your
per-question logic (calling `/chat`)? Think it through before the reveal.

## Reveal — basic chat wiring

```python
# app/frontend/chainlit_app.py
import chainlit as cl
import requests

API_URL = "http://localhost:8000"


@cl.on_chat_start
async def start():
    await cl.Message(
        content="Paste a GitHub repo URL to ingest it, or just ask a question if one's already indexed."
    ).send()


@cl.on_message
async def main(message: cl.Message):
    text = message.content.strip()

    # crude heuristic: treat anything that looks like a repo URL as an ingest request
    if text.startswith("https://github.com/"):
        async with cl.Step(name="Ingesting repo") as step:
            resp = requests.post(f"{API_URL}/ingest", json={"repo_url": text})
            if resp.status_code == 200:
                data = resp.json()
                step.output = f"Indexed {data['chunks_stored']} chunks from {data['repo_name']}"
            else:
                step.output = f"Ingestion failed: {resp.text}"
        await cl.Message(content=step.output).send()
        return

    resp = requests.post(f"{API_URL}/chat", json={"question": text})
    if resp.status_code == 200:
        data = resp.json()
        await cl.Message(
            content=data["answer"],
            elements=[cl.Text(name="source", content=data["source"], display="inline")],
        ).send()
    else:
        await cl.Message(content=f"Request failed: {resp.text}").send()
```

**Question to check your understanding:** why is the ingest-vs-chat branch
here a crude string-prefix heuristic (`startswith("https://github.com/")`)
rather than two separate UI elements (a text box for URLs, a chat box for
questions)? What's the tradeoff — simpler for the user, or just simpler for
you to build? Worth improving later with `cl.AskUserMessage` for a proper
ingest flow.

## Reveal — showing the agent's actual reasoning steps

This is the part Streamlit can't do natively, and it's the reason Chainlit
fits this specific project. Instead of `/chat` being a black box, expose
the graph's intermediate node outputs as visible steps.

**Think first:** to show "Router decided: kb" as a visible step before the
final answer, does `cl.Step` need to wrap the whole `/chat` HTTP call, or
does the *graph itself* need to report progress node-by-node? What does
that imply about doing this through a single `requests.post()` to your
existing `/chat` endpoint versus needing a different endpoint?

```python
# updated on_message — showing step-by-step reasoning

@cl.on_message
async def main(message: cl.Message):
    text = message.content.strip()
    if text.startswith("https://github.com/"):
        # ... same ingest branch as above ...
        return

    async with cl.Step(name="Routing question") as route_step:
        resp = requests.post(f"{API_URL}/chat/debug", json={"question": text})
        data = resp.json()
        route_step.output = f"Routed to: {data['route']}"

    if data.get("kb_grade"):
        async with cl.Step(name="Grading KB evidence") as grade_step:
            grade_step.output = f"KB grade: {data['kb_grade']}"

    if data.get("web_grade"):
        async with cl.Step(name="Grading web evidence") as grade_step:
            grade_step.output = f"Web grade: {data['web_grade']}"

    await cl.Message(
        content=data["answer"],
        elements=[cl.Text(name="source", content=data["source"], display="inline")],
    ).send()
```

This requires a new `/chat/debug` endpoint in `app/api/routes.py` returning
the **full final state** instead of just `answer`/`source` — since
`agent_graph.invoke()` already returns the complete state dict, this is a
small addition:

```python
# addition to app/api/routes.py

class DebugChatResponse(BaseModel):
    route: str
    kb_grade: str | None = None
    web_grade: str | None = None
    answer: str
    source: str

@app.post("/chat/debug", response_model=DebugChatResponse)
def chat_debug(req: ChatRequest):
    result = agent_graph.invoke({"question": req.question})
    return DebugChatResponse(**{k: result.get(k) for k in DebugChatResponse.model_fields})
```

**Question:** why add a *separate* `/chat/debug` endpoint instead of always
returning the full state from `/chat` itself? Think about API design —
should a production chat endpoint's response shape depend on whether a
debug UI happens to be consuming it?

**Self-test:** Chainlit apps run via their own CLI, not `argparse`/`main()`:
```bash
uvicorn app.api.routes:app --reload      # terminal 1
chainlit run app/frontend/chainlit_app.py -w   # terminal 2, -w = auto-reload
```
**What to actually verify:**
1. Paste a real repo URL — does the ingest step show up as a collapsible
   step with the chunk count, or does it just look like a normal message?
2. Ask a KB-eligible question — do you see "Routing question" and "Grading
   KB evidence" as separate visible steps before the final answer? That
   step-by-step visibility is the actual payoff of choosing Chainlit here —
   if it's not showing, something in the `cl.Step` wiring needs fixing
   before you'd want to demo this.
3. Ask a nonsense question — do you see it route to `kb`, grade `weak`,
   presumably also try web and grade that `weak` too, ending in a fallback
   answer? Watching that whole decision chain visibly is the demo moment
   worth building this for.

# PART C — Final packaging

## Stage 0 — Think first

**Question:** if you handed this repo to someone else (or a future version
of yourself six months from now) with zero context, what's the minimum set
of things they'd need to get it running? List them before the reveal.

## Reveal — full `docker-compose.yml`

```yaml
version: "3.8"
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - ./qdrant_data:/qdrant/storage
```

Notice this is the SAME compose file from Phase 1 — the FastAPI app and
Chainlit frontend still run directly via `uvicorn`/`chainlit run` rather
than being containerized themselves. **Question:** is that a gap worth
closing, or a reasonable scope boundary for a portfolio project? Think about
what containerizing the app itself would actually buy you here versus the
setup complexity it adds.

## Reveal — a minimal `README.md` structure worth writing

```markdown
# Agentic Codebase RAG Assistant

[one-paragraph pitch]

## Architecture
[your diagram]

## Setup
1. docker compose up -d
2. pip install -r requirements.txt
3. cp .env.example .env  (fill in free API keys)
4. uvicorn app.api.routes:app --reload
5. chainlit run app/frontend/chainlit_app.py -w

## Demo script
1. Ingest [some public repo] via sidebar
2. Ask [a KB-eligible question] -> shows file:line citation
3. Ask [a web-eligible question] -> shows it routes to search
4. Ask [nonsense] -> shows honest fallback

## Eval results
[paste your RAGAS scores from Phase 3 here]
```

**Question, the real one to sit with before wrapping up:** of everything
across all four phases, which single decision would you defend hardest in
an interview if pushed on it — the AST-aware chunking, the corrective-RAG
grading step, the free-tier fallback cascades, the Docker-sandboxed
execution tool, or something else? You should be able to answer this in
under 60 seconds, with the tradeoff included, not just the feature.

---

# Phase 4 "Done" checklist

- [ ] Repo-map chunk wired into `retrieve_kb_node`, verified it actually
      changes the answer quality on an architecture-flavored question
- [ ] Checked whether always-present repo-map context risks making
      `grade_kb_node` too lenient — and formed an actual opinion on it
- [ ] Chainlit frontend running against live `/ingest` and `/chat`, with
      routing/grading steps visibly displayed per question
- [ ] Honestly checked whether multi-turn conversation context actually
      works end-to-end, or only appears to in the UI
- [ ] `docker-compose.yml` + `.env.example` + `README.md` are enough for a
      stranger to get this running from scratch
- [ ] Can defend one specific design decision, with its tradeoff, in under
      60 seconds

---

Once you've worked through this, we're at "all phases generated" — from
here it's the doubts/clarification mode you mentioned. Go build, and bring
back whatever breaks or whatever you want to push back on.
