"""
In-memory TTL cache for yfinance responses.

Every fetch from Yahoo Finance is expensive (network + rate limits), so we
cache results keyed by request signature. Each entry has its own TTL — price
data expires faster (15 min) than holdings metadata (1 hour).

This is a single-process cache; it resets on server restart. For multi-worker
deployments, swap this for Redis or a shared-memory solution.
"""

import time
from typing import Any


class TTLCache:
    """Dict-backed cache where each entry expires after its individual TTL."""

    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        """Return cached value if present and not expired, else None."""
        entry = self._store.get(key)
        if entry is None:
            return None
        expires, value = entry
        if time.time() > expires:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: int):
        """Store a value with a TTL in seconds from now."""
        self._store[key] = (time.time() + ttl, value)

    def invalidate(self, prefix: str = ""):
        """Remove all entries whose key starts with the given prefix."""
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            del self._store[k]


# Module-level singleton shared across all service functions
cache = TTLCache()
