
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.persistence import job_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Use a separate temporary database for every test."""
    db_path = tmp_path / "test_jobs.sqlite3"

    monkeypatch.setattr(
        job_store,
        "get_db_path",
        lambda: db_path,
    )

    job_store.init_db()
    return job_store


def test_create_job(store):
    store.create_job("job-001", "microsoft/typescript")

    job = store.get_job("job-001")

    assert job is not None
    assert job["job_id"] == "job-001"
    assert job["repo_name"] == "microsoft/typescript"
    assert job["status"] == "queued"
    assert job["stage"] == "Queued"
    assert job["chunks_stored"] is None
    assert job["created_at"] is not None


def test_update_job_status_and_timestamps(store):
    store.create_job("job-002", "facebook/react")

    store.update_job(
        "job-002",
        status="running",
        stage="Generating embeddings",
    )

    running_job = store.get_job("job-002")

    assert running_job["status"] == "running"
    assert running_job["stage"] == "Generating embeddings"
    assert running_job["started_at"] is not None
    assert running_job["heartbeat_at"] is not None

    store.update_job(
        "job-002",
        status="done",
        stage="Indexed 120 chunks",
        chunks_stored=120,
    )

    completed_job = store.get_job("job-002")

    assert completed_job["status"] == "done"
    assert completed_job["chunks_stored"] == 120
    assert completed_job["completed_at"] is not None
    assert completed_job["started_at"] is not None


def test_update_job_error(store):
    store.create_job("job-003", "owner/repo")

    store.update_job(
        "job-003",
        status="error",
        stage="Failed",
        error="Simulated ingestion failure",
    )

    job = store.get_job("job-003")

    assert job["status"] == "error"
    assert job["error"] == "Simulated ingestion failure"
    assert job["completed_at"] is not None


def test_unknown_job(store):
    assert store.get_job("unknown-job") is None

    assert store.update_job(
        "unknown-job",
        status="running",
    ) is False


def test_reject_unsupported_update_fields(store):
    store.create_job("job-004", "owner/repo")

    with pytest.raises(ValueError):
        store.update_job(
            "job-004",
            invalid_column="unexpected",
        )


def test_concurrent_job_updates(store):
    store.create_job("job-005", "owner/repo")

    def update_stage(index):
        return store.update_job(
            "job-005",
            stage=f"Stage {index}",
            status="running",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(update_stage, range(30)))

    assert all(results)

    job = store.get_job("job-005")

    assert job["status"] == "running"
    assert job["stage"].startswith("Stage ")
    assert job["heartbeat_at"] is not None


def test_mark_interrupted_jobs(store):
    store.create_job("job-queued", "owner/repo-a")
    store.create_job("job-running", "owner/repo-b")
    store.create_job("job-completed", "owner/repo-c")

    store.update_job(
        "job-running",
        status="running",
        stage="Embedding",
    )

    store.update_job(
        "job-completed",
        status="done",
        stage="Completed",
        chunks_stored=50,
    )

    interrupted = store.mark_interrupted_jobs()

    assert interrupted == 2

    queued = store.get_job("job-queued")
    running = store.get_job("job-running")
    completed = store.get_job("job-completed")

    assert queued["status"] == "error"
    assert running["status"] == "error"
    assert completed["status"] == "done"

    assert queued["completed_at"] is not None
    assert "restart" in queued["error"].lower()
