import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from git import Repo

from app.ingestion import clone

GITHUB_URL = "https://github.com/owner/repo.git"


def create_repo(path: Path, content: str) -> Repo:
    """Initialize a local git repo with a single committed ``main.py``."""
    path.mkdir(parents=True, exist_ok=True)
    repo = Repo.init(path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "CodeSage Tests")
        config.set_value("user", "email", "tests@example.com")
    source_file = path / "main.py"
    source_file.write_text(content, encoding="utf-8")
    repo.index.add(["main.py"])
    repo.index.commit("Test commit")
    repo.close()
    return repo


def mock_remote_sha(monkeypatch, sha):
    """Mock ``git ls-remote`` so it reports ``sha`` as the remote HEAD.

    Other ``subprocess.run`` calls (e.g. ``git status`` used to detect a
    dirty tree) pass through to the real implementation. ``clone.subprocess``
    is the same ``subprocess`` module the tests import, so we must not blanket
    replace ``run``.
    """
    real_run = subprocess.run

    def fake_run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args")
        if (
            isinstance(cmd, list)
            and len(cmd) >= 2
            and cmd[0] == "git"
            and cmd[1] == "ls-remote"
        ):
            return SimpleNamespace(stdout=f"{sha}\tHEAD\n")
        return real_run(*args, **kwargs)

    monkeypatch.setattr(clone.subprocess, "run", fake_run)


class _LiteCommit:
    """HEAD commit SHA read via a short-lived ``git`` subprocess (no open handle)."""

    def __init__(self, path: Path):
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.hexsha = result.stdout.strip()


class _LiteHead:
    """HEAD ref read via a short-lived ``git`` subprocess."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @property
    def commit(self):
        return _LiteCommit(self.path)


class _LiteRepo:
    """Handle-free read view of a git repo.

    GitPython keeps file handles open that would block ``os.replace`` on
    Windows, so HEAD/dirty status is read through short-lived ``git``
    subprocesses instead. Used only to stand in for :class:`git.Repo` while
    testing :func:`clone.clone_repo`.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    @property
    def head(self):
        return _LiteHead(self.path)

    def is_dirty(self, **kwargs):
        result = subprocess.run(
            ["git", "-C", str(self.path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(result.stdout.strip())


def _local_clone_from(source_path: Path):
    """Fake ``Repo.clone_from`` that copies the local repo into place."""
    calls = []

    def fake_clone_from(url, target, **kwargs):
        calls.append(1)
        target = Path(target)
        shutil.copytree(str(source_path), str(target))
        sha = _LiteRepo(source_path).head.commit.hexsha
        return SimpleNamespace(
            head=SimpleNamespace(commit=SimpleNamespace(hexsha=sha))
        )

    return fake_clone_from, calls


def _setup_clone_monkeypatches(monkeypatch, source_path: Path):
    """Monkeypatch clone for local-repo testing; return the clone call log."""
    fake_clone_from, calls = _local_clone_from(source_path)
    monkeypatch.setattr(clone, "Repo", _LiteRepo)
    monkeypatch.setattr(
        clone.Repo, "clone_from", fake_clone_from, raising=False
    )
    return calls


def test_fresh_clone_checks_out_remote_content(tmp_path, monkeypatch):
    clone.CLONE_BASE_DIR = tmp_path / "repos"

    source_path = tmp_path / "source"
    repo = create_repo(source_path, "v1 content")
    sha_v1 = repo.head.commit.hexsha

    calls = _setup_clone_monkeypatches(monkeypatch, source_path)
    mock_remote_sha(monkeypatch, sha_v1)

    result = clone.clone_repo(GITHUB_URL)

    assert calls == [1]
    assert result == tmp_path / "repos" / "owner" / "repo"
    assert result.exists()
    assert (result / "main.py").read_text(encoding="utf-8") == "v1 content"
    assert _LiteRepo(result).head.commit.hexsha == sha_v1
def test_reuse_existing_clone_when_remote_unchanged(tmp_path, monkeypatch):
    clone.CLONE_BASE_DIR = tmp_path / "repos"

    source_path = tmp_path / "source"
    repo = create_repo(source_path, "v1 content")
    sha_v1 = repo.head.commit.hexsha

    calls = _setup_clone_monkeypatches(monkeypatch, source_path)
    mock_remote_sha(monkeypatch, sha_v1)

    # First call performs a fresh clone.
    result_first = clone.clone_repo(GITHUB_URL)
    assert calls == [1]
    assert (result_first / "main.py").read_text(encoding="utf-8") == "v1 content"

    # Second call: remote SHA matches and the clone is clean, so it must be
    # reused without re-cloning.
    result_second = clone.clone_repo(GITHUB_URL)
    assert calls == [1]
    assert result_first == result_second
    assert (result_second / "main.py").read_text(encoding="utf-8") == "v1 content"


def test_refresh_clone_when_remote_changes(tmp_path, monkeypatch):
    clone.CLONE_BASE_DIR = tmp_path / "repos"

    source_path = tmp_path / "source"
    repo = create_repo(source_path, "v1 content")
    sha_v1 = repo.head.commit.hexsha

    calls = _setup_clone_monkeypatches(monkeypatch, source_path)
    mock_remote_sha(monkeypatch, sha_v1)

    # Initial clone at v1.
    result_first = clone.clone_repo(GITHUB_URL)
    assert calls == [1]
    assert (result_first / "main.py").read_text(encoding="utf-8") == "v1 content"

    # Advance the remote (source) repository to v2.
    source_file = source_path / "main.py"
    source_file.write_text("v2 content", encoding="utf-8")
    repo.index.add(["main.py"])
    sha_v2 = repo.index.commit("v2").hexsha

    mock_remote_sha(monkeypatch, sha_v2)
    result_second = clone.clone_repo(GITHUB_URL)

    # The same target path must now point at the refreshed v2 content.
    assert calls == [1, 1]
    assert result_first == result_second
    assert (result_second / "main.py").read_text(encoding="utf-8") == "v2 content"
    assert _LiteRepo(result_second).head.commit.hexsha == sha_v2

def test_force_reclone_ignores_unchanged_remote(tmp_path, monkeypatch):
    clone.CLONE_BASE_DIR = tmp_path / "repos"

    source_path = tmp_path / "source"
    repo = create_repo(source_path, "v1 content")
    sha_v1 = repo.head.commit.hexsha

    calls = _setup_clone_monkeypatches(monkeypatch, source_path)
    mock_remote_sha(monkeypatch, sha_v1)

    clone.clone_repo(GITHUB_URL)
    assert calls == [1]

    # force=True re-clones even though the remote SHA did not change.
    clone.clone_repo(GITHUB_URL, force=True)
    assert calls == [1, 1]


def test_dirty_local_clone_blocks_refresh_without_force(tmp_path, monkeypatch):
    clone.CLONE_BASE_DIR = tmp_path / "repos"

    source_path = tmp_path / "source"
    repo = create_repo(source_path, "v1 content")
    sha_v1 = repo.head.commit.hexsha

    calls = _setup_clone_monkeypatches(monkeypatch, source_path)
    mock_remote_sha(monkeypatch, sha_v1)

    clone.clone_repo(GITHUB_URL)
    target = tmp_path / "repos" / "owner" / "repo"

    # Introduce an uncommitted change in the local clone.
    (target / "main.py").write_text("dirty uncommitted change", encoding="utf-8")

    # Remote advances to v2.
    source_file = source_path / "main.py"
    source_file.write_text("v2 content", encoding="utf-8")
    repo.index.add(["main.py"])
    sha_v2 = repo.index.commit("v2").hexsha
    mock_remote_sha(monkeypatch, sha_v2)

    # A dirty clone must not be silently overwritten without force=True.
    with pytest.raises(RuntimeError, match="uncommitted changes"):
        clone.clone_repo(GITHUB_URL)

    # force=True refreshes despite the previously dirty working tree.
    clone.clone_repo(GITHUB_URL, force=True)
    assert (target / "main.py").read_text(encoding="utf-8") == "v2 content"

def test_get_revision_from_git_repository(tmp_path):
    repo_path = tmp_path / "git-repo"
    repo = create_repo(repo_path, "version = 1")

    assert clone.get_repo_revision(repo_path) == repo.head.commit.hexsha


def test_get_revision_from_plain_directory_returns_none(tmp_path):
    plain_dir = tmp_path / "plain-folder"
    plain_dir.mkdir()

    assert clone.get_repo_revision(plain_dir) is None


def test_failed_download_preserves_existing_clone(tmp_path, monkeypatch):
    base = tmp_path / "repos"
    target = base / "owner" / "repo"
    existing_repo = create_repo(target, "version = 1")
    old_sha = existing_repo.head.commit.hexsha
    mock_remote_sha(monkeypatch, "a" * 40)
    monkeypatch.setattr(clone, "CLONE_BASE_DIR", base)

    def failed_clone(*args, **kwargs):
        raise RuntimeError("Simulated download failure")

    monkeypatch.setattr(clone.Repo, "clone_from", failed_clone)
    with pytest.raises(RuntimeError, match="Simulated download failure"):
        clone.clone_repo("https://github.com/owner/repo")
    assert target.exists()
    assert _LiteRepo(target).head.commit.hexsha == old_sha

def test_sha_mismatch_preserves_existing_clone(tmp_path, monkeypatch):
    base = tmp_path / "repos"
    target = base / "owner" / "repo"

    old_repo = create_repo(target, "version = 1")
    old_sha = old_repo.head.commit.hexsha

    remote_repo = create_repo(tmp_path / "remote", "version = 2")

    # GitHub reports a different SHA from the downloaded clone.
    mock_remote_sha(monkeypatch, "a" * 40)
    monkeypatch.setattr(clone, "CLONE_BASE_DIR", base)

    downloaded_sha = remote_repo.head.commit.hexsha
    remote_path = Path(remote_repo.working_tree_dir)
    old_repo.close()
    remote_repo.close()

    def fake_clone(url, destination, **kwargs):
        shutil.copytree(remote_path, destination)
        return SimpleNamespace(
            head=SimpleNamespace(
                commit=SimpleNamespace(hexsha=downloaded_sha)
            ),
            close=lambda: None,
        )

    monkeypatch.setattr(clone.Repo, "clone_from", fake_clone)

    with pytest.raises(RuntimeError, match="changed during cloning"):
        clone.clone_repo("https://github.com/owner/repo")

    # Original clone must remain untouched.
    assert _LiteRepo(target).head.commit.hexsha == old_sha