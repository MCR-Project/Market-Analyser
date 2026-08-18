"""
Unit tests for services/market_data.py.

auto_adjust=True coverage (issue #13) locks in the two live-fallback paths
that must keep agreeing with fetch_ticker_rows's own guard in
test_fetch_daily.py - _get_price_series_live (single-ticker series) and
_closes_live (the correlation matrix's multi-ticker path) - so an upstream
yfinance default change, or an incautious edit, can't silently reintroduce
raw closes on just one of the read paths.

_correlation_summary coverage exercises its degenerate-input boundaries:
with zero or one available ticker there are no pairs to compare, and the
sentinel values used while scanning for strongest/weakest/hub (value=-1,
value=2, avgCorr=0) must never leak into the result unexamined - the 1+
ticker case previously did (hub.avgCorr=0, strongest.value=-1,
weakest.value=2 on degenerate input).

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from services.market_data import _closes_live, _correlation_summary, _get_price_series_live


class GetPriceSeriesLiveTests(unittest.TestCase):
    def _fake_history(self):
        dates = pd.to_datetime(["2024-06-06", "2024-06-07"])
        return pd.DataFrame(
            {"Close": [1205.0, 120.5], "Volume": [1_000_000, 2_000_000]},
            index=dates,
        )

    def test_requests_adjusted_history(self):
        """auto_adjust=True must stay explicit - relying on yfinance's
        default would silently reintroduce the mismatch with
        scripts/fetch_daily.py's fetch_ticker_rows if that default ever
        changed upstream."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._fake_history()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker) as mock_cls:
            result = _get_price_series_live("NVDA", "1y", "1d")

        mock_cls.assert_called_once_with("NVDA")
        mock_ticker.history.assert_called_once_with(period="1y", interval="1d", auto_adjust=True)
        self.assertEqual(result[1]["close"], 120.5)


class ClosesLiveTests(unittest.TestCase):
    def _fake_download(self):
        dates = pd.to_datetime(["2024-06-06", "2024-06-07"])
        columns = pd.MultiIndex.from_tuples([("Close", "NVDA"), ("Close", "SMH")])
        return pd.DataFrame(
            [[1205.0, 200.0], [120.5, 201.0]], index=dates, columns=columns
        )

    def test_requests_adjusted_history(self):
        """Same guard as _get_price_series_live, for the correlation
        matrix's multi-ticker download path - a raw close here makes
        pct_change() read a stock split as a huge one-day return
        (compute_correlation_matrix, issue #13)."""
        with patch("services.market_data.yf.download", return_value=self._fake_download()) as mock_download:
            closes = _closes_live(["NVDA", "SMH"], "1y", "1d")

        mock_download.assert_called_once_with(
            ["NVDA", "SMH"], period="1y", interval="1d", progress=False, threads=True,
            auto_adjust=True,
        )
        self.assertEqual(list(closes.columns), ["NVDA", "SMH"])


# ── _correlation_summary ─────────────────────────────────────────────────────

class CorrelationSummaryTests(unittest.TestCase):
    def test_zero_available_tickers_returns_degenerate_sentinels(self):
        """No requested ticker has a returns column at all (e.g. yfinance/DB
        had data for none of them) - available ends up empty, and the
        scan-for-extremes sentinels (strongest.value=-1, weakest.value=2,
        hub.avgCorr=0) are never overwritten, so they leak straight into the
        result unexamined. This pins that current, documented behavior."""
        returns = pd.DataFrame(index=pd.to_datetime(["2024-06-06", "2024-06-07"]))

        result = _correlation_summary(returns, ["AAPL", "MSFT"])

        self.assertEqual(result["tickers"], [])
        self.assertEqual(result["matrix"], {})
        self.assertEqual(result["averages"], {})
        self.assertEqual(result["strongest"], {"a": "", "b": "", "value": -1})
        self.assertEqual(result["weakest"], {"a": "", "b": "", "value": 2})
        self.assertEqual(result["hub"], {"ticker": "", "avgCorr": 0})

    def test_requested_ticker_missing_from_returns_is_dropped_from_available(self):
        """A ticker requested but absent from `returns.columns` (not yet
        synced) is silently excluded from `tickers`/`matrix`, not an
        error - the summary is computed over whichever subset is present."""
        returns = pd.DataFrame(
            {"AAPL": [0.01, -0.02, 0.03]},
            index=pd.to_datetime(["2024-06-06", "2024-06-07", "2024-06-10"]),
        )

        result = _correlation_summary(returns, ["AAPL", "MSFT"])

        self.assertEqual(result["tickers"], ["AAPL"])
        self.assertNotIn("MSFT", result["matrix"])

    def test_single_ticker_has_no_pairs_and_a_zero_average(self):
        """With exactly one available ticker there's no peer to correlate
        against - averages/hub read as 0 (not an error, not NaN), and
        strongest/weakest - which only ever compare pairs - never get
        assigned past their initial sentinels, matching the 0-ticker case."""
        returns = pd.DataFrame(
            {"AAPL": [0.01, -0.02, 0.03]},
            index=pd.to_datetime(["2024-06-06", "2024-06-07", "2024-06-10"]),
        )

        result = _correlation_summary(returns, ["AAPL"])

        self.assertEqual(result["tickers"], ["AAPL"])
        self.assertEqual(result["matrix"]["AAPL"]["AAPL"], 1.0)
        self.assertEqual(result["averages"], {"AAPL": 0})
        self.assertEqual(result["hub"], {"ticker": "AAPL", "avgCorr": 0})
        self.assertEqual(result["strongest"], {"a": "", "b": "", "value": -1})
        self.assertEqual(result["weakest"], {"a": "", "b": "", "value": 2})

    def test_three_tickers_picks_strongest_weakest_pair_and_hub(self):
        """Sanity check of the non-degenerate path: A and B move in
        lockstep (correlation 1), C is their exact mirror image
        (correlation -1 with both) - strongest must be the A/B pair,
        weakest either C pair (both are -1; scan order picks A/C first and
        a tie never overwrites it), and each ticker's average correlation
        to its peers must reflect that shape."""
        dates = pd.to_datetime(["2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06", "2024-06-07"])
        returns = pd.DataFrame(
            {
                "A": [0.01, -0.02, 0.03, -0.01, 0.02],
                "B": [0.01, -0.02, 0.03, -0.01, 0.02],
                "C": [-0.01, 0.02, -0.03, 0.01, -0.02],
            },
            index=dates,
        )

        result = _correlation_summary(returns, ["A", "B", "C"])

        self.assertEqual(result["tickers"], ["A", "B", "C"])
        self.assertEqual(result["strongest"], {"a": "A", "b": "B", "value": 1.0})
        self.assertEqual(result["weakest"], {"a": "A", "b": "C", "value": -1.0})
        self.assertEqual(result["averages"], {"A": 0, "B": 0, "C": -1})


if __name__ == "__main__":
    unittest.main()
