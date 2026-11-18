import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from uuid import uuid4

# Ensure the project root is on sys.path BEFORE any `from app...` imports.
# This makes the module runnable standalone (python app/api/routes.py) as
# well as via uvicorn/python -m.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from fastapi import Depends
from app.api.security import require_api_key
from app.ingestion.clone import get_repo_name
from app.ingestion.embed_store import ingest_repo, list_ingested_repos, warmup
from app.agent.graph import agent_graph
from app import metrics
from app.persistence import job_store


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Warm the embedding models before serving traffic.

    Without this, the first chat request pays the full SentenceTransformer +
    BM25 load inside `retrieve_kb`, which shows up as a bogus ~7s p99 in the
    latency metrics. The warm-up runs in a threadpool because it is blocking
    (model load + CPU encode).
    """
    job_store.init_db()
    interrupted = job_store.mark_interrupted_jobs()
    if interrupted:
        print(f"[startup] Marked {interrupted} interrupted ingestion jobs")

    try:
        elapsed = await run_in_threadpool(warmup)
        print(f"[startup] embedding models warm in {elapsed}s")
    except Exception as e:
        # A failed warm-up must not stop the server — the models will just load
        # lazily on the first request instead.
        print(f"[startup] warmup failed ({e}); models will load on first request")
    yield


app = FastAPI(title="Agentic Codebase RAG Assistant", dependencies=[Depends(require_api_key)], lifespan=lifespan)

class IngestRequest(BaseModel):
    repo_url:str
    force:bool= False 

class IngestResponse(BaseModel):
    repo_name:str 
    chunks_stored: int 

class IngestJobAccepted(BaseModel):
    job_id: str
    repo_name: str

class IngestJobStatus(BaseModel):
    job_id: str
    repo_name: str
    status: str                     # queued | running | done | error
    stage: str                      # human-readable pipeline milestone
    chunks_stored: int | None = None
    elapsed_s: float = 0.0
    error: str | None = None

class RepoResponse(BaseModel):
    repo_name: str
    points: int

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    question:str 
    repo_name: str
    history: list[ChatMessage] = []



class ChatResponse(BaseModel):
    answer:str 
    source:str

class DebugChatResponse(BaseModel):
    route: str
    kb_grade: str | None = None
    web_grade: str | None = None
    answer: str
    source: str



@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    t0 = time.perf_counter()
    try:
        result = agent_graph.invoke({
            "question": req.question,
            "repo_name": req.repo_name,
            "history": [h.model_dump() for h in req.history],
        })
        metrics.record("chat_total", time.perf_counter()- t0)
        return ChatResponse(answer=result["answer"], source=result["source"])
    except Exception as e:
        # Failed requests are still latency samples — recording them keeps
        # `chat_total` an honest picture of what users actually waited for.
        metrics.record("chat_total", time.perf_counter()- t0)
        metrics.record("chat_error", time.perf_counter()- t0)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/debug", response_model=DebugChatResponse)

def chat_debug(req: ChatRequest):
    # The frontends use /chat/debug, so it must record the same total as /chat
    # — otherwise chat_total only ever reflects API traffic, never UI traffic.
    t0 = time.perf_counter()
    try:
        result = agent_graph.invoke({
            "question": req.question,
            "repo_name": req.repo_name,
            "history": [h.model_dump() for h in req.history],
        })
        metrics.record("chat_total", time.perf_counter()- t0)
        return DebugChatResponse(**{k: result.get(k) for k in DebugChatResponse.model_fields})
    except Exception as e:
        metrics.record("chat_total", time.perf_counter()- t0)
        metrics.record("chat_error", time.perf_counter()- t0)
        raise HTTPException(status_code=500, detail=str(e))

def _derive_repo_name(repo_url: str) -> str:
    """Name a repo exactly the way ingest_repo will store it in point payloads.

    Keeping one implementation means the response body, the async job record and
    the Qdrant payload can never disagree about what the repo is called.
    """
    if "://" in repo_url or repo_url.startswith("git@"):
        return get_repo_name(repo_url)
    return Path(repo_url).resolve().name


def validate_github_url(repo_url: str) -> None:
    """Ensure the URL is a HTTPS GitHub repository before any clone/ingest."""
    from urllib.parse import urlparse
    from fastapi import HTTPException

    parsed = urlparse(repo_url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise HTTPException(
            status_code=400,
            detail="Only HTTPS repositories hosted on github.com are supported",
        )
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) != 2:
        raise HTTPException(
            status_code=400,
            detail="Expected https://github.com/owner/repository",
        )
    owner, repo = parts
    if not owner or not repo:
        raise HTTPException(
            status_code=400,
            detail="Invalid repository path",
        )


@app.post("/ingest", response_model=IngestResponse)
def ingest(req:IngestRequest):
    validate_github_url(req.repo_url)  # ensure only HTTPS GitHub URLs are accepted
    try:
        repo_name = _derive_repo_name(req.repo_url)
        # Full pipeline: clean clone (URLs) -> chunk -> delete stale points ->
        # store chunks -> store REPO_MAP structural context.
        n = ingest_repo(req.repo_url, force=req.force, repo_name=repo_name)
        return IngestResponse(repo_name=repo_name,chunks_stored=n)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------------------------
# Async ingestion (what the UIs use)
# ----------------------------------------------------------------------
# Ingesting a real repo takes minutes: AST chunking, CPU embedding of every
# chunk (~1.2s per batch of 32), upsert, then the REPO_MAP encode. That outlives
# any sane HTTP client timeout, and uvicorn keeps running the handler after the
# client disconnects — so a browser that gave up still got the repo indexed
# while showing an error, and never learned the repo name.
#
# /ingest/async therefore returns 202 immediately and clients poll
# /ingest/status/{job_id} for the current stage. The synchronous /ingest above
# stays for CLI/API callers that genuinely want to block.
#
# Jobs live in this process only (fine for the single worker this app runs):
# a --reload/restart drops them, and the status endpoint then returns 404, which
# the frontends treat as "job lost — fall back to /repos".
def _update_job(job_id: str, **fields) -> None:
    """Persist ingestion progress and status."""
    job_store.update_job(job_id, **fields)


def _run_ingest_job(
    job_id: str,
    repo_url: str,
    force: bool,
    repo_name: str,
) -> None:
    """Background worker with persistent job tracking."""
    _update_job(
        job_id,
        status="running",
        stage="Starting ...",
    )
    try:
        n = ingest_repo(
            repo_url,
            force=force,
            repo_name=repo_name,
            progress=lambda stage: _update_job(
                job_id,
                stage=stage,
            ),
        )
        _update_job(
            job_id,
            status="done",
            stage=f"Indexed {n} chunks",
            chunks_stored=n,
        )
    except Exception as e:
        _update_job(
            job_id,
            status="error",
            stage="Failed",
            error=str(e),
        )


@app.post("/ingest/async", response_model=IngestJobAccepted, status_code=202)
def ingest_async(req: IngestRequest):
    """Queue an ingestion and return immediately; poll /ingest/status/{job_id}."""
    validate_github_url(req.repo_url)  # ensure only HTTPS GitHub URLs are accepted
    repo_name = _derive_repo_name(req.repo_url)
    job_id = uuid4().hex
    job_store.create_job(job_id, repo_name)
    threading.Thread(
        target=_run_ingest_job,
        args=(job_id, req.repo_url, req.force, repo_name),
        name=f"ingest-{repo_name}",
        daemon=True,
    ).start()
    return IngestJobAccepted(job_id=job_id, repo_name=repo_name)


@app.get("/ingest/status/{job_id}", response_model=IngestJobStatus)
def ingest_status(job_id: str):
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown ingest job")
    start_time = job.get("started_at") or job.get("created_at") or time.time()
    end_time = job.get("completed_at") or time.time()
    elapsed_s = round(end_time - start_time, 1)

    return IngestJobStatus(
        job_id=job["job_id"],
        repo_name=job["repo_name"],
        status=job["status"],
        stage=job["stage"],
        chunks_stored=job["chunks_stored"],
        elapsed_s=elapsed_s,
        error=job["error"],
    )

@app.get("/metrics")
def get_metrics():
    """
    Returns p50 / p95 / p99 latency (ms) for each pipeline stage.
    Stages tracked: router, rewrite_query, retrieve_kb, grade_kb,
                    web_search, grade_web, generate_kb, generate_web,
                    fallback, direct, chat_total, chat_error
    """
    return {"latency": metrics.get_all_percentiles()}


@app.post("/metrics/reset")
def reset_metrics():
    """Clear all recorded latency samples (useful before a clean measurement run)."""
    metrics.reset()
    return {"status": "cleared"}




@app.get("/repos", response_model=list[RepoResponse])
def repos():
    """Repos already indexed in Qdrant, so a UI session can reuse one."""
    try:
        return [RepoResponse(**r) for r in list_ingested_repos()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



if __name__ == "__main__":
    import argparse
    from fastapi.testclient import TestClient

    parser = argparse.ArgumentParser()
    parser.add_argument("--test", choices=["ingest", "ingest_async", "repos", "chat"], required=True)
    parser.add_argument("--repo_url", default="https://github.com/tiangolo/fastapi")
    parser.add_argument("--question", default="How does dependency injection work?")
    args = parser.parse_args()

    client = TestClient(app)

    if args.test == "ingest":
        resp = client.post("/ingest", json={"repo_url": args.repo_url})
        print(resp.status_code, resp.json())
    elif args.test == "ingest_async":
        resp = client.post("/ingest/async", json={"repo_url": args.repo_url})
        print(resp.status_code, resp.json())
        job_id = resp.json()["job_id"]
        while True:
            snap = client.get(f"/ingest/status/{job_id}").json()
            print(f"  {snap['status']:8} {snap['elapsed_s']:6}s  {snap['stage']}")
            if snap["status"] in ("done", "error"):
                print("  chunks_stored:", snap["chunks_stored"], "| error:", snap["error"])
                break
            time.sleep(2)
    elif args.test == "repos":
        resp = client.get("/repos")
        print(resp.status_code, resp.json())
    elif args.test == "chat":
        resp = client.post("/chat", json={"question": args.question})
        print(resp.status_code, resp.json())
    

