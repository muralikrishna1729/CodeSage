from pathlib import Path

from app.ingestion import clone


class _FakeRepo:
    class _Head:
        class _Commit:
            hexsha = "abc123"

        commit = _Commit()

    head = _Head()


def test_clone_repo_uses_canonical_owner_repo_path(tmp_path, monkeypatch):
    base_dir = tmp_path / "repos"
    monkeypatch.setattr(clone, "CLONE_BASE_DIR", base_dir)

    def fake_clone_from(url, target, **kwargs):
        target = Path(target)

        assert url == "https://github.com/Microsoft/TypeScript.git"
        assert target.parent.parent == base_dir / "microsoft"
        assert target.parent.exists()

        target.mkdir(parents=True, exist_ok=True)
        return _FakeRepo()

    monkeypatch.setattr(clone.Repo, "clone_from", fake_clone_from)

    result = clone.clone_repo(
        "https://github.com/Microsoft/TypeScript.git"
    )

    assert result == base_dir / "microsoft" / "typescript"
    assert result.exists()
