import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4
from git import Repo
from git.exc import InvalidGitRepositoryError, NoSuchPathError, BadName
from .repo_id import canonical_repo_id

# Clone target lives OUTSIDE the project root on purpose: dev servers that
# watch the project tree for changes (uvicorn --reload, `chainlit -w`) would
# otherwise detect the cloned source files and restart mid-request, killing
# the in-flight /ingest call. Override with the REPOS_DIR env var.
CLONE_BASE_DIR = Path(os.environ.get("REPOS_DIR", Path.home() / ".codebase-rag-agent" / "repos"))


def clone_repo(repo_url: str, force: bool = False) -> Path:
    """
    Clones a GitHub repo URL into ./repos/<repo_name>.

    Reuses an existing clone if nothing has changed on the remote. Downloads
    into a temporary directory first and swaps atomically, so a failed download
    never destroys the working clone.

    Args:
        repo_url (str): The URL of the git repository to clone.
        force (bool): If True, force re-cloning even if the repository already exists.

    Returns:
        Path: The path to the cloned repository.
    """
    repo_name = canonical_repo_id(repo_url)
    target_path = CLONE_BASE_DIR / repo_name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    CLONE_BASE_DIR.mkdir(parents=True, exist_ok=True)

    existing_sha = None
    existing_is_clean = True

    if target_path.exists():
        try:
            existing_repo = Repo(target_path)
            existing_sha = existing_repo.head.commit.hexsha
            existing_is_clean = not existing_repo.is_dirty(untracked_files=True)

        except (InvalidGitRepositoryError, NoSuchPathError, BadName):
            existing_sha = None
            existing_is_clean = True

    if target_path.exists() and not existing_is_clean and not force:
        raise RuntimeError(
            f"Local repository {repo_name} contains uncommitted changes. "
            "Use force=True to replace it explicitly."
        )

    remote_sha = None
    try:
        result = subprocess.run(
            ["git", "ls-remote", repo_url.strip(), "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        if result.stdout.strip():
            remote_sha = result.stdout.strip().split()[0]
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise RuntimeError(
            f"Unable to check remote revision for {repo_name}"
        ) from exc

    # 3. Reuse the clone if nothing has changed.
    if (
        target_path.exists()
        and existing_sha == remote_sha
        and existing_is_clean
        and not force
    ):
        print(f"[clone] Repository is up to date: {repo_name}")
        return target_path

    # 4. Download into a temporary directory.
    backup_path = None
    with tempfile.TemporaryDirectory(
        prefix=".codesage-clone-",
        dir=target_path.parent,
    ) as temp_dir:
        candidate_path = Path(temp_dir) / "repository"
        print(f"[clone] Downloading latest revision of {repo_name}")
        new_repo = Repo.clone_from(
            repo_url.strip(),
            candidate_path,
            depth=1,
        )
        try:
            new_sha = new_repo.head.commit.hexsha
        finally:
            if hasattr(new_repo, "close"):
                new_repo.close()
        if new_sha != remote_sha:
            raise RuntimeError(
                f"Remote repository changed during cloning. "
                f"Expected {remote_sha}, received {new_sha}. Please retry."
            )

        print(f"[clone] Latest revision: {new_sha}")
        # 5. Move the existing clone aside.
        if target_path.exists():
            backup_path = target_path.parent / (
                f".{target_path.name}.backup-{uuid4().hex}"
            )
            os.replace(target_path, backup_path)
        try:
            # 6. Install the successfully downloaded clone.
            os.replace(candidate_path, target_path)
        except Exception:
            # Restore the previous clone if replacement fails.
            if backup_path and backup_path.exists():
                os.replace(backup_path, target_path)
            raise
        # 7. Remove the previous clone after successful replacement.
        if backup_path and backup_path.exists():
            shutil.rmtree(backup_path, ignore_errors=True)
    return target_path


def get_repo_revision(repo_path: str | Path) -> str | None:
    """Return the Git commit SHA, or None for a non-Git directory."""
    try:
        return Repo(Path(repo_path)).head.commit.hexsha
    except (
        InvalidGitRepositoryError,
        NoSuchPathError,
        BadName,
        ValueError,
    ):
        return None

def get_repo_name(repo_url: str) -> str:
    return canonical_repo_id(repo_url)

def clean_repo(repo_url: str, force: bool = False) -> Path:
    """
    Alias kept for embed_store.ingest_repo: removes the existing clone if
    present and re-clones, exactly matching clone_repo(force=...).
    """
    return clone_repo(repo_url, force=force)
