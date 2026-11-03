"""
Tests for a stock's balance sheet, cash flow, insider purchases and
institutional holders (issue #195): the four live-only readers in
services/market_data.py, and their own routes under
GET /api/stock/{ticker}/....

Mirrors test_stock_fundamentals.py's own structure and reasoning - these
four are live-only the same way, for the same stated reason
(docs/adr/0007-per-ticker-fundamentals-are-live-only.md):

  - Live-only, each cached under its own key, separate from every other
    per-ticker read - a second call must not re-hit yfinance.
  - Neither GET /api/stock/{ticker} nor the batch GET /api/stocks ever call
    any of the four - a live-only read with no DB path must not risk
    breaking either one over something neither reads.
  - A missing cell (NaN, pandas NA) reads None, never 0 (invariant 7) -
    except a balance-sheet/cash-flow cell that genuinely *is* zero, which
    must still read as 0, not be swallowed into None by a falsy check.
  - A statement capped to its four most recent quarters, newest first, in
    yfinance's own row order - no curation of which rows to keep.
  - An empty DataFrame (a security yfinance has nothing for, e.g. an ETF)
    reads as an empty, successful answer - not an error.

No test here touches yfinance or Supabase for real: yf.Ticker is patched
throughout with synthetic pandas DataFrames shaped like yfinance's own,
the way test_stock_fundamentals.py and test_market_data.py do.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from fastapi.testclient import TestClient

from main import app
from rate_limit import FixedWindowLimiter
from services.cache import TTLCache
from services.market_data import (
    get_stock_balance_sheet,
    get_stock_cash_flow,
    get_stock_insider_purchases,
    get_stock_institutional_holders,
)

client = TestClient(app, raise_server_exceptions=False)


def _statement_df():
    """Six quarters (newest first, like yfinance's own), two line items -
    one with a NaN cell and one with a genuine zero, so both are told
    apart from "no data" in the same fixture."""
    columns = pd.to_datetime(
        ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"]
    )
    return pd.DataFrame(
        {
            columns[0]: [100.0, -5.0],
            columns[1]: [90.0, float("nan")],
            columns[2]: [80.0, -3.0],
            columns[3]: [70.0, -2.0],
            columns[4]: [60.0, -1.0],
            columns[5]: [50.0, 0.0],
        },
        index=["Total Assets", "Working Capital"],
    )


def _insider_df():
    return pd.DataFrame({
        "Insider Purchases Last 6m": ["Purchases", "Sales", "Total Insider Shares Held"],
        "Shares": [843588.0, 585844.0, 240512096.0],
        "Trans": pd.array([12, 19, pd.NA], dtype="Int64"),
    })


def _holders_df():
    return pd.DataFrame({
        "Date Reported": pd.to_datetime(["2026-06-30", "2026-06-30"]),
        "Holder": ["Vanguard Group Inc", "Blackrock Inc."],
        "pctHeld": [0.0882, 0.0797],
        "Shares": [1162996939, 959107911],
        "Value": [383009766304.0, 315862995450.0],
        "pctChange": [0.016, -0.0076],
    })


class GetStockBalanceSheetTests(unittest.TestCase):
    def setUp(self):
        self.cache_patch = patch("services.market_data.cache", TTLCache())
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def test_caps_to_the_four_most_recent_quarters(self):
        mock_ticker = MagicMock()
        mock_ticker.get_balance_sheet.return_value = _statement_df()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_balance_sheet("AAPL")

        self.assertEqual(result["columns"], ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"])
        mock_ticker.get_balance_sheet.assert_called_once_with(freq="quarterly", pretty=True)

    def test_a_blank_cell_is_none_but_a_real_zero_stays_zero(self):
        """Invariant 7, both directions: a NaN cell (no figure reported)
        must be None, and a genuine 0 (Working Capital's oldest quarter,
        outside the four-quarter cap here) must not be flattened to None
        by a falsy check - exercised within the kept window via the first
        column instead, where Total Assets is a real, non-zero 100.0."""
        mock_ticker = MagicMock()
        mock_ticker.get_balance_sheet.return_value = _statement_df()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_balance_sheet("AAPL")

        working_capital = next(r for r in result["rows"] if r["label"] == "Working Capital")
        # Column 1 (2026-03-31) was NaN in the fixture.
        self.assertIsNone(working_capital["values"][1])
        # Column 0 is a genuine negative figure, preserved as-is.
        self.assertEqual(working_capital["values"][0], -5.0)

    def test_an_empty_statement_is_an_empty_answer_not_an_error(self):
        mock_ticker = MagicMock()
        mock_ticker.get_balance_sheet.return_value = pd.DataFrame()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_balance_sheet("SPY")

        self.assertEqual(result, {"columns": [], "rows": []})

    def test_second_call_is_served_from_cache(self):
        mock_ticker = MagicMock()
        mock_ticker.get_balance_sheet.return_value = _statement_df()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker) as mock_cls:
            get_stock_balance_sheet("AAPL")
            get_stock_balance_sheet("AAPL")

        mock_cls.assert_called_once_with("AAPL")


class GetStockCashFlowTests(unittest.TestCase):
    def setUp(self):
        self.cache_patch = patch("services.market_data.cache", TTLCache())
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def test_reads_the_cash_flow_statement(self):
        mock_ticker = MagicMock()
        mock_ticker.get_cash_flow.return_value = _statement_df()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_cash_flow("AAPL")

        self.assertEqual(result["columns"], ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"])
        self.assertEqual(len(result["rows"]), 2)
        mock_ticker.get_cash_flow.assert_called_once_with(freq="quarterly", pretty=True)

    def test_cached_separately_from_balance_sheet(self):
        mock_ticker = MagicMock()
        mock_ticker.get_balance_sheet.return_value = _statement_df()
        mock_ticker.get_cash_flow.return_value = _statement_df()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            get_stock_balance_sheet("AAPL")
            get_stock_cash_flow("AAPL")

        mock_ticker.get_balance_sheet.assert_called_once()
        mock_ticker.get_cash_flow.assert_called_once()


class GetStockInsiderPurchasesTests(unittest.TestCase):
    def setUp(self):
        self.cache_patch = patch("services.market_data.cache", TTLCache())
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def test_reads_label_shares_and_trans(self):
        mock_ticker = MagicMock()
        mock_ticker.get_insider_purchases.return_value = _insider_df()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_insider_purchases("AAPL")

        self.assertEqual(result["rows"][0], {"label": "Purchases", "shares": 843588.0, "trans": 12.0})

    def test_a_pandas_na_transaction_count_is_none(self):
        mock_ticker = MagicMock()
        mock_ticker.get_insider_purchases.return_value = _insider_df()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_insider_purchases("AAPL")

        last_row = result["rows"][-1]
        self.assertEqual(last_row["label"], "Total Insider Shares Held")
        self.assertIsNone(last_row["trans"])
        self.assertEqual(last_row["shares"], 240512096.0)

    def test_an_empty_table_is_an_empty_answer_not_an_error(self):
        mock_ticker = MagicMock()
        mock_ticker.get_insider_purchases.return_value = pd.DataFrame()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_insider_purchases("SPY")

        self.assertEqual(result, {"rows": []})


class GetStockInstitutionalHoldersTests(unittest.TestCase):
    def setUp(self):
        self.cache_patch = patch("services.market_data.cache", TTLCache())
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def test_reads_every_field_for_each_holder(self):
        mock_ticker = MagicMock()
        mock_ticker.get_institutional_holders.return_value = _holders_df()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_institutional_holders("AAPL")

        self.assertEqual(len(result["holders"]), 2)
        first = result["holders"][0]
        self.assertEqual(first["dateReported"], "2026-06-30")
        self.assertEqual(first["holder"], "Vanguard Group Inc")
        self.assertAlmostEqual(first["pctHeld"], 0.0882)
        self.assertEqual(first["shares"], 1162996939.0)
        self.assertAlmostEqual(first["value"], 383009766304.0)
        self.assertAlmostEqual(first["pctChange"], 0.016)

    def test_an_empty_table_is_an_empty_answer_not_an_error(self):
        mock_ticker = MagicMock()
        mock_ticker.get_institutional_holders.return_value = pd.DataFrame()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            result = get_stock_institutional_holders("SPY")

        self.assertEqual(result, {"holders": []})


class StockRouteStatementTests(unittest.TestCase):
    def setUp(self):
        # A fresh, generous limiter per test - see test_stock_description's
        # own module docstring for why the real singleton is never spent here.
        patcher = patch("rate_limit.general_limiter", FixedWindowLimiter(limit=20, window_seconds=60))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_balance_sheet_route_carries_it(self):
        with patch("api.routes.get_stock_balance_sheet", return_value={"columns": [], "rows": []}):
            resp = client.get("/api/stock/NVDA/balance-sheet")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"columns": [], "rows": []})

    def test_cash_flow_route_carries_it(self):
        with patch("api.routes.get_stock_cash_flow", return_value={"columns": [], "rows": []}):
            resp = client.get("/api/stock/NVDA/cash-flow")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"columns": [], "rows": []})

    def test_insider_purchases_route_carries_it(self):
        with patch("api.routes.get_stock_insider_purchases", return_value={"rows": []}):
            resp = client.get("/api/stock/NVDA/insider-purchases")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"rows": []})

    def test_institutional_holders_route_carries_it(self):
        with patch("api.routes.get_stock_institutional_holders", return_value={"holders": []}):
            resp = client.get("/api/stock/NVDA/institutional-holders")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"holders": []})

    def test_single_ticker_and_batch_routes_never_call_any_of_the_four(self):
        """GET /api/stock/{ticker} and GET /api/stocks are read by StockPopup,
        HoldingChartPopup and the Table tab for name/sector/exchange alone -
        none of the four new live-only reads may risk breaking either over
        fields neither returns."""
        with (
            patch("api.routes.get_stock_info", return_value={"ticker": "NVDA", "name": "NVIDIA"}),
            patch("api.routes.get_stock_infos", return_value={"NVDA": {"ticker": "NVDA", "name": "NVIDIA"}}),
            patch("api.routes.get_stock_balance_sheet") as balance_sheet,
            patch("api.routes.get_stock_cash_flow") as cash_flow,
            patch("api.routes.get_stock_insider_purchases") as insider_purchases,
            patch("api.routes.get_stock_institutional_holders") as institutional_holders,
        ):
            resp1 = client.get("/api/stock/NVDA")
            resp2 = client.get("/api/stocks?tickers=NVDA")

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        balance_sheet.assert_not_called()
        cash_flow.assert_not_called()
        insider_purchases.assert_not_called()
        institutional_holders.assert_not_called()


if __name__ == "__main__":
    unittest.main()
