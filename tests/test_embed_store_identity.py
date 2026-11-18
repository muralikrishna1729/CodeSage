import pytest
from app.ingestion import embed_store


def test_rejects_noncanonical_repo_name_before_cloning(monkeypatch):
    def clone_should_not_run(*args, **kwargs):
        pytest.fail("Clone should not run when repository identity mismatches")

    monkeypatch.setattr(
        embed_store,
        "clean_repo",
        clone_should_not_run,
    )
    monkeypatch.setattr(embed_store, "ensure_collection", lambda *a, **k: None)

    with pytest.raises(ValueError, match="Repository name mismatch"):
        embed_store.ingest_repo(
            "https://github.com/Microsoft/TypeScript.git",
            repo_name="another/repository",
        )
