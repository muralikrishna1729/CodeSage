import os
import sys

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
from app.ingestion.embed_store import ingest_repo
from app.agent.graph import agent_graph

app = FastAPI(title="Agentic Codebase RAG Assistant")

class IngestRequest(BaseModel):
    repo_url:str
    force:bool= False 

class IngestResponse(BaseModel):
    repo_name:str 
    chunks_stored: int 

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

@app.post("/ingest", response_model=IngestResponse)
def ingest(req:IngestRequest):
    try:
        # Derive the repo name the same way ingest_repo's payloads will, so the
        # response matches what's actually stored.
        if "://" in req.repo_url or req.repo_url.startswith("git@"):
            repo_name = get_repo_name(req.repo_url)
        else:
            repo_name = Path(req.repo_url).resolve().name
        # Full pipeline: clean clone (URLs) -> chunk -> delete stale points ->
        # store chunks -> store REPO_MAP structural context.
        n = ingest_repo(req.repo_url, force=req.force, repo_name=repo_name)
        return IngestResponse(repo_name=repo_name,chunks_stored=n)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



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
    

