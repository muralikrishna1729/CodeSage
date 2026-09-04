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
from app.ingestion.clone import clone_repo, get_repo_name
from app.ingestion.chunker import chunk_repo
from app.ingestion.embed_store import store_chunks
from app.agent.graph import agent_graph

app = FastAPI(title="Agentic Codebase RAG Assistant")

class IngestRequest(BaseModel):
    repo_url:str
    force:bool= False 

class IngestResponse(BaseModel):
    repo_name:str 
    chunks_stored: int 

class ChatRequest(BaseModel):
    question:str 

class ChatResponse(BaseModel):
    answer:str 
    source:str

@app.post("/ingest", response_model=IngestResponse)
def ingest(req:IngestRequest):
    try:
        local_path = clone_repo(req.repo_url, force= req.force)
        repo_name = get_repo_name(req.repo_url)
        chunks = chunk_repo(local_path)
        n = store_chunks(chunks, repo_name = repo_name)
        return IngestResponse(repo_name=repo_name,chunks_stored=n)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        result = agent_graph.invoke({"question": req.question})
        return ChatResponse(answer=result["answer"], source=result["source"])
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
    

