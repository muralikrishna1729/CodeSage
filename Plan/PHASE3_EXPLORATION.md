# Phase 3 — Exploration Guide (FastAPI Endpoints → Code Execution Tool → RAGAS Eval)

> Same format: think-first question, then reveal, then a self-test via
> `argparse`/`main()` you run directly from the file.

**Scope carried over from Phase 1's plan:** FastAPI endpoints were originally
slated for Phase 2 but Phase 2 focused entirely on the agent core (state,
llm_client, web_search, nodes, graph) — so they land here instead, alongside
the two items always meant for Phase 3.

---

# PART A — `app/api/routes.py`

## Stage 0 — Think first

You have two working pieces so far: the Phase 1 ingestion pipeline
(`chunk_repo` → `store_chunks`) and the Phase 2 agent graph
(`agent_graph.invoke({"question": ...})`). Neither is reachable over HTTP
yet.

**Question:** how many endpoints does this actually need at minimum? Think
about the two distinct user actions — "index a new repo" and "ask a
question about an already-indexed repo" — are these the same request, or
two separate ones? What should each endpoint's request body look like?

## Reveal

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.ingestion.clone import clone_repo, get_repo_name
from app.ingestion.chunker import chunk_repo
from app.ingestion.embed_store import store_chunks
from app.agent.graph import agent_graph

app = FastAPI(title="Agentic Codebase RAG Assistant")


class IngestRequest(BaseModel):
    repo_url: str
    force: bool = False


class IngestResponse(BaseModel):
    repo_name: str
    chunks_stored: int


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    source: str


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest):
    try:
        local_path = clone_repo(req.repo_url, force=req.force)
        repo_name = get_repo_name(req.repo_url)
        chunks = chunk_repo(local_path)
        n = store_chunks(chunks, repo_name=repo_name)
        return IngestResponse(repo_name=repo_name, chunks_stored=n)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        result = agent_graph.invoke({"question": req.question})
        return ChatResponse(answer=result["answer"], source=result["source"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**Question to check your understanding:** why is `/ingest` a separate call
from `/chat`, rather than having `/chat` auto-ingest a repo URL on first
question? Think about cost and latency — ingesting a large repo can take
minutes (cloning, chunking, embedding); should a chat response ever be
blocked on that?

**Self-test — FastAPI apps don't fit the same `argparse` pattern as a
plain script, since they need a running server.** Instead, use FastAPI's
`TestClient`, which lets you call endpoints in-process without actually
starting uvicorn:

```python
if __name__ == "__main__":
    import argparse
    from fastapi.testclient import TestClient

    parser = argparse.ArgumentParser()
    parser.add_argument("--test", choices=["ingest", "chat"], required=True)
    parser.add_argument("--repo_url", default="https://github.com/tiangolo/fastapi")
    parser.add_argument("--question", default="How does dependency injection work?")
    args = parser.parse_args()

    client = TestClient(app)

    if args.test == "ingest":
        resp = client.post("/ingest", json={"repo_url": args.repo_url})
        print(resp.status_code, resp.json())
    elif args.test == "chat":
        resp = client.post("/chat", json={"question": args.question})
        print(resp.status_code, resp.json())
```
```bash
python -m app.api.routes --test ingest --repo_url https://github.com/tiangolo/fastapi
python -m app.api.routes --test chat --question "How does dependency injection work?"
```

**For actually running the server** (not just the in-process test):
```bash
uvicorn app.api.routes:app --reload
```
Then hit `http://localhost:8000/docs` — FastAPI auto-generates an
interactive Swagger UI from your Pydantic models, useful for manual testing
without writing curl commands.

**Expected behavior to verify yourself:** does `/ingest` on a repo you've
already ingested (without `force=True`) reuse the clone and just re-chunk +
re-store, or does it fail? Trace through `clone_repo`'s logic from Phase 1
to answer this before testing it.

---

# PART B — `app/tools/code_exec.py`

## Stage 0 — Think first

This is the tool that pushes the project from "agentic RAG" (routing +
retrieval) into genuinely agentic (the LLM decides to take an action,
observes a real result, and can use that to verify its own explanation).

**Question:** if you let an LLM-generated string of Python code just get
`exec()`'d directly in your own Python process, what could go wrong? List at
least two concrete failure modes before looking at the reveal — think about
what a malicious or simply buggy piece of generated code could do to your
machine, your filesystem, or your running process.

## Reveal

```python
import subprocess
import tempfile
import os


def run_code_sandboxed(code: str, timeout: int = 10) -> dict:
    """
    Executes Python code in an isolated Docker container — not in this
    process. Returns stdout, stderr, and whether it succeeded.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        script_path = f.name

    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "--network", "none",              # no internet access from inside
                "--memory", "128m",                # cap memory
                "--cpus", "0.5",                   # cap CPU
                "-v", f"{script_path}:/sandbox/script.py:ro",  # read-only mount
                "python:3.11-slim",
                "python", "/sandbox/script.py",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": f"Execution timed out after {timeout}s"}
    finally:
        os.unlink(script_path)
```

**Did your failure-mode list include these?**
- Infinite loops / resource exhaustion → handled by `timeout` and
  `--memory`/`--cpus` caps
- Filesystem access to your real machine → handled by mounting the script
  `:ro` (read-only) and not mounting anything else — the container can't
  touch your actual filesystem
- Network calls out to exfiltrate data or hit arbitrary URLs → handled by
  `--network none`, which cuts all networking inside the container
- `--rm` ensures the container is deleted immediately after running, so
  nothing lingers or accumulates

**Question:** why write the code to a temp file and mount it into the
container, instead of passing the code as a string argument directly to
`docker run python -c "..."`? Think about shell-escaping — what happens if
the generated code itself contains quote characters?

**Self-test:**
```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", default="print('hello from sandbox')")
    args = parser.parse_args()
    print(run_code_sandboxed(args.code))
```
```bash
python -m app.tools.code_exec --code "print(2 + 2)"
```
**Expected output:**
```
{'success': True, 'stdout': '4\n', 'stderr': ''}
```

**Now deliberately test the guardrails, don't skip this:**
```bash
python -m app.tools.code_exec --code "while True: pass"
```
**Predict first:** should this hang forever, or return after ~10 seconds
with a timeout message? Run it and confirm.

```bash
python -m app.tools.code_exec --code "import socket; socket.create_connection(('8.8.8.8', 53), timeout=3)"
```
**Predict first:** should this succeed (proving network isn't actually
blocked — a real problem) or fail with a connection error (proving
`--network none` works)? This is the single most important guardrail to
verify before trusting this tool anywhere near an LLM's generated code.

---

# PART C — RAGAS Evaluation

## Stage 0 — Think first

Every earlier phase had you manually eyeball whether results "look right."
That doesn't scale, and it's not something you can put a number on in an
interview. RAGAS gives you actual metrics computed by an LLM-as-judge:
**faithfulness** (does the answer only claim things the retrieved context
actually supports — the core hallucination check) and **answer relevancy**
(does the answer actually address the question asked).

**Question:** what would you need to hand-collect to run an evaluation like
this? Think about what RAGAS needs per test case — not just a question, but
what else has to be captured from a real agent run to score it afterward.

## Reveal — building a small eval set

```python
# eval_dataset.py — a small, hand-curated set of test questions
EVAL_QUESTIONS = [
    "How does the router node decide where to send a question?",
    "What happens when KB evidence is graded as weak?",
    "How are code chunks embedded and stored?",
    # add 5-10 more, mixing kb/web/direct-eligible questions
]
```

**Question:** given RAGAS needs `question`, `answer`, `contexts` (what was
retrieved), and ideally a `ground_truth` for some metrics — which of these
do you already have sitting in `AgentState` after a graph run, and which
would you have to add yourself?

## Reveal — running the eval

```python
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy
from app.agent.graph import agent_graph
from eval_dataset import EVAL_QUESTIONS


def build_eval_dataset():
    rows = {"question": [], "answer": [], "contexts": []}
    for q in EVAL_QUESTIONS:
        result = agent_graph.invoke({"question": q})
        contexts = []
        if result.get("kb_results"):
            contexts = [r["content"] for r in result["kb_results"]]
        elif result.get("web_results"):
            contexts = [r["content"] for r in result["web_results"]]

        rows["question"].append(q)
        rows["answer"].append(result["answer"])
        rows["contexts"].append(contexts if contexts else ["(no context — fallback answer)"])

    return Dataset.from_dict(rows)


def run_eval():
    dataset = build_eval_dataset()
    scores = evaluate(dataset, metrics=[faithfulness, answer_relevancy])
    return scores
```

**Question before running this:** RAGAS's default metrics use an LLM judge
under the hood. Given your whole stack is free-tier, which of your existing
providers (Groq, Gemini) should you configure RAGAS to use as the judge, and
why might that choice matter for the fairness/accuracy of the eval itself?
(Recall your earlier stack decision — Gemini's free tier has notably higher
daily volume, which matters if you're evaluating a decent-sized question
set.)

**Self-test:**
```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    if args.run:
        scores = run_eval()
        print(scores)
```
```bash
python -m app.eval.run_eval --run
```
**Expected output:** a dict-like result with `faithfulness` and
`answer_relevancy` scores between 0 and 1 per question, plus an average.
**What counts as a good result here:** faithfulness scores noticeably lower
than 1.0 on fallback-sourced answers are actually *expected and correct* —
those answers are explicitly not grounded, so a lower faithfulness score
there validates that the fallback node is being honest, not that something
is broken. A low faithfulness score on a `kb`-sourced answer, though, is a
real problem worth investigating.

---

# Phase 3 "Done" checklist

- [ ] `/ingest` and `/chat` endpoints work via `TestClient`, and separately
      via a real running `uvicorn` server + the `/docs` UI
- [ ] Explained to yourself why ingest and chat are separate endpoints, not
      combined into one
- [ ] `code_exec.py`: confirmed the timeout guardrail actually fires on an
      infinite loop
- [ ] `code_exec.py`: confirmed the network guardrail actually blocks an
      outbound connection attempt — this is the one guardrail worth never
      skipping verification on
- [ ] Built a real eval set of 8–10 questions spanning kb/web/fallback paths
- [ ] Ran RAGAS and can explain, in your own words, why a low faithfulness
      score on a fallback answer is expected, while the same score on a
      kb-sourced answer would be a bug worth fixing

---

# Resume bullets this phase supports

- "Exposed the agentic RAG pipeline via FastAPI, with separate ingestion
  and chat endpoints to keep indexing latency off the chat request path"
- "Added a Docker-sandboxed code-execution tool (network-isolated,
  resource-capped) letting the agent verify its own explanations against
  real runtime behavior"
- "Evaluated the pipeline with RAGAS (faithfulness, answer relevancy)
  across a hand-curated question set spanning KB, web-fallback, and
  no-evidence-fallback paths"
