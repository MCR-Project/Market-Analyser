"""
Route-level test for GET /api/correlation's edge-count threshold logic.

`_correlation_summary` (services/market_data.py) reports a pair with too
little overlapping history as `None`, not 0.0 (issue #97). The edge-count
loop in api/routes.py used to reach that value through `.get(b, 0)` — a
pattern that only worked because a *missing* key defaulted to 0; now that
every pair explicitly holds a value (possibly `None`), the same `.get`
returns `None` for an unknown pair, and `None >= threshold` raises. This
locks in that a null pair is treated as "not an edge" rather than crashing
the endpoint the network view depends on.

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

client = TestClient(app, raise_server_exceptions=False)


class CorrelationEdgeCountTests(unittest.TestCase):
    def test_null_pair_is_not_counted_as_an_edge(self):
        fake_result = {
            "matrix": {
                "AAPL": {"AAPL": 1.0, "MSFT": 0.8, "NEW": None},
                "MSFT": {"AAPL": 0.8, "MSFT": 1.0, "NEW": None},
                "NEW": {"AAPL": None, "MSFT": None, "NEW": 1.0},
            },
            "tickers": ["AAPL", "MSFT", "NEW"],
            "averages": {"AAPL": 0.8, "MSFT": 0.8, "NEW": None},
            "strongest": {"a": "AAPL", "b": "MSFT", "value": 0.8},
            "weakest": {"a": "AAPL", "b": "MSFT", "value": 0.8},
            "hub": {"ticker": "AAPL", "avgCorr": 0.8},
        }
        with patch(
            "api.routes.get_etf_holdings",
            return_value=([["AAPL", 40.0], ["MSFT", 30.0], ["NEW", 5.0]], False),
        ), patch("api.routes.compute_correlation_matrix", return_value=fake_result):
            resp = client.get("/api/correlation/ETF?threshold=0.5")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # Only the AAPL/MSFT pair clears the threshold - NEW's null pairs
        # must not raise (None >= threshold) and must not be counted.
        self.assertEqual(body["edgeCount"], 1)


if __name__ == "__main__":
    unittest.main()
