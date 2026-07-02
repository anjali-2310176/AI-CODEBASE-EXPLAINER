import hashlib
import logging
import shutil
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

from git import Repo

from app.config import settings
from app.security.file_safety import FileSafetyError, validate_file_for_processing
from app.security.validation import SecurityError, validate_github_url

logger = logging.getLogger(__name__)


class CloneError(Exception):
    pass


class RepoLimitError(Exception):
    pass


def _parse_github_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) < 2:
        raise CloneError(f"Invalid GitHub URL: {url}")
    return parts[0], parts[1]


def repo_id_from_url(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def clone_repository(url: str, branch: str | None = None) -> tuple[str, str, Path]:
    """
    Shallow-clone a GitHub repository. Returns (repo_id, name, local_path).
    Never executes repo code — read-only git operations only.
    """
    url = validate_github_url(url)
    owner, repo_name = _parse_github_url(url)
    repo_id = repo_id_from_url(url)
    name = f"{owner}/{repo_name}"
    local_path = Path(settings.repos_dir) / repo_id

    local_path.parent.mkdir(parents=True, exist_ok=True)

    if local_path.exists() and (local_path / ".git").exists():
        repo = Repo(str(local_path))
        repo.remotes.origin.pull(depth=settings.clone_depth)
    else:
        if local_path.exists():
            shutil.rmtree(local_path)
        Repo.clone_from(
            url,
            str(local_path),
            branch=branch,
            depth=settings.clone_depth,
            single_branch=True,
        )

    _enforce_repo_limits(local_path)
    return repo_id, name, local_path


def _enforce_repo_limits(repo_path: Path) -> None:
    total_size = 0
    file_count = 0

    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        file_count += 1
        total_size += path.stat().st_size
        if file_count > settings.max_file_count:
            cleanup_clone(repo_path)
            raise RepoLimitError(f"Repository exceeds file count limit ({settings.max_file_count})")
        if total_size > settings.max_repo_size_bytes:
            cleanup_clone(repo_path)
            raise RepoLimitError(f"Repository exceeds size limit ({settings.max_repo_size_mb} MB)")


def cleanup_clone(repo_path: Path) -> None:
    """Remove cloned repository to free disk space."""
    if repo_path.exists():
        shutil.rmtree(repo_path, ignore_errors=True)
        logger.info("Cleaned up clone at %s", repo_path)


IGNORE_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", "dist", "build", ".eggs",
    ".tox", "htmlcov", ".idea", ".vscode", "site-packages",
}

IGNORE_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".egg", ".whl",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf",
    ".zip", ".tar", ".gz", ".lock", ".min.js", ".map",
}


def iter_python_files(repo_path: Path) -> Iterator[Path]:
    """
    Yield Python files one at a time — never loads full file list into memory
    for very large repos (stops at max_file_count).
    """
    count = 0
    for path in repo_path.rglob("*.py"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.suffix in IGNORE_EXTENSIONS:
            continue
        try:
            validate_file_for_processing(path, repo_path)
        except FileSafetyError:
            continue
        yield path
        count += 1
        if count >= settings.max_file_count:
            logger.warning("File count limit reached for %s", repo_path)
            break


def count_python_files(repo_path: Path) -> int:
    return sum(1 for _ in iter_python_files(repo_path))


def analyze_structure(repo_path: Path, max_depth: int = 6) -> dict:
    """Build directory tree structure without loading file contents."""
    root_name = repo_path.name

    def build_node(path: Path, depth: int) -> dict | None:
        rel = path.relative_to(repo_path)
        name = path.name

        if path.is_dir():
            if name in IGNORE_DIRS or (name.startswith(".") and name != "."):
                return None
            if depth >= max_depth:
                return {"name": name, "path": str(rel), "type": "directory", "children": []}
            children = []
            try:
                for child in sorted(path.iterdir()):
                    node = build_node(child, depth + 1)
                    if node:
                        children.append(node)
            except PermissionError:
                return None
            return {"name": name, "path": str(rel), "type": "directory", "children": children}

        if path.suffix == ".py":
            return {"name": name, "path": str(rel), "type": "file", "children": []}
        return None

    children = []
    for child in sorted(repo_path.iterdir()):
        node = build_node(child, 0)
        if node:
            children.append(node)

    def count_nodes(node: dict) -> tuple[int, int]:
        files, dirs = 0, 0
        if node["type"] == "file":
            return 1, 0
        dirs = 1
        for c in node.get("children", []):
            f, d = count_nodes(c)
            files += f
            dirs += d
        return files, dirs

    root = {"name": root_name, "path": ".", "type": "directory", "children": children}
    total_files, total_dirs = count_nodes(root)
    return {"root": root, "total_files": total_files, "total_directories": total_dirs}
