import ipaddress
import re
import socket
from urllib.parse import urlparse

from app.config import settings

REPO_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")
BRANCH_PATTERN = re.compile(r"^[a-zA-Z0-9._/-]{1,128}$")


class SecurityError(Exception):
    pass


def validate_github_url(url: str) -> str:
    """Validate GitHub URL and block SSRF to private networks."""
    parsed = urlparse(url.strip())

    if parsed.scheme not in ("http", "https"):
        raise SecurityError("Only HTTP/HTTPS URLs are allowed")

    host = (parsed.hostname or "").lower()
    if host not in settings.allowed_hosts:
        raise SecurityError(f"Host not allowed: {host}. Only GitHub URLs are supported.")

    if settings.block_private_ips:
        _block_private_host(host)

    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise SecurityError("Invalid GitHub repository URL")

    for part in parts[:2]:
        if ".." in part or part.startswith("."):
            raise SecurityError("Invalid repository path")

    return url.strip().rstrip("/")


def _block_private_host(host: str) -> None:
    try:
        for info in socket.getaddrinfo(host, None):
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise SecurityError("URLs resolving to private networks are blocked")
    except socket.gaierror:
        pass  # DNS failure handled at clone time


def validate_branch_name(branch: str | None) -> str | None:
    if branch is None:
        return None
    branch = branch.strip()
    if not BRANCH_PATTERN.match(branch):
        raise SecurityError("Invalid branch name")
    return branch


def validate_repo_id(repo_id: str) -> str:
    if not REPO_ID_PATTERN.match(repo_id):
        raise SecurityError("Invalid repository ID")
    return repo_id


def safe_relative_path(base: str, user_path: str) -> str:
    """Prevent path traversal when resolving user-supplied paths."""
    from pathlib import Path

    base_path = Path(base).resolve()
    resolved = (base_path / user_path).resolve()
    if not str(resolved).startswith(str(base_path)):
        raise SecurityError("Path traversal detected")
    return str(resolved.relative_to(base_path))
