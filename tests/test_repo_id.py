import pytest

from app.ingestion.repo_id import canonical_repo_id


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/Owner/Repo", "owner/repo"),
        ("https://github.com/Owner/Repo.git", "owner/repo"),
        ("https://github.com/Owner/Repo/", "owner/repo"),
        ("https://github.com/Microsoft/TypeScript.git", "microsoft/typescript"),
        ("https://github.com:443/Owner/Repo","owner/repo"),
    ],
)
def test_valid_repository_urls(url, expected):
    assert canonical_repo_id(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/repo/extra",
        "https://github.com//owner/repo",
        "https://user@github.com/owner/repo",
        "https://github.com:444/owner/repo",
        "https://github.com/owner/repo?tab=readme",
        "https://github.com/owner/repo#section",
        "https://github.com/owner/.git",
        "https://github.com/owner/.",
        "https://github.com/owner/..",
    ],
)
def test_invalid_repository_urls(url):
    with pytest.raises(ValueError):
        canonical_repo_id(url)
