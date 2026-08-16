"""
Unit tests locking in auto_adjust=True on services/market_data.py's live
yfinance calls (issue #13). fetch_ticker_rows already has an equivalent
guard in test_fetch_daily.py; these cover the two live-fallback paths that
must keep agreeing with it - _get_price_series_live (single-ticker series)
and _closes_live (the correlation matrix's multi-ticker path) - so an
upstream yfinance default change, or an incautious edit, can't silently
reintroduce raw closes on just one of the read paths.

Run with:   python -m unittest discover -s tests   (from backend/)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from services.market_data import _closes_live, _get_price_series_live


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


if __name__ == "__main__":
    unittest.main()
