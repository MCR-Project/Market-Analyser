"""
Tests for a stock's business description (issue #158's own to-do on the
backend side of the new Stock page): get_stock_description in
services/market_data.py, and its own route, GET /api/stock/{ticker}/description.

Three things are pinned down:
  - The description is live-only and cached under its own key, separate
    from get_stock_info's `stock_info:{ticker}` entry - a second call must
    not re-hit yfinance.
  - Neither GET /api/stock/{ticker} (read by StockPopup and
    HoldingChartPopup for name/sector/exchange alone) nor the batch
    GET /api/stocks (the peer-name lookup) ever call get_stock_description -
    a live-only field with no DB path must not risk breaking either one
    over something neither reads.
  - A missing longBusinessSummary reads as an empty string, not a crash or
    a null the frontend has to special-case.

No test here touches yfinance or Supabase for real: yf.Ticker is patched
throughout, the way test_market_data.py already does.

StockRouteDescriptionTests exercises the real /api/stock, /api/stock/.../
description and /api/stocks routes through TestClient, which - per
test_rate_limit.py's own module docstring - share one bucket on the real
rate_limit.general_limiter with every other /api/* call in this suite
(every TestClient reports the same address). It patches in a fresh
FixedWindowLimiter for its own calls rather than spending headroom out of
that shared budget, the same way test_rate_limit.py's own middleware
tests do.
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
from services.market_data import get_stock_description

client = TestClient(app, raise_server_exceptions=False)


class GetStockDescriptionTests(unittest.TestCase):
    def setUp(self):
        # A fresh cache per test - the module-level singleton would
        # otherwise let one test's cached description leak into the next.
        self.cache_patch = patch("services.market_data.cache", TTLCache())
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def test_reads_long_business_summary(self):
        mock_ticker = MagicMock()
        mock_ticker.info = {"longBusinessSummary": "Designs graphics processors."}
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_description("NVDA")

        self.assertEqual(result, "Designs graphics processors.")

    def test_missing_summary_is_empty_string_not_none(self):
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_description("ZZZZ")

        self.assertEqual(result, "")

    def test_second_call_is_served_from_cache(self):
        mock_ticker = MagicMock()
        mock_ticker.info = {"longBusinessSummary": "Makes electric cars."}
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker) as mock_cls:
            get_stock_description("TSLA")
            get_stock_description("TSLA")

        mock_cls.assert_called_once_with("TSLA")


class StockRouteDescriptionTests(unittest.TestCase):
    def setUp(self):
        # A fresh, generous limiter per test - see the module docstring for
        # why the real singleton is never spent here.
        patcher = patch("rate_limit.general_limiter", FixedWindowLimiter(limit=10, window_seconds=60))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_single_ticker_route_never_calls_get_stock_description(self):
        """GET /api/stock/{ticker} - read by StockPopup and HoldingChartPopup
        for name/sector/exchange - must never pay for or risk failing on a
        field it doesn't return (issue #158 code review)."""
        with patch("api.routes.get_stock_info", return_value={"ticker": "NVDA", "name": "NVIDIA"}), \
             patch("api.routes.get_stock_description") as mock_description:
            resp = client.get("/api/stock/NVDA")

        self.assertEqual(resp.status_code, 200)
        mock_description.assert_not_called()
        self.assertNotIn("description", resp.json())

    def test_description_route_carries_it(self):
        with patch("api.routes.get_stock_description", return_value="Designs graphics processors."):
            resp = client.get("/api/stock/NVDA/description")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"description": "Designs graphics processors."})

    def test_batch_route_never_calls_get_stock_description(self):
        with patch("api.routes.get_stock_info", return_value={"ticker": "NVDA", "name": "NVIDIA"}), \
             patch("api.routes.get_stock_description") as mock_description:
            resp = client.get("/api/stocks?tickers=NVDA,TSLA")

        self.assertEqual(resp.status_code, 200)
        mock_description.assert_not_called()
        for row in resp.json():
            self.assertNotIn("description", row)


if __name__ == "__main__":
    unittest.main()
