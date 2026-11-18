
import threading
from concurrent.futures import ThreadPoolExecutor

from app.ingestion import embed_store


REPO_A = "https://github.com/owner/repo-a"
REPO_B = "https://github.com/owner/repo-b"
COMMIT = "a" * 40

CHUNK = {
    "content": "def example(): pass",
    "file_path": "main.py",
    "function_name": "example",
    "start_line": 1,
    "end_line": 1,
    "parent_symbol": None,
}


def setup_fake_pipeline(monkeypatch, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    monkeypatch.setattr(embed_store, "ensure_collection", lambda *a, **k: None)
    monkeypatch.setattr(embed_store, "clean_repo", lambda *a, **k: repo_path)
    monkeypatch.setattr(embed_store, "get_repo_revision", lambda *a: COMMIT)
    monkeypatch.setattr(embed_store, "get_token_counter", lambda: lambda text: 1)
    monkeypatch.setattr(embed_store, "chunk_repo", lambda *a, **k: [CHUNK.copy()])
    monkeypatch.setattr(embed_store, "delete_repo_points", lambda *a, **k: None)
    monkeypatch.setattr(embed_store, "store_chunks", lambda *a, **k: 1)
    monkeypatch.setattr(embed_store, "store_repo_map", lambda *a, **k: None)


def test_skip_when_same_commit_is_already_indexed(monkeypatch, tmp_path):
    setup_fake_pipeline(monkeypatch, tmp_path)

    monkeypatch.setattr(
        embed_store,
        "get_repo_map_chunk",
        lambda *a, **k: {"commit_sha": COMMIT},
    )

    def chunking_must_not_run(*args, **kwargs):
        raise AssertionError("Chunking should be skipped")

    monkeypatch.setattr(embed_store, "chunk_repo", chunking_must_not_run)

    result = embed_store.ingest_repo(REPO_A)

    assert result == 0


def test_reindex_when_commit_changes(monkeypatch, tmp_path):
    setup_fake_pipeline(monkeypatch, tmp_path)

    monkeypatch.setattr(
        embed_store,
        "get_repo_map_chunk",
        lambda *a, **k: {"commit_sha": "old-commit"},
    )

    saved_shas = []

    def fake_store_chunks(chunks, **kwargs):
        saved_shas.append(kwargs["commit_sha"])
        return 1

    def fake_store_repo_map(*args, **kwargs):
        saved_shas.append(kwargs["commit_sha"])

    monkeypatch.setattr(embed_store, "store_chunks", fake_store_chunks)
    monkeypatch.setattr(embed_store, "store_repo_map", fake_store_repo_map)

    result = embed_store.ingest_repo(REPO_A)

    assert result == 1
    assert saved_shas == [COMMIT, COMMIT]


def test_same_repository_ingestion_is_serialized(monkeypatch, tmp_path):
    setup_fake_pipeline(monkeypatch, tmp_path)

    monkeypatch.setattr(
        embed_store,
        "get_repo_map_chunk",
        lambda *a, **k: None,
    )

    first_entered = threading.Event()
    second_entered = threading.Event()
    second_attempting = threading.Event()
    release_first = threading.Event()

    state_lock = threading.Lock()
    active = 0
    maximum_active = 0
    calls = 0

    def controlled_chunker(*args, **kwargs):
        nonlocal active, maximum_active, calls

        with state_lock:
            calls += 1
            call_number = calls
            active += 1
            maximum_active = max(maximum_active, active)

        if call_number == 1:
            first_entered.set()
            assert release_first.wait(timeout=5)
        else:
            second_entered.set()

        with state_lock:
            active -= 1

        return [CHUNK.copy()]

    monkeypatch.setattr(embed_store, "chunk_repo", controlled_chunker)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(embed_store.ingest_repo, REPO_A)

        assert first_entered.wait(timeout=5)

        def second_request():
            second_attempting.set()
            return embed_store.ingest_repo(REPO_A)

        second = executor.submit(second_request)

        assert second_attempting.wait(timeout=5)

        # Second request must wait while the first is processing.
        assert not second_entered.wait(timeout=0.3)

        release_first.set()

        assert first.result(timeout=5) == 1
        assert second.result(timeout=5) == 1

    assert maximum_active == 1


def test_different_repositories_can_ingest_concurrently(
    monkeypatch, tmp_path
):
    setup_fake_pipeline(monkeypatch, tmp_path)

    monkeypatch.setattr(
        embed_store,
        "get_repo_map_chunk",
        lambda *a, **k: None,
    )

    both_entered = threading.Barrier(2)

    def parallel_chunker(*args, **kwargs):
        both_entered.wait(timeout=5)
        return [CHUNK.copy()]

    monkeypatch.setattr(embed_store, "chunk_repo", parallel_chunker)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(embed_store.ingest_repo, REPO_A)
        second = executor.submit(embed_store.ingest_repo, REPO_B)

        assert first.result(timeout=10) == 1
        assert second.result(timeout=10) == 1
