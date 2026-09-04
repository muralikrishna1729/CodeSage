import shutil
from pathlib import Path
from git import Repo
import argparse

CLONE_BASE_DIR = Path("./repos")

def clone_repo(repo_url:str, force:bool = False)->Path:
    """
    Clones a GitHub repo URL into ./repos/<repo_name>. If the repository already exists, it will be removed and re-cloned.

    Args:
        repo_url (str): The URL of the git repository to clone.
        force (bool): If True, force re-cloning even if the repository already exists.

    Returns:
        Path: The path to the cloned repository.
    """
    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    target_path = CLONE_BASE_DIR / repo_name
    CLONE_BASE_DIR.mkdir(parents=True, exist_ok=True)

    if target_path.exists():
        if force:
            shutil.rmtree(target_path)
        else:
            print(f"[clone] Repo already exists at {target_path}, reusing.")
            return target_path

    print(f"[clone] Cloning {repo_url} -> {target_path}")
    Repo.clone_from(repo_url, target_path, depth=1)  # depth=1 = shallow clone, faster
    return target_path

def get_repo_name(repo_url: str) -> str:
    return repo_url.rstrip("/").split("/")[-1].replace(".git", "")


def clean_repo(repo_url: str, force: bool = False) -> Path:
    """
    Alias kept for embed_store.ingest_repo: removes the existing clone if
    present and re-clones, exactly matching clone_repo(force=...).
    """
    return clone_repo(repo_url, force=force)



def main():
    parser = argparse.ArgumentParser(description="Clone a GitHub repository.")
    parser.add_argument("repo_url", nargs="?", help="The URL of the git repository to clone.")
    parser.add_argument("--repo_url", dest="repo_url_option", help="The URL of the git repository to clone.")
    parser.add_argument("--force", action="store_true", help="Force re-cloning even if the repository already exists.")
    args = parser.parse_args()

    repo_url = args.repo_url_option or args.repo_url
    if not repo_url:
        parser.error("a repository URL is required")

    clone_repo(repo_url, args.force)


if __name__ == "__main__":
    main()