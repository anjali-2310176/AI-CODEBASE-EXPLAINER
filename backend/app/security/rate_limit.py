import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request

from app.config import settings


class InMemoryRateLimiter:
    """Token-bucket rate limiter per client IP. Replace with Redis in production."""

    def __init__(self, requests_per_minute: int) -> None:
        self._limit = requests_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, client_id: str) -> None:
        now = time.monotonic()
        window_start = now - 60.0

        with self._lock:
            timestamps = self._windows[client_id]
            self._windows[client_id] = [t for t in timestamps if t > window_start]
            if len(self._windows[client_id]) >= self._limit:
                raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
            self._windows[client_id].append(now)


rate_limiter = InMemoryRateLimiter(settings.rate_limit_per_minute)


def get_client_id(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
