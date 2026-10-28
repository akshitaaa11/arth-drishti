"""Response cache for the API: Redis when ``REDIS_URL`` is set and reachable, else an in-process TTL cache (README Phase 10).

``Cache.get_or_set(key, ttl, compute)`` returns ``(value, hit)``. Values are JSON-serialisable. A Redis outage never breaks a request:
the error is swallowed, the value is computed and (if possible) the in-process cache is used instead.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any, Protocol


class Cache(Protocol):
    def get_or_set(self, key: str, ttl: int, compute: Callable[[], Any]) -> tuple[Any, bool]: ...

    def clear(self) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get_or_set(self, key: str, ttl: int, compute: Callable[[], Any]) -> tuple[Any, bool]:
        now = time.monotonic()
        hit = self._store.get(key)
        if hit and hit[0] > now:
            return hit[1], True
        value = compute()
        self._store[key] = (now + ttl, value)
        return value, False

    def clear(self) -> None:
        self._store.clear()


class RedisCache:
    """Redis-backed cache with an in-process fallback if Redis fails at request time."""

    def __init__(self, client: Any, prefix: str = "bsp:") -> None:
        self.client, self.prefix = client, prefix
        self.fallback = MemoryCache()

    def get_or_set(self, key: str, ttl: int, compute: Callable[[], Any]) -> tuple[Any, bool]:
        full = self.prefix + key
        try:
            raw = self.client.get(full)
            if raw is not None:
                return json.loads(raw), True
            value = compute()
            self.client.set(full, json.dumps(value), ex=ttl)
            return value, False
        except Exception as exc:  # Redis down or the value is not JSON: serve without it
            if isinstance(exc, (TypeError, ValueError)):
                raise
            return self.fallback.get_or_set(key, ttl, compute)

    def clear(self) -> None:
        try:
            for key in self.client.scan_iter(self.prefix + "*"):
                self.client.delete(key)
        except Exception:
            pass
        self.fallback.clear()


def make_cache(url: str | None = None) -> Cache:
    """Redis if ``url`` (or REDIS_URL) answers a ping within one second, otherwise the in-process cache."""
    url = url if url is not None else os.environ.get("REDIS_URL", "")
    if not url:
        return MemoryCache()
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return RedisCache(client)
    except Exception:
        return MemoryCache()
