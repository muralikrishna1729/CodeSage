from types import SimpleNamespace
from app.ingestion import embed_store

COMMIT_SHA = "a" * 40


def setup_models(monkeypatch):
    class FakeDenseResult:
        def __init__(self, data):
            self.data = data

        def tolist(self):
            return self.data

    class FakeDenseModel:
        def encode(self, texts, **kwargs):
            if isinstance(texts, str):
                return FakeDenseResult([0.1] * 768)
            return FakeDenseResult([[0.1] * 768 for _ in texts])

    class FakeSparseVec:
        indices = SimpleNamespace(tolist=lambda: [1, 2])
        values = SimpleNamespace(tolist=lambda: [0.5, 0.5])

    class FakeSparseModel:
        def embed(self, texts, **kwargs):
            return [FakeSparseVec() for _ in texts]

    monkeypatch.setattr(embed_store, "get_model", lambda: FakeDenseModel())
    monkeypatch.setattr(embed_store, "get_sparse_model", lambda: FakeSparseModel())
    monkeypatch.setattr(embed_store, "ensure_collection", lambda *a, **k: None)


def test_store_chunks_saves_commit_sha(monkeypatch):
    setup_models(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        embed_store.client,
        "upsert",
        lambda **kwargs: captured.update(kwargs),
    )
    chunk = {
        "file_path": "main.py",
        "function_name": "hello",
        "start_line": 1,
        "end_line": 2,
        "content": "def hello(): pass",
        "parent_symbol": None,
    }
    embed_store.store_chunks(
        [chunk],
        repo_name="owner/repo",
        commit_sha=COMMIT_SHA,
    )
    payload = captured["points"][0].payload
    assert payload["commit_sha"] == COMMIT_SHA
    assert payload["repo"] == "owner/repo"


def test_store_repo_map_saves_commit_sha(monkeypatch):
    setup_models(monkeypatch)
    monkeypatch.setattr(
        embed_store,
        "build_repo_map",
        lambda path: {
            "directory_tree": "src/",
            "key_files": {"main.py": "print('hello')"},
        },
    )
    captured = {}
    monkeypatch.setattr(
        embed_store.client,
        "upsert",
        lambda **kwargs: captured.update(kwargs),
    )
    embed_store.store_repo_map(
        repo_path="fake/path",
        repo_name="owner/repo",
        commit_sha=COMMIT_SHA,
    )
    payload = captured["points"][0].payload
    assert payload["commit_sha"] == COMMIT_SHA
    assert payload["file_path"] == "REPO_MAP"


def test_search_returns_commit_sha(monkeypatch):
    setup_models(monkeypatch)
    payload = {
        "repo": "owner/repo",
        "file_path": "main.py",
        "function_name": "hello",
        "start_line": 1,
        "end_line": 2,
        "content": "def hello(): pass",
        "parent_symbol": None,
        "commit_sha": COMMIT_SHA,
    }
    monkeypatch.setattr(
        embed_store.client,
        "query_points",
        lambda **kwargs: SimpleNamespace(
            points=[
                SimpleNamespace(score=0.95, payload=payload)
            ]
        ),
    )
    results = embed_store.search(
        query="hello",
        repo_name="owner/repo",
    )
    assert len(results) == 1
    assert results[0]["commit_sha"] == COMMIT_SHA


def test_get_repo_map_chunk_returns_commit_sha(monkeypatch):
    payload = {
        "repo": "owner/repo",
        "file_path": "REPO_MAP",
        "content": "DIRECTORY STRUCTURE:\nsrc/",
        "commit_sha": COMMIT_SHA,
    }
    monkeypatch.setattr(
        embed_store.client,
        "scroll",
        lambda **kwargs: ([SimpleNamespace(payload=payload)], None),
    )
    result = embed_store.get_repo_map_chunk(repo_name="owner/repo")
    assert result is not None
    assert result["commit_sha"] == COMMIT_SHA
    assert result["file_path"] == "REPO_MAP"
