
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import routes
from app.config import settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test-secret-key")
    monkeypatch.setattr(routes, "list_ingested_repos", lambda: [])
    monkeypatch.setattr(routes, "warmup", lambda: 0.0)

    return TestClient(routes.app)


def test_missing_api_key(client):
    response = client.get("/repos")

    assert response.status_code == 401


def test_invalid_api_key(client):
    response = client.get(
        "/repos",
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 401


def test_valid_api_key(client):
    response = client.get(
        "/repos",
        headers={"X-API-Key": "test-secret-key"},
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/repo/extra",
    ],
)
def test_reject_invalid_github_url(url):
    with pytest.raises(HTTPException) as exc:
        routes.validate_github_url(url)

    assert exc.value.status_code == 400


def test_accept_valid_github_url():
    routes.validate_github_url(
        "https://github.com/owner/repo"
    )

def test_unconfigured_api_key_fails_closed(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")

    response = client.get("/repos")

    assert response.status_code == 503


def test_ingest_endpoint_rejects_invalid_url(client, monkeypatch):
    def ingestion_must_not_run(*args, **kwargs):
        raise AssertionError("Ingestion must not run for an invalid URL")

    monkeypatch.setattr(routes, "ingest_repo", ingestion_must_not_run)

    response = client.post(
        "/ingest",
        json={
            "repo_url": "http://github.com/owner/repo",
            "force": False,
        },
        headers={"X-API-Key": "test-secret-key"},
    )

    assert response.status_code == 400