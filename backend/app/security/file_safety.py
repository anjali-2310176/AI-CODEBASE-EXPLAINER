import hashlib
from pathlib import Path

from app.config import settings

# Null-byte ratio threshold for binary detection
_BINARY_NULL_THRESHOLD = 0.01

GENERATED_PATTERNS = (
    "/migrations/versions/",
    "/__pycache__/",
    ".pb.go",
    "_generated.",
    ".generated.",
)

LOCK_FILES = {
    "poetry.lock", "Pipfile.lock", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", "Cargo.lock", "go.sum", "Gemfile.lock",
}


class FileSafetyError(Exception):
    pass


def is_binary(sample: bytes) -> bool:
    if not sample:
        return False
    if b"\x00" in sample:
        null_ratio = sample.count(b"\x00") / len(sample)
        if null_ratio > _BINARY_NULL_THRESHOLD:
            return True
    try:
        sample.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def is_generated_code(rel_path: str) -> bool:
    lower = rel_path.lower()
    if any(p in lower for p in GENERATED_PATTERNS):
        return True
    name = Path(rel_path).name
    return name in LOCK_FILES or name.endswith(".lock")


def validate_file_for_processing(file_path: Path, repo_path: Path) -> None:
    """Raise FileSafetyError if file should be skipped."""
    rel = str(file_path.relative_to(repo_path))

    if ".." in rel or rel.startswith("/"):
        raise FileSafetyError("Path traversal in file path")

    if is_generated_code(rel):
        raise FileSafetyError("Generated or lock file skipped")

    size = file_path.stat().st_size
    if size > settings.max_file_size_bytes:
        raise FileSafetyError(f"File exceeds size limit: {rel}")

    if size == 0:
        raise FileSafetyError("Empty file skipped")

    with open(file_path, "rb") as f:
        header = f.read(min(8192, size))
    if is_binary(header):
        raise FileSafetyError(f"Binary file skipped: {rel}")


def read_text_safe(file_path: Path, max_bytes: int | None = None) -> str:
    max_bytes = max_bytes or settings.max_file_size_bytes
    with open(file_path, "rb") as f:
        raw = f.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise FileSafetyError(f"File too large to read: {file_path.name}")
    if is_binary(raw[:8192]):
        raise FileSafetyError(f"Binary file: {file_path.name}")
    return raw.decode("utf-8", errors="replace")


def compute_file_hash(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
