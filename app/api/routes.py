import os
import sys
import threading
import time
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
from app.ingestion.clone import get_repo_name
from app.ingestion.embed_store import ingest_repo, list_ingested_repos
from app.agent.graph import agent_graph

app = FastAPI(title="Agentic Codebase RAG Assistant")

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
    try:
        result = agent_graph.invoke({
            "question": req.question,
            "repo_name": req.repo_name,
            "history": [h.model_dump() for h in req.history],
        })        
        return ChatResponse(answer=result["answer"], source=result["source"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/debug", response_model=DebugChatResponse)

def chat_debug(req: ChatRequest):
    result = agent_graph.invoke({
        "question": req.question,
        "repo_name": req.repo_name,
        "history": [h.model_dump() for h in req.history],
    })
    return DebugChatResponse(**{k: result.get(k) for k in DebugChatResponse.model_fields})

def _derive_repo_name(repo_url: str) -> str:
    """Name a repo exactly the way ingest_repo will store it in point payloads.

    Keeping one implementation means the response body, the async job record and
    the Qdrant payload can never disagree about what the repo is called.
    """
    if "://" in repo_url or repo_url.startswith("git@"):
        return get_repo_name(repo_url)
    return Path(repo_url).resolve().name


@app.post("/ingest", response_model=IngestResponse)
def ingest(req:IngestRequest):
    try:
        repo_name = _derive_repo_name(req.repo_url)
        # Full pipeline: clean clone (URLs) -> chunk -> delete stale points ->
        # store chunks -> store REPO_MAP structural context.
        n = ingest_repo(req.repo_url, force=req.force, repo_name=repo_name)
        return IngestResponse(repo_name=repo_name,chunks_stored=n)

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
_INGEST_JOBS: dict[str, dict] = {}
_INGEST_JOBS_LOCK = threading.Lock()


def _update_job(job_id: str, **fields) -> None:
    with _INGEST_JOBS_LOCK:
        job = _INGEST_JOBS.get(job_id)
        if job is not None:
            job.update(fields)


def _run_ingest_job(job_id: str, repo_url: str, force: bool, repo_name: str) -> None:
    """Background worker: run the ingest pipeline and track its stage."""
    _update_job(job_id, status="running", stage="Starting ...")
    try:
        n = ingest_repo(
            repo_url,
            force=force,
            repo_name=repo_name,
            progress=lambda stage: _update_job(job_id, stage=stage),
        )
        _update_job(job_id, status="done", stage=f"Indexed {n} chunks", chunks_stored=n)
    except Exception as e:
        # Errors are reported through the status payload instead of a response
        # body, since the client is long gone by the time most of them happen.
        _update_job(job_id, status="error", stage="Failed", error=str(e))


@app.post("/ingest/async", response_model=IngestJobAccepted, status_code=202)
def ingest_async(req: IngestRequest):
    """Queue an ingestion and return immediately; poll /ingest/status/{job_id}."""
    repo_name = _derive_repo_name(req.repo_url)
    job_id = uuid4().hex
    with _INGEST_JOBS_LOCK:
        _INGEST_JOBS[job_id] = {
            "job_id": job_id,
            "repo_name": repo_name,
            "status": "queued",
            "stage": "Queued",
            "chunks_stored": None,
            "error": None,
            "started_at": time.time(),
        }
    threading.Thread(
        target=_run_ingest_job,
        args=(job_id, req.repo_url, req.force, repo_name),
        name=f"ingest-{repo_name}",
        daemon=True,
    ).start()
    return IngestJobAccepted(job_id=job_id, repo_name=repo_name)


@app.get("/ingest/status/{job_id}", response_model=IngestJobStatus)
def ingest_status(job_id: str):
    with _INGEST_JOBS_LOCK:
        job = _INGEST_JOBS.get(job_id)
        snapshot = dict(job) if job is not None else None
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Unknown ingest job (backend restarted?)")
    return IngestJobStatus(
        job_id=snapshot["job_id"],
        repo_name=snapshot["repo_name"],
        status=snapshot["status"],
        stage=snapshot["stage"],
        chunks_stored=snapshot["chunks_stored"],
        elapsed_s=round(time.time() - snapshot["started_at"], 1),
        error=snapshot["error"],
    )


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
    

