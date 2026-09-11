"""
Tests for rate_limit.py — per-client request limiting (issue #93).

FixedWindowLimiter is tested standalone first, then the middleware end to
end against a throwaway FastAPI app with fresh, tiny limiter instances
patched in. Deliberately never driven through the real, module-level
`general_limiter`/`simulate_limiter` at their real 120/20-per-minute
sizes: Starlette's TestClient reports the same client address
("testclient", 50000) for every instance, so every /api/* call made by
this whole test suite already shares one bucket on those singletons.
Looping real requests to trip a 120/min limit here would consume that
shared budget and could start failing unrelated tests elsewhere in the
suite, depending on run order - the same class of leak
test_transient_failures.py guards against for _rate_limit_cooldown.

Run with:   pytest   (from the repo root)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from rate_limit import FixedWindowLimiter, RateLimitMiddleware, client_ip


class FixedWindowLimiterTests(unittest.TestCase):
    def test_allows_up_to_the_limit(self):
        limiter = FixedWindowLimiter(limit=3, window_seconds=60)
        for _ in range(3):
            allowed, _ = limiter.check("a")
            self.assertTrue(allowed)

    def test_refuses_the_next_one(self):
        limiter = FixedWindowLimiter(limit=3, window_seconds=60)
        for _ in range(3):
            limiter.check("a")
        allowed, retry_after = limiter.check("a")
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)

    def test_a_refused_request_does_not_extend_its_own_window(self):
        """Continuing to ask after being refused must not push the reset
        further away - only a request that was actually allowed should
        count against the window."""
        with patch("rate_limit.time.time", return_value=1_000.0):
            limiter = FixedWindowLimiter(limit=1, window_seconds=60)
            limiter.check("a")
        with patch("rate_limit.time.time", return_value=1_000.0 + 10):
            _, retry_after_1 = limiter.check("a")
        with patch("rate_limit.time.time", return_value=1_000.0 + 20):
            _, retry_after_2 = limiter.check("a")
        # The window still started at t=1000 both times - the refusal at
        # t=1010 didn't reset it to t=1010, so the reset at t=1020 is 10s
        # sooner than it would be if it had.
        self.assertEqual(retry_after_1 - retry_after_2, 10)

    def test_different_keys_have_independent_budgets(self):
        limiter = FixedWindowLimiter(limit=1, window_seconds=60)
        allowed_a, _ = limiter.check("a")
        allowed_b, _ = limiter.check("b")
        self.assertTrue(allowed_a)
        self.assertTrue(allowed_b)

    def test_the_window_resets_after_it_elapses(self):
        with patch("rate_limit.time.time", return_value=1_000.0):
            limiter = FixedWindowLimiter(limit=1, window_seconds=60)
            self.assertTrue(limiter.check("a")[0])
            self.assertFalse(limiter.check("a")[0])
        with patch("rate_limit.time.time", return_value=1_000.0 + 61):
            self.assertTrue(limiter.check("a")[0])

    def test_retry_after_counts_down(self):
        with patch("rate_limit.time.time", return_value=1_000.0):
            limiter = FixedWindowLimiter(limit=1, window_seconds=60)
            limiter.check("a")
        with patch("rate_limit.time.time", return_value=1_000.0 + 40):
            _, retry_after = limiter.check("a")
        self.assertEqual(retry_after, 20)


class ClientIpTests(unittest.TestCase):
    def _request(self, headers=None, client_host="1.2.3.4"):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": (client_host, 12345) if client_host else None,
        }
        return Request(scope)

    def test_uses_the_first_forwarded_entry(self):
        """Render's own convention: the first entry is the real client,
        anything after it is intermediate proxies."""
        req = self._request({"x-forwarded-for": "203.0.113.5, 10.0.0.1"})
        self.assertEqual(client_ip(req), "203.0.113.5")

    def test_falls_back_to_the_socket_peer_with_no_header(self):
        req = self._request({}, client_host="9.9.9.9")
        self.assertEqual(client_ip(req), "9.9.9.9")

    def test_strips_whitespace_around_the_first_entry(self):
        req = self._request({"x-forwarded-for": "  203.0.113.5  ,10.0.0.1"})
        self.assertEqual(client_ip(req), "203.0.113.5")


def _build_app():
    """A throwaway app wired the same way main.py wires the real one -
    RateLimitMiddleware added before CORSMiddleware, so CORSMiddleware
    stays outermost and still stamps headers on a response
    RateLimitMiddleware short-circuits (see main.py's own comment on
    this - reversing the order was a real bug caught before it shipped)."""
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/etfs")
    def etfs():
        return []

    @app.post("/api/portfolio/simulate")
    def simulate():
        return {}

    return app


class RateLimitMiddlewareTests(unittest.TestCase):
    def setUp(self):
        # Fresh, small limiters per test - see the module docstring for
        # why the real singletons are never driven to their limit here.
        self.general = FixedWindowLimiter(limit=3, window_seconds=60)
        self.simulate = FixedWindowLimiter(limit=1, window_seconds=60)
        patcher_g = patch("rate_limit.general_limiter", self.general)
        patcher_s = patch("rate_limit.simulate_limiter", self.simulate)
        patcher_g.start()
        patcher_s.start()
        self.addCleanup(patcher_g.stop)
        self.addCleanup(patcher_s.stop)
        self.client = TestClient(_build_app())

    def test_requests_within_the_limit_succeed(self):
        for _ in range(3):
            resp = self.client.get("/api/etfs")
            self.assertEqual(resp.status_code, 200)

    def test_the_next_request_is_refused_with_retry_after(self):
        for _ in range(3):
            self.client.get("/api/etfs")
        resp = self.client.get("/api/etfs")
        self.assertEqual(resp.status_code, 429)
        self.assertIsNotNone(resp.headers.get("Retry-After"))

    def test_health_is_never_limited(self):
        for _ in range(10):
            resp = self.client.get("/health")
            self.assertEqual(resp.status_code, 200)

    def test_different_forwarded_ips_get_separate_buckets(self):
        for _ in range(3):
            resp = self.client.get("/api/etfs", headers={"X-Forwarded-For": "1.1.1.1"})
            self.assertEqual(resp.status_code, 200)
        # A different client is unaffected by the first one's exhausted budget.
        resp = self.client.get("/api/etfs", headers={"X-Forwarded-For": "2.2.2.2"})
        self.assertEqual(resp.status_code, 200)
        # The first client is still limited.
        resp = self.client.get("/api/etfs", headers={"X-Forwarded-For": "1.1.1.1"})
        self.assertEqual(resp.status_code, 429)

    def test_simulate_has_its_own_tighter_budget(self):
        """Exhausting simulate's own (lower) limit must not consume the
        general budget beyond what those same requests already used -
        a plain GET from the same client is still answered."""
        resp = self.client.post("/api/portfolio/simulate")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post("/api/portfolio/simulate")
        self.assertEqual(resp.status_code, 429)

        resp = self.client.get("/api/etfs")
        self.assertEqual(resp.status_code, 200)

    def test_a_429_still_carries_the_cors_header(self):
        """The whole point of adding RateLimitMiddleware before
        CORSMiddleware (main.py): a rate-limited browser request must
        still be readable by the frontend's own JS, or the 429 and its
        Retry-After are invisible to it - it just sees a CORS failure."""
        for _ in range(3):
            self.client.get("/api/etfs", headers={"Origin": "http://localhost:5173"})
        resp = self.client.get("/api/etfs", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "http://localhost:5173")

    def test_a_non_api_path_is_never_limited(self):
        @self.client.app.get("/docs-alt")
        def _docs_alt():
            return {}

        for _ in range(10):
            resp = self.client.get("/docs-alt")
            self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
