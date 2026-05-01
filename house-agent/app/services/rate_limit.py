"""Simple in-memory rate limiting for security-sensitive endpoints."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._events[key]
            cutoff = now - window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                raise HTTPException(429, "too many requests", headers={"Retry-After": str(retry_after)})
            bucket.append(now)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


_RATE_LIMITER = InMemoryRateLimiter()


def client_ip(request: Request) -> str:
    forwarded_for = str(request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    if forwarded_for:
        return forwarded_for
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    limit: int,
    window_seconds: int,
    subject: str = "",
) -> None:
    normalized_subject = subject.strip().lower() or "-"
    key = f"{scope}:{client_ip(request)}:{normalized_subject}"
    _RATE_LIMITER.hit(key, limit=limit, window_seconds=window_seconds)


def reset_rate_limits() -> None:
    _RATE_LIMITER.reset()
