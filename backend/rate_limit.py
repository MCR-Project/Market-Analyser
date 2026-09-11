"""
Per-client request limiting for the public API (issue #93).

The API has no accounts and never will (see "Where portfolios live, and why
there is no account" in the README), so once it is reachable from a shared
link every request is anonymous. Two things are bounded here:

  - A general cap on every /api/* request, per client.
  - A separate, tighter cap on POST /api/portfolio/simulate, the most
    expensive request the service answers - it is checked in addition to
    the general cap, not instead of it, so exhausting it does not also
    exhaust a client's budget for ordinary GETs.

Both are in-process, fixed-window counters, deliberately not
`services/cache.py`'s TTL dict: a cache stores an answer per request key,
and this stores no answer at all, just how many requests a client has
made recently. The service runs one instance with one worker, so an
in-memory limiter is correct; a multi-instance deployment would need a
shared store (Redis or similar) instead; both cases are called out
explicitly below rather than left implicit.

A limited request answers 429 with Retry-After set to when its window
resets - the same shape as DataUnavailable's 503, so the frontend's
existing transient-failure handling (isTransientError, the backoff
schedule from issue #92) already knows what to do with it without any
frontend change.
"""

import math
import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

WINDOW_SECONDS = 60

# Defaults were sized against what real usage actually issues, not
# guessed: loading one ETF's dashboard (info, holdings, correlation,
# sectors, the measurement manifest, and one call per active measurement)
# is under 15 requests, and comparing several portfolios is a handful of
# /api/portfolio/simulate calls plus ticker resolution - both well under
# these ceilings even for a rapid burst of ETF switches.
GENERAL_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))
SIMULATE_LIMIT_PER_MINUTE = int(os.environ.get("SIMULATE_RATE_LIMIT_PER_MINUTE", "20"))


class FixedWindowLimiter:
    """Caps how many times `key` may be allowed within a rolling window
    that starts at that key's first request and resets `window_seconds`
    later - not a wall-clock-aligned minute, so a burst that happens to
    straddle :00 cannot double a client's real allowance.

    A request beyond the limit does not itself count against the window -
    a client already over the limit continuing to ask must not be able to
    push its own reset further away, which incrementing unconditionally
    would do.
    """

    def __init__(self, limit: int, window_seconds: int = WINDOW_SECONDS):
        self.limit = limit
        self.window_seconds = window_seconds
        self._windows: dict[str, tuple[float, int]] = {}  # key -> (window_start, count)

    def check(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds). retry_after is only
        meaningful when allowed is False."""
        now = time.time()
        start, count = self._windows.get(key, (now, 0))
        if now - start >= self.window_seconds:
            start, count = now, 0

        if count >= self.limit:
            # Rounded up and floored at 1 for the same reason as
            # market_data._RateLimitCooldown.remaining() (issue #92): 0
            # would tell the caller not to wait at all.
            retry_after = max(1, math.ceil(self.window_seconds - (now - start)))
            return False, retry_after

        self._windows[key] = (start, count + 1)
        return True, 0


# Module-level singletons, like services/cache.py's `cache` - shared
# across every request in this process. A test that needs a clean limiter
# patches these names with fresh instances rather than mutating them, the
# same way test_transient_failures.py swaps in a fresh
# _RateLimitCooldown.
general_limiter = FixedWindowLimiter(GENERAL_LIMIT_PER_MINUTE)
simulate_limiter = FixedWindowLimiter(SIMULATE_LIMIT_PER_MINUTE)


def client_ip(request: Request) -> str:
    """The client's real address, not this process's own view of the
    socket - Render (and any reverse proxy) terminates the real
    connection itself, so `request.client.host` is always the proxy.

    Trusts the *first* entry of X-Forwarded-For, which is Render's own
    convention for where the real client address goes; a self-hosted
    deployment behind a different proxy would need to confirm the same
    convention holds before trusting this. Deliberately not used for
    anything security-sensitive beyond bucketing a rate limit - a client
    that controls its own address (no proxy in front at all) only ever
    manages to give itself a bucket, never to escape one.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _too_many_requests(retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded - try again in {retry_after}s"},
        headers={"Retry-After": str(retry_after)},
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies the two limiters above to /api/* only - /health must never
    be limited, since it is what Render's own health check polls, and a
    limited health check would read as the service itself being down."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        ip = client_ip(request)

        allowed, retry_after = general_limiter.check(f"general:{ip}")
        if not allowed:
            return _too_many_requests(retry_after)

        if request.method == "POST" and request.url.path == "/api/portfolio/simulate":
            allowed, retry_after = simulate_limiter.check(f"simulate:{ip}")
            if not allowed:
                return _too_many_requests(retry_after)

        return await call_next(request)
