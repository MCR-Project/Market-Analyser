"""
Route-level tests for how a failed upstream fetch reaches the frontend.

The status code is the whole contract here: the frontend's useFetch
auto-retries a 5xx/429 and never auto-retries a 4xx, so answering 404 or
crashing out as an unhandled 500 for a temporary Yahoo/Supabase failure is
what wedged the dashboard on a cold start. A genuinely absent ETF must
still be a 404 - retrying that forever would be just as wrong.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from main import app
from services.market_data import DataUnavailable

client = TestClient(app, raise_server_exceptions=False)


class DataUnavailableHandlerTests(unittest.TestCase):
    def test_upstream_failure_is_a_retryable_503(self):
        with patch("api.routes.get_etf_info",
                   side_effect=DataUnavailable("ETF info for 'SPY' is temporarily unavailable upstream")):
            resp = client.get("/api/etf/SPY")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.headers.get("Retry-After"), "3")

    def test_missing_etf_is_still_a_permanent_404(self):
        """No holdings is a real answer about SPY, not a symptom of a cold
        start - it must stay a 404 so the frontend stops asking."""
        with patch("api.routes.get_etf_holdings", return_value=([], False)):
            resp = client.get("/api/correlation/SPY")

        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
