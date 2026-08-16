"""
Unit tests for the adjusted-price-storage logic added in scripts/fetch_daily.py
(issue #13): fetch_ticker_rows's auto_adjust setting, and the
_has_new_events/_needs_full_backfill helpers that decide whether a top-up
run needs to escalate into a full re-backfill because a split or dividend
retroactively rescaled the ticker's whole adjusted history.

Run with:   python -m unittest discover -s tests   (from backend/)
No pytest dependency required - the repo has no test runner configured yet,
so this sticks to the standard library.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.fetch_daily import (
    _has_new_events,
    _needs_full_backfill,
    _select_tickers_needing_sync,
    fetch_ticker_rows,
)


# ── fetch_ticker_rows ────────────────────────────────────────────────────────

class FetchTickerRowsTests(unittest.TestCase):
    def _fake_history(self):
        dates = pd.to_datetime(["2024-06-06", "2024-06-07"])
        return pd.DataFrame(
            {
                "Open": [1200.0, 121.0],
                "High": [1210.0, 122.0],
                "Low": [1190.0, 119.0],
                "Close": [1205.0, 120.5],
                "Volume": [1_000_000, 2_000_000],
                "Dividends": [0.0, 0.0],
                "Stock Splits": [0.0, 10.0],
            },
            index=dates,
        )

    def test_requests_adjusted_history(self):
        """auto_adjust=True is the whole point of issue #13 - a regression
        back to False would silently reintroduce raw closes in `prices`."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._fake_history()
        with patch("scripts.fetch_daily.yf.Ticker", return_value=mock_ticker) as mock_cls:
            fetch_ticker_rows("NVDA", "5d")
        mock_cls.assert_called_once_with("NVDA")
        mock_ticker.history.assert_called_once_with(period="5d", auto_adjust=True)

    def test_extracts_rows_and_split_events(self):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._fake_history()
        with patch("scripts.fetch_daily.yf.Ticker", return_value=mock_ticker):
            rows, dividend_events, split_events = fetch_ticker_rows("NVDA", "5d")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["date"], "2024-06-07")
        self.assertEqual(rows[1]["close"], 120.5)

        self.assertEqual(dividend_events, [])
        self.assertEqual(
            split_events, [{"ticker": "NVDA", "date": "2024-06-07", "splits": 10.0}]
        )

    def test_extracts_dividend_events(self):
        hist = self._fake_history()
        hist["Stock Splits"] = [0.0, 0.0]
        hist["Dividends"] = [0.0, 0.5]
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = hist
        with patch("scripts.fetch_daily.yf.Ticker", return_value=mock_ticker):
            _, dividend_events, split_events = fetch_ticker_rows("NVDA", "5d")

        self.assertEqual(split_events, [])
        self.assertEqual(
            dividend_events, [{"ticker": "NVDA", "date": "2024-06-07", "dividends": 0.5}]
        )


# ── _has_new_events / _needs_full_backfill ──────────────────────────────────

class _FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def execute(self):
        return SimpleNamespace(data=self._data)


class _FakeClient:
    """Minimal stand-in for the Supabase client's fluent query builder,
    enough to drive _has_new_events/_needs_full_backfill without a real DB."""

    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))


class HasNewEventsTests(unittest.TestCase):
    def test_no_events_is_never_new(self):
        client = _FakeClient({"splits": []})
        self.assertFalse(_has_new_events(client, "splits", "NVDA", []))

    def test_event_date_not_in_db_is_new(self):
        client = _FakeClient({"splits": []})
        events = [{"ticker": "NVDA", "date": "2024-06-07", "splits": 10.0}]
        self.assertTrue(_has_new_events(client, "splits", "NVDA", events))

    def test_event_date_already_recorded_is_not_new(self):
        client = _FakeClient({"splits": [{"date": "2024-06-07"}]})
        events = [{"ticker": "NVDA", "date": "2024-06-07", "splits": 10.0}]
        self.assertFalse(_has_new_events(client, "splits", "NVDA", events))


class NeedsFullBackfillTests(unittest.TestCase):
    def test_no_split_or_dividend_events(self):
        client = _FakeClient({"splits": [], "dividends": []})
        self.assertIsNone(_needs_full_backfill(client, "NVDA", [], []))

    def test_new_split_only(self):
        client = _FakeClient({"splits": [], "dividends": []})
        split_events = [{"ticker": "NVDA", "date": "2024-06-07", "splits": 10.0}]
        self.assertEqual(_needs_full_backfill(client, "NVDA", split_events, []), "split")

    def test_new_dividend_only(self):
        """The blocking case from the review: a dividend rescales the whole
        adjusted history exactly like a split does, so it must escalate too,
        not just splits."""
        client = _FakeClient({"splits": [], "dividends": []})
        dividend_events = [{"ticker": "AAPL", "date": "2024-05-10", "dividends": 0.25}]
        self.assertEqual(
            _needs_full_backfill(client, "AAPL", [], dividend_events), "dividend"
        )

    def test_new_split_and_dividend(self):
        client = _FakeClient({"splits": [], "dividends": []})
        split_events = [{"ticker": "NVDA", "date": "2024-06-07", "splits": 10.0}]
        dividend_events = [{"ticker": "NVDA", "date": "2024-06-07", "dividends": 0.01}]
        self.assertEqual(
            _needs_full_backfill(client, "NVDA", split_events, dividend_events),
            "split+dividend",
        )

    def test_already_recorded_events_do_not_re_escalate(self):
        """Once a split/dividend has already triggered one full backfill,
        it stays inside the rolling 5-day top-up window for several more
        runs - it must not force another full backfill every single time."""
        client = _FakeClient(
            {
                "splits": [{"date": "2024-06-07"}],
                "dividends": [{"date": "2024-06-07"}],
            }
        )
        split_events = [{"ticker": "NVDA", "date": "2024-06-07", "splits": 10.0}]
        dividend_events = [{"ticker": "NVDA", "date": "2024-06-07", "dividends": 0.01}]
        self.assertIsNone(
            _needs_full_backfill(client, "NVDA", split_events, dividend_events)
        )


# ── _select_tickers_needing_sync ────────────────────────────────────────────

class SelectTickersNeedingSyncTests(unittest.TestCase):
    """Regression coverage for the review finding: the sync loop used to
    iterate active tickers only, so an inactive ticker's `prices` rows
    never got the one-time re-backfill sql/003_store_adjusted_prices.sql's
    last_fetch=null reset was supposed to trigger, and stayed on the old
    raw-close convention forever."""

    def test_active_tickers_always_included(self):
        tickers = [{"id": "AAPL", "active": True, "last_fetch": "2024-01-01"}]
        self.assertEqual(_select_tickers_needing_sync(tickers), tickers)

    def test_inactive_never_fetched_is_included(self):
        """An inactive ticker with last_fetch still null - just added via
        add_ticker.py --inactive, or reset by the adjusted-prices migration -
        must get its one-time backfill despite being inactive."""
        tickers = [{"id": "OLDCO", "active": False, "last_fetch": None}]
        self.assertEqual(_select_tickers_needing_sync(tickers), tickers)

    def test_inactive_already_fetched_is_excluded(self):
        """Once an inactive ticker has a last_fetch, it goes back to being
        skipped by daily top-ups, same as before this fix."""
        tickers = [{"id": "OLDCO", "active": False, "last_fetch": "2024-01-01"}]
        self.assertEqual(_select_tickers_needing_sync(tickers), [])

    def test_sorted_by_id_and_mixed_set(self):
        tickers = [
            {"id": "MSFT", "active": True, "last_fetch": "2024-01-01"},
            {"id": "OLDCO", "active": False, "last_fetch": None},
            {"id": "ZZZ", "active": False, "last_fetch": "2024-01-01"},
            {"id": "AAPL", "active": True, "last_fetch": None},
        ]
        result = _select_tickers_needing_sync(tickers)
        self.assertEqual([t["id"] for t in result], ["AAPL", "MSFT", "OLDCO"])


if __name__ == "__main__":
    unittest.main()
