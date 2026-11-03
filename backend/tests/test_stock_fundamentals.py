"""
Tests for a stock's valuation/ownership/growth fundamentals (issue #194):
get_stock_fundamentals in services/market_data.py, and its own route,
GET /api/stock/{ticker}/fundamentals.

Mirrors test_stock_description.py's own structure and reasoning, since
get_stock_fundamentals is live-only with no DB path the same way
get_stock_description is:
  - Live-only, cached under its own key, separate from get_stock_info's
    `stock_info:{ticker}` entry - a second call must not re-hit yfinance.
  - Neither GET /api/stock/{ticker} nor the batch GET /api/stocks ever
    call get_stock_fundamentals - a live-only field with no DB path must
    not risk breaking either one over something neither reads.
  - A field Yahoo's .info doesn't carry for a ticker reads as None, never
    a zero standing in for an absent figure (invariant 7).

No test here touches yfinance or Supabase for real: yf.Ticker is patched
throughout, the way test_stock_description.py and test_market_data.py do.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from main import app
from rate_limit import FixedWindowLimiter
from services.cache import TTLCache
from services.market_data import get_stock_fundamentals

client = TestClient(app, raise_server_exceptions=False)

_FULL_INFO = {
    "trailingPE": 24.31,
    "forwardPE": 21.05,
    "profitMargins": 0.1823,
    "heldPercentInsiders": 0.041,
    "heldPercentInstitutions": 0.672,
    "earningsQuarterlyGrowth": 0.095,
    "totalDebt": 12_300_000_000,
    "revenuePerShare": 9.87,
}


class GetStockFundamentalsTests(unittest.TestCase):
    def setUp(self):
        # A fresh cache per test - the module-level singleton would
        # otherwise let one test's cached fundamentals leak into the next.
        self.cache_patch = patch("services.market_data.cache", TTLCache())
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def test_reads_every_field_from_info(self):
        mock_ticker = MagicMock()
        mock_ticker.info = _FULL_INFO
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_fundamentals("NVDA")

        self.assertEqual(result, _FULL_INFO)

    def test_missing_fields_are_none_not_zero(self):
        """Invariant 7: a field .info doesn't carry for this ticker (e.g.
        an ETF's own P/E) is absent, and must read None, never a 0 that
        would claim the ratio really is zero."""
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_fundamentals("SPY")

        self.assertEqual(result, {
            "trailingPE": None,
            "forwardPE": None,
            "profitMargins": None,
            "heldPercentInsiders": None,
            "heldPercentInstitutions": None,
            "earningsQuarterlyGrowth": None,
            "totalDebt": None,
            "revenuePerShare": None,
        })

    def test_second_call_is_served_from_cache(self):
        mock_ticker = MagicMock()
        mock_ticker.info = _FULL_INFO
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker) as mock_cls:
            get_stock_fundamentals("TSLA")
            get_stock_fundamentals("TSLA")

        mock_cls.assert_called_once_with("TSLA")

    def test_cached_separately_from_stock_info(self):
        """A ticker's get_stock_info call must not be served by - or serve -
        this cache entry; the two cache under different keys on the same
        ticker."""
        mock_ticker = MagicMock()
        mock_ticker.info = _FULL_INFO
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker), \
             patch("services.market_data.get_client_optional", return_value=None):
            from services.market_data import get_stock_info
            get_stock_info("NVDA")
            fundamentals = get_stock_fundamentals("NVDA")

        self.assertEqual(fundamentals["trailingPE"], 24.31)


class StockRouteFundamentalsTests(unittest.TestCase):
    def setUp(self):
        # A fresh, generous limiter per test - see test_stock_description's
        # own module docstring for why the real singleton is never spent here.
        patcher = patch("rate_limit.general_limiter", FixedWindowLimiter(limit=10, window_seconds=60))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_single_ticker_route_never_calls_get_stock_fundamentals(self):
        with patch("api.routes.get_stock_info", return_value={"ticker": "NVDA", "name": "NVIDIA"}), \
             patch("api.routes.get_stock_fundamentals") as mock_fundamentals:
            resp = client.get("/api/stock/NVDA")

        self.assertEqual(resp.status_code, 200)
        mock_fundamentals.assert_not_called()

    def test_fundamentals_route_carries_it(self):
        with patch("api.routes.get_stock_fundamentals", return_value=_FULL_INFO):
            resp = client.get("/api/stock/NVDA/fundamentals")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _FULL_INFO)

    def test_batch_route_never_calls_get_stock_fundamentals(self):
        stubbed = {
            "NVDA": {"ticker": "NVDA", "name": "NVIDIA"},
            "TSLA": {"ticker": "TSLA", "name": "Tesla"},
        }
        with patch("api.routes.get_stock_infos", return_value=stubbed), \
             patch("api.routes.get_stock_fundamentals") as mock_fundamentals:
            resp = client.get("/api/stocks?tickers=NVDA,TSLA")

        self.assertEqual(resp.status_code, 200)
        mock_fundamentals.assert_not_called()


if __name__ == "__main__":
    unittest.main()
