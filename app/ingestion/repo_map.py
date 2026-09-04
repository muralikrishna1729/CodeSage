# it maintains shape of whole project.
from pathlib import Path


IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

def build_directory_tree(repo_path:str, max_depth:int = 5) -> str:
    """
    Recursively build a directory tree representation of the repository.
    """
    lines = []
    root = Path(repo_path)
    def walk(path:Path, prefix:str = "", depth:int=0):
        """
            max_depth bounds output size — a deeply nested repo could otherwise
            produce a huge wall of text. The sort key puts directories before files
            (False < True), then sorts alphabetically by name.
        """
        if depth>=max_depth:
            return
        entries = sorted([p for p in path.iterdir() if p not in IGNORE_DIRS and not p.name.startswith(".")] , key=lambda p: (p.is_file(), p.name))
        for entry in entries:
            lines.append(f"{prefix}{entry.name}/")
            if entry.is_dir():
                walk(entry, prefix + "  ", depth + 1)
    walk(root)
    return "\n".join(lines)

def find_key_files(repo_path:str) -> dict:
    """
    Find key files in the repository, such as README.md, LICENSE, and setup.py.
    """
    root = Path(repo_path)
    key_names = ["README.md", "README.rst", "package.json", "requirements.txt", "pyproject.toml"]
    found_files = {}
    for name in key_names:
        matches = list(root.rglob(name))
        if matches:
            found_files[name] = str(matches[0].read_text(errors="ignore")[:3000])  # Read first 3000 chars to avoid huge files
    return found_files


def build_repo_map(repo_path:str)->dict:
    """
    Build a map of the repository, including its directory tree and key files.
    """
    repo_map = {
        "directory_tree": build_directory_tree(repo_path),
        "key_files": find_key_files(repo_path)
    }
    return repo_map

if __name__== "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build a directory tree representation of a repository.")
    parser.add_argument("--repo_path", type=str, help="Path to the repository.")
    parser.add_argument("--max_depth", type=int, default=5, help="Maximum depth to traverse.")
    args = parser.parse_args()
    #tree = build_directory_tree(args.repo_path, args.max_depth)
    #print(tree)
    # key_files = find_key_files(args.repo_path)
    # for name, content in key_files.items():
    #     print(f"\n{name}:")
    #     print(content)
    repo_map = build_repo_map(args.repo_path)
    print("\nRepository Map:")
    print(repo_map)