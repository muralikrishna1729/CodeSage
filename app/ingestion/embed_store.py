import os
import uuid
from pathlib import Path
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from qdrant_client.models import Filter, FieldCondition, MatchValue
from qdrant_client import models as qdrant_models
from app.ingestion.repo_map import build_repo_map
from app.config import settings

try:
    from .chunker import chunk_repo
    from .clone import clean_repo, get_repo_name
except ImportError:
    # Support running directly: python app/ingestion/embed_store.py
    from chunker import chunk_repo
    from clone import clean_repo, get_repo_name

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".model_cache")

_model = None
def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer('all-MiniLM-L6-v2', cache_folder=CACHE_DIR)
    return _model

def _build_client() -> QdrantClient:
    """Build the Qdrant handle from settings instead of hardcoding localhost,
    so the same code works in dev (localhost:6333 via docker-compose), inside
    the prod compose network (QDRANT_HOST=qdrant), and against Qdrant Cloud
    (full https URL + API key via QDRANT_HOST / QDRANT_API_KEY / QDRANT_HTTPS).
    """
    if "://" in settings.qdrant_host:
        kwargs: dict = {"url": settings.qdrant_host}
    else:
        kwargs = {"host": settings.qdrant_host, "port": settings.qdrant_port}
        if settings.qdrant_https:
            kwargs["https"] = True
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return QdrantClient(**kwargs)

client = _build_client()

def ensure_collection(name: str):
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )

def store_chunks(chunks, repo_name: str, collection: str = "codebase_chunks"):
    ensure_collection(collection)
    model = get_model()
    texts = [chunk.content for chunk in chunks]  # note: fixed to use .content, see below
    vectors = model.encode(texts, show_progress_bar=True).tolist()

    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vec,
            payload={
                "repo": repo_name,
                "file_path": c.file_path,
                "function_name": c.function_name,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "content": c.content,
            },
        )
        for c, vec in zip(chunks, vectors)
    ]
    client.upsert(collection_name=collection, points=points)
    return len(points)

def store_repo_map(repo_path:str, repo_name:str, collection:str = "codebase_chunks"):
    repo_map = build_repo_map(repo_path)
    summary_text = "DIRECTORY STRUCTURE:\n" + repo_map["directory_tree"] + "\n\n"
    for fname, content in repo_map["key_files"].items():
        summary_text += f"--- {fname} ---\n{content}\n\n"
    vector = get_model().encode(summary_text).tolist()
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
    client.upsert(collection_name=collection,points = [point])

def get_repo_map_chunk(repo_name: str, collection: str = "codebase_chunks") -> dict | None:
    """
    Fetch the stored repo-map chunk (file_path == "REPO_MAP") directly via a
    payload filter, bypassing similarity search.

    The repo-map describes whole-project structure, so it's deliberately kept
    out of the similarity ranking (it would otherwise crowd out fine-grained
    code chunks). Instead it is prepended as always-available context in
    ``retrieve_kb_node``.

    Args:
        collection: Qdrant collection to read from.

    Returns:
        A dict shaped like a ``search`` result (with ``content``), or ``None``
        if no REPO_MAP point has been stored for this collection.
    """
    results = client.scroll(
        collection_name=collection,
        scroll_filter=Filter(must=[
            FieldCondition(key="repo", match=MatchValue(value=repo_name)),
            FieldCondition(key="file_path", match=MatchValue(value="REPO_MAP")),
        ]),
        limit=1,
    )
    points, _ = results
    if not points:
        return None
    p = points[0]
    return {
        "score": 1.0, "file_path": "REPO_MAP", "function_name": "STRUCTURE",
        "start_line": 0, "end_line": 0, "content": p.payload["content"],
    }



def delete_repo_points(repo_name: str, collection: str = "codebase_chunks"):
    """Remove all stored points belonging to a repo so re-ingestion doesn't duplicate."""
    client.delete(
        collection_name=collection,
        points_selector=qdrant_models.FilterSelector(
            filter=qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(
                        key="repo", match=qdrant_models.MatchValue(value=repo_name)
                    )
                ]
            )
        ),
    )


def ingest_repo(
    repo_url_or_path: str,
    collection: str = "codebase_chunks",
    force: bool = False,
    repo_name: str | None = None,
) -> int:
    """
    Ingest a repo into Qdrant.

    Args:
        repo_url_or_path: A GitHub URL (cloned via clone.clean_repo) or a local repo path.
        collection: Qdrant collection to write into.
        force: If True, force a fresh re-clone when a URL is given.
        repo_name: Optional override for the repo name stored in each point's payload.

    Returns:
        Number of chunks stored.
    """
    ensure_collection(collection)

    if "://" in repo_url_or_path or repo_url_or_path.startswith("git@"):
        path = clean_repo(repo_url_or_path, force=force)
        name = repo_name or get_repo_name(repo_url_or_path)
    else:
        path = Path(repo_url_or_path).resolve()
        name = repo_name or path.name

    print(f"[ingest] Chunking {path} ...")
    chunks = chunk_repo(str(path))
    print(f"[ingest] Extracted {len(chunks)} chunks.")

    if not chunks:
        print("[ingest] No chunks found; nothing stored.")
        return 0

    # Drop any stale points for this repo before storing fresh ones.
    delete_repo_points(name, collection)
    n = store_chunks(chunks, repo_name=name, collection=collection)
    print(f"[ingest] Stored {n} chunks for repo '{name}' into '{collection}'.")

    # Also store the whole-repo map (structure + key files) as a single
    # REPO_MAP point. Done after store_chunks so delete_repo_points above
    # doesn't clear it, and so it can be fetched directly by
    # get_repo_map_chunk() without competing in similarity ranking.
    store_repo_map(str(path), repo_name=name, collection=collection)
    print(f"[ingest] Stored REPO_MAP for repo '{name}'.")

    return n


def search(query: str, repo_name: str, top_k: int = 5, collection: str = "codebase_chunks"):
    query_vec = get_model().encode(query).tolist()
    response = client.query_points(
        collection_name=collection,
        query=query_vec,  # qdrant-client >= 1.10: vector goes in `query`, NOT `query_vector`
        query_filter=Filter(
            must=[FieldCondition(key="repo", match=MatchValue(value=repo_name))],
            # The REPO_MAP sentinel is fetched directly by get_repo_map_chunk();
            # keep it out of similarity results so it's never duplicated in context.
            must_not=[FieldCondition(key="file_path", match=MatchValue(value="REPO_MAP"))],
        ),
        limit=top_k,
    )
    return [
        {
            "score": r.score,
            "file_path": r.payload["file_path"],
            "function_name": r.payload["function_name"],
            "start_line": r.payload["start_line"],
            "end_line": r.payload["end_line"],
            "content": r.payload["content"],
        }
        for r in response.points  # query_points returns a QueryResponse, not a list
    ]

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Ingest a repo (GitHub URL or local path) into Qdrant."
    )
    parser.add_argument("repo", help="GitHub URL (e.g. https://github.com/user/repo) or local repo path.")
    parser.add_argument("--collection", default="codebase_chunks", help="Qdrant collection name.")
    parser.add_argument("--name", default=None, help="Override repo name stored in point payloads.")
    parser.add_argument("--force", action="store_true", help="Force a fresh re-clone for URLs.")
    args = parser.parse_args()

    ingest_repo(args.repo, collection=args.collection, force=args.force, repo_name=args.name)
    