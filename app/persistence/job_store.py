
import os
import sqlite3
import time

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def get_db_path() -> Path:
    """Resolve the SQLite database path from JOB_DB_PATH."""
    configured_path = os.getenv("JOB_DB_PATH")

    if configured_path:
        return Path(configured_path).expanduser().resolve()

    project_root = Path(__file__).resolve().parents[2]
    return project_root / "data" / "codesage_jobs.sqlite3"


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """Create a SQLite connection with safe cleanup and rollback."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(db_path),
        timeout=10,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Create the persistent ingestion-jobs table."""
    with _connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")

        connection.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_jobs (
                job_id TEXT PRIMARY KEY,
                repo_name TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK(status IN ('queued', 'running', 'done', 'error')),
                stage TEXT NOT NULL,
                chunks_stored INTEGER,
                error TEXT,
                created_at REAL NOT NULL,
                started_at REAL,
                heartbeat_at REAL,
                completed_at REAL,
                updated_at REAL NOT NULL
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_repo
            ON ingestion_jobs(repo_name)
        """)


def create_job(job_id: str, repo_name: str) -> None:
    """Persist a newly queued ingestion job."""
    now = time.time()

    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO ingestion_jobs (
                job_id,
                repo_name,
                status,
                stage,
                chunks_stored,
                error,
                created_at,
                started_at,
                heartbeat_at,
                completed_at,
                updated_at
            )
            VALUES (?, ?, 'queued', 'Queued', NULL, NULL, ?, NULL, ?, NULL, ?)
            """,
            (job_id, repo_name, now, now, now),
        )


def update_job(job_id: str, **fields: Any) -> bool:
    """Update allowed job fields and refresh its heartbeat."""
    allowed_fields = {
        "status",
        "stage",
        "chunks_stored",
        "error",
    }

    invalid_fields = set(fields) - allowed_fields

    if invalid_fields:
        raise ValueError(
            f"Unsupported job fields: {sorted(invalid_fields)}"
        )

    if not fields:
        return False

    now = time.time()

    assignments = []
    values = []

    for key, value in fields.items():
        assignments.append(f"{key} = ?")
        values.append(value)

    assignments.append("updated_at = ?")
    values.append(now)

    assignments.append("heartbeat_at = ?")
    values.append(now)

    if fields.get("status") == "running":
        assignments.append("started_at = COALESCE(started_at, ?)")
        values.append(now)

    if fields.get("status") in {"done", "error"}:
        assignments.append("completed_at = ?")
        values.append(now)

    values.append(job_id)

    with _connection() as connection:
        cursor = connection.execute(
            f"""
            UPDATE ingestion_jobs
            SET {", ".join(assignments)}
            WHERE job_id = ?
            """,
            values,
        )

        return cursor.rowcount > 0


def get_job(job_id: str) -> dict | None:
    """Retrieve a persistent ingestion-job record."""
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM ingestion_jobs
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()

    return dict(row) if row else None


def mark_interrupted_jobs() -> int:
    """
    Mark queued or running jobs as interrupted after a backend restart.

    These jobs are not automatically resumed.
    """
    now = time.time()

    with _connection() as connection:
        cursor = connection.execute(
            """
            UPDATE ingestion_jobs
            SET
                status = 'error',
                stage = 'Interrupted by backend restart',
                error = 'Backend restarted before ingestion completed',
                completed_at = ?,
                heartbeat_at = ?,
                updated_at = ?
            WHERE status IN ('queued', 'running')
            """,
            (now, now, now),
        )

        return cursor.rowcount
