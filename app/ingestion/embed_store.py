import os
import uuid
from pathlib import Path
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    SparseVectorParams,
    SparseVector,
    PointStruct,
    Prefetch,
    FusionQuery,
    Fusion,
    Filter,
    FieldCondition,
    MatchValue,
)
from qdrant_client import models as qdrant_models
from app.ingestion.repo_map import build_repo_map
from app.config import settings
from fastembed import SparseTextEmbedding

try:
    from .chunker import chunk_repo
    from .clone import clean_repo, get_repo_name
except ImportError:
    # Support running directly: python app/ingestion/embed_store.py
    from chunker import chunk_repo
    from clone import clean_repo, get_repo_name

import transformers.pytorch_utils
if not hasattr(transformers.pytorch_utils, "find_pruneable_heads_and_indices"):
    import torch
    def _find_pruneable_heads_and_indices(heads, n_heads, head_size, already_pruned_heads):
        mask = torch.ones(n_heads, head_size)
        heads = set(heads) - already_pruned_heads
        for head in heads:
            head = head - sum(1 if h < head else 0 for h in already_pruned_heads)
            mask[head] = 0
        mask = mask.view(-1).contiguous().eq(1)
        index = torch.arange(len(mask))[mask].long()
        return heads, index
    transformers.pytorch_utils.find_pruneable_heads_and_indices = _find_pruneable_heads_and_indices

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".model_cache")

_model = None
def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(
            settings.embed_model,
            device="cpu",
            trust_remote_code=True,
            cache_folder=CACHE_DIR,
        )
        _model.max_seq_length = 512  # default 8192 is very slow on CPU
    return _model


_sparse_model = None
def get_sparse_model():
    global _sparse_model
    if _sparse_model is None:
        _sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25", cache_dir=CACHE_DIR)
    return _sparse_model


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


def _stage(progress, message: str) -> None:
    """Announce a pipeline milestone on stdout and to an optional callback.

    `/ingest/async` passes a callback here so the UI can show which stage a
    long ingestion (clone -> AST chunk -> CPU embed -> upsert) is currently in.
    A broken callback must never abort an ingestion, so its errors are logged
    and swallowed.
    """
    print(f"[ingest] {message}")
    if progress is not None:
        try:
            progress(message)
        except Exception as e:
            print(f"[ingest] progress callback failed (ignored): {e}")

def recreate_collection(name: str = "codebase_chunks"):
    """Creates collection with both Dense (768-dim) and Sparse (BM25) vector support."""
    client.recreate_collection(
        collection_name=name,
        vectors_config={
            "dense": VectorParams(size=768, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(),
        },
    )

def ensure_collection(name: str):
    if not client.collection_exists(name):
        recreate_collection(name)
    else:
        try:
            info = client.get_collection(name)
            vectors_config = info.config.params.vectors
            if isinstance(vectors_config, dict):
                dense_cfg = vectors_config.get("dense")
                size = getattr(dense_cfg, "size", None)
            else:
                size = getattr(vectors_config, "size", None)
            if size is not None and size != 768:
                print(f"[ingest] Collection '{name}' dimension is {size} != 768. Recreating with 768 dims...")
                recreate_collection(name)
        except Exception as e:
            print(f"[ingest] Warning checking collection config: {e}")

def store_chunks(chunks, repo_name: str, collection: str = "codebase_chunks", progress=None) -> int:
    ensure_collection(collection)
    texts = [c.content if hasattr(c, "content") else c["content"] for c in chunks]

    # 1. Generating dense embeddings
    dense_model = get_model()
    _stage(progress, f"Generating dense embeddings for {len(texts)} chunks...")
    dense_embeddings = dense_model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()

    # 2. Generating Sparse BM25 embeddings
    _stage(progress, f"Generating sparse BM25 vectors for {len(texts)} chunks...")
    sparse_model = get_sparse_model()
    sparse_embeddings = list(sparse_model.embed(texts))

    points = []
    for i, chunk in enumerate(chunks):
        s_vec = sparse_embeddings[i]
        file_path = chunk.file_path if hasattr(chunk, "file_path") else chunk["file_path"]
        func_name = chunk.function_name if hasattr(chunk, "function_name") else chunk["function_name"]
        start_line = chunk.start_line if hasattr(chunk, "start_line") else chunk["start_line"]
        end_line = chunk.end_line if hasattr(chunk, "end_line") else chunk["end_line"]
        content = chunk.content if hasattr(chunk, "content") else chunk["content"]

        point = PointStruct(
            id=str(uuid.uuid4()),
            vector={
                "dense": dense_embeddings[i],
                "sparse": SparseVector(
                    indices=s_vec.indices.tolist(),
                    values=s_vec.values.tolist(),
                ),
            },
            payload={
                "repo": repo_name,
                "file_path": file_path,
                "function_name": func_name,
                "start_line": start_line,
                "end_line": end_line,
                "content": content,
            },
        )
        points.append(point)

    # Upsert in batches of 64
    batch_size = 64
    for idx in range(0, len(points), batch_size):
        client.upsert(collection_name=collection, points=points[idx:idx + batch_size])
    
    _stage(progress, f"Upserted {len(points)} points into '{collection}'.")
    return len(points)

def store_repo_map(repo_path: str, repo_name: str, collection: str = "codebase_chunks", progress=None):
    _stage(progress, "Building REPO_MAP (directory tree + key files) ...")
    repo_map = build_repo_map(repo_path)
    summary_text = "DIRECTORY STRUCTURE:\n" + repo_map["directory_tree"] + "\n\n"
    for fname, content in repo_map["key_files"].items():
        summary_text += f"--- {fname} ---\n{content}\n\n"
    vector = get_model().encode(summary_text, normalize_embeddings=True).tolist()
    point = PointStruct(
        id=str(uuid.uuid4()),
        vector={"dense": vector},
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
    _stage(progress, "Stored REPO_MAP.")

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
    progress=None,
) -> int:
    """
    Ingest a repo into Qdrant.

    Args:
        repo_url_or_path: A GitHub URL (cloned via clone.clean_repo) or a local repo path.
        collection: Qdrant collection to write into.
        force: If True, force a fresh re-clone when a URL is given.
        repo_name: Optional override for the repo name stored in each point's payload.
        progress: Optional callable(str) invoked at each pipeline milestone, so a
            caller (e.g. /ingest/async) can report live progress to a UI.

    Returns:
        Number of chunks stored.
    """
    _stage(progress, f"Preparing collection '{collection}' ...")
    ensure_collection(collection)

    if "://" in repo_url_or_path or repo_url_or_path.startswith("git@"):
        _stage(progress, f"Cloning {repo_url_or_path} ...")
        path = clean_repo(repo_url_or_path, force=force)
        name = repo_name or get_repo_name(repo_url_or_path)
    else:
        path = Path(repo_url_or_path).resolve()
        name = repo_name or path.name

    _stage(progress, f"Chunking {path} ...")
    chunks = chunk_repo(str(path))
    _stage(progress, f"Extracted {len(chunks)} chunks.")

    if not chunks:
        _stage(progress, "No chunks found; nothing stored.")
        return 0

    # Drop any stale points for this repo before storing fresh ones.
    _stage(progress, f"Removing stale points for '{name}' ...")
    delete_repo_points(name, collection)
    n = store_chunks(chunks, repo_name=name, collection=collection, progress=progress)
    _stage(progress, f"Stored {n} chunks for repo '{name}' into '{collection}'.")

    # Also store the whole-repo map (structure + key files) as a single
    # REPO_MAP point. Done after store_chunks so delete_repo_points above
    # doesn't clear it, and so it can be fetched directly by
    # get_repo_map_chunk() without competing in similarity ranking.
    store_repo_map(str(path), repo_name=name, collection=collection, progress=progress)

    return n


def search(query: str, repo_name: str, top_k: int = 5, collection: str = "codebase_chunks"):
     # 1. Encode query for both models
    dense_vec = get_model().encode(query, normalize_embeddings = True).tolist()
    sparse_obj = list(get_sparse_model().embed([query]))[0]
    sparse_vec = SparseVector(
        indices= sparse_obj.indices.tolist(),
        values= sparse_obj.values.tolist(),
    )
    # Shared filter to keep repos isolated
    repo_filter = Filter(
        must = [FieldCondition(key="repo", match = MatchValue(value = repo_name))],
        must_not = [FieldCondition(key = "file_path", match = MatchValue(value= "REPO_MAP"))]
    )
    response = client.query_points(
        collection_name=collection,
        prefetch=[
            Prefetch(
                query = dense_vec,
                using = "dense",
                filter = repo_filter,
                limit = top_k*2,
            ),
            Prefetch(
                query = sparse_vec,
                using = "sparse",
                filter = repo_filter,
                limit = top_k*2
            ),
        ],
        query = FusionQuery(fusion=Fusion.RRF),
        limit = top_k
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


def list_ingested_repos(collection: str = "codebase_chunks") -> list[dict]:
    """Distinct repos currently indexed in `collection`, with point counts.

    The frontends use this to offer already-indexed repos, so a UI session that
    never learned the repo name (page reload, or an ingest whose HTTP request the
    client abandoned) can still be pointed at indexed code.

    Scrolls page by page instead of using Qdrant facets, because a payload index
    on "repo" isn't guaranteed to exist on an already-created collection.
    """
    ensure_collection(collection)
    counts: dict[str, int] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=1000,
            offset=offset,
            with_payload=["repo"],
            with_vectors=False,
        )
        for p in points:
            repo = (p.payload or {}).get("repo")
            if repo:
                counts[repo] = counts.get(repo, 0) + 1
        if offset is None:  # last page reached
            break
    return [{"repo_name": r, "points": n} for r, n in sorted(counts.items())]


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
    