
import re
from urllib.parse import urlsplit


OWNER_PATTERN = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def canonical_repo_id(repo_url: str) -> str:
    """Return a normalized GitHub repository ID: owner/repo."""

    parsed = urlsplit(repo_url.strip())

    if parsed.scheme.lower() != "https" or parsed.hostname != "github.com":
        raise ValueError("Only HTTPS GitHub URLs are supported")

    # Reject credentials and non-standard ports.
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("GitHub URL must not contain credentials")

    try:
        if parsed.port not in (None, 443):
            raise ValueError("Only the standard HTTPS port is supported")
    except ValueError as exc:
        raise ValueError("Invalid GitHub URL port") from exc

    # Reject query strings and fragments.
    if parsed.query or parsed.fragment:
        raise ValueError("Query strings and fragments are not allowed")

    # Remove at most one trailing slash.
    path = parsed.path
    if path.endswith("/"):
        path = path[:-1]

    parts = path.split("/")

    # Require exactly /owner/repository.
    # Empty path segments are not silently ignored.
    if len(parts) != 3 or parts[0] != "":
        raise ValueError("Expected https://github.com/owner/repository")

    owner, repo = parts[1], parts[2]

    repo = repo.removesuffix(".git")
    if repo in {".", ".."}:
        raise ValueError("Invalid repository name")

    if not OWNER_PATTERN.fullmatch(owner):
        raise ValueError("Invalid GitHub owner name")

    if not REPO_PATTERN.fullmatch(repo):
        raise ValueError("Invalid GitHub repository name")

    return f"{owner.lower()}/{repo.lower()}"


def get_repo_name(repo_url: str) -> str:
    return canonical_repo_id(repo_url)
