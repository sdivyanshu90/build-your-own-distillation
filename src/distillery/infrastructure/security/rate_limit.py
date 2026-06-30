"""Fixed-window rate limiting with in-memory and Redis backends.

The in-memory limiter is correct for a single process (tests, local dev). The
Redis limiter is shared across all API replicas and is the production default.
Both expose the same :class:`RateLimiter` interface and return a
:class:`RateLimitDecision` carrying the headers clients expect.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a rate-limit check."""

    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


@runtime_checkable
class RateLimiter(Protocol):
    def check(self, key: str) -> RateLimitDecision: ...


def _reset_seconds(now: float, window: int) -> int:
    return int(window - (now % window))


class InMemoryRateLimiter:
    """Process-local fixed-window limiter (thread-safe)."""

    def __init__(self, limit_per_minute: int, *, window_seconds: int = _WINDOW_SECONDS) -> None:
        self._limit = limit_per_minute
        self._window = window_seconds
        self._buckets: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> RateLimitDecision:
        now = time.time()
        window_id = int(now // self._window)
        with self._lock:
            # Opportunistically drop stale windows to bound memory.
            self._buckets = {k: v for k, v in self._buckets.items() if k[1] >= window_id}
            count = self._buckets.get((key, window_id), 0) + 1
            self._buckets[(key, window_id)] = count
        remaining = max(0, self._limit - count)
        return RateLimitDecision(
            allowed=count <= self._limit,
            limit=self._limit,
            remaining=remaining,
            reset_seconds=_reset_seconds(now, self._window),
        )


class RedisRateLimiter:
    """Distributed fixed-window limiter backed by Redis ``INCR``/``EXPIRE``."""

    def __init__(
        self, client: Any, limit_per_minute: int, *, window_seconds: int = _WINDOW_SECONDS
    ) -> None:
        self._client = client
        self._limit = limit_per_minute
        self._window = window_seconds

    @classmethod
    def from_url(cls, url: str, limit_per_minute: int) -> RedisRateLimiter:  # pragma: no cover
        import redis

        return cls(redis.Redis.from_url(url), limit_per_minute)

    def check(self, key: str) -> RateLimitDecision:
        now = time.time()
        window_id = int(now // self._window)
        bucket = f"ratelimit:{key}:{window_id}"
        pipe = self._client.pipeline()
        pipe.incr(bucket)
        pipe.expire(bucket, self._window)
        count = int(pipe.execute()[0])
        remaining = max(0, self._limit - count)
        return RateLimitDecision(
            allowed=count <= self._limit,
            limit=self._limit,
            remaining=remaining,
            reset_seconds=_reset_seconds(now, self._window),
        )
