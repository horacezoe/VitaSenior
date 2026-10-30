"""Process-local throttling for public demo and binding-preview endpoints.

Deliberately small: the demo runs one backend process. Persistent per-account
limits (AUTH01) stay in the database; this only protects anonymous entry points
from being hammered during a demo. Not a distributed rate limiter.
"""
from app.core.clock import Clock
from app.core.errors import AppError

class RateLimiter:
    def __init__(self, clock: Clock):
        self.clock = clock
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str, *, limit: int, window_seconds: float) -> None:
        now = self.clock.now().timestamp()
        hits = [t for t in self._hits.get(key, []) if now - t < window_seconds]
        if len(hits) >= limit:
            retry_after = max(1, int(window_seconds - (now - hits[0])) + 1)
            raise AppError(429, "RATE_LIMITED", "Too many requests", {"retry_after_seconds": retry_after}, retryable=True)
        hits.append(now)
        self._hits[key] = hits

    def reset(self) -> None:
        self._hits.clear()
