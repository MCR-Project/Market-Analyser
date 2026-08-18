"""
Unit tests for the adjusted-price-storage logic added in scripts/fetch_daily.py
(issue #13): fetch_ticker_rows's auto_adjust setting, and the
_has_new_events/_needs_full_backfill helpers that decide whether a top-up
run needs to escalate into a full re-backfill because a split or dividend
retroactively rescaled the ticker's whole adjusted history.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.fetch_daily import (
    _has_new_events,
    _needs_full_backfill,
    _select_tickers_needing_sync,
    bucket_by_age,
    compact_ticker,
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


# ── compact_ticker ───────────────────────────────────────────────────────────

class _FakePricesQuery:
    """Minimal stand-in for postgrest-py's fluent query builder, enough to
    drive compact_ticker (and the paginated_select it reads through) against
    an in-memory `prices` table without a real Supabase instance."""

    def __init__(self, table_rows: list[dict], mode: str, payload=None):
        self._table_rows = table_rows  # shared, mutable reference
        self._mode = mode
        self._payload = payload
        self._filters = []  # list of (kind, col, value)
        self._range = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def lt(self, col, val):
        self._filters.append(("lt", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, set(vals)))
        return self

    def order(self, *a, **k):
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def _matches(self, row):
        for kind, col, val in self._filters:
            if kind == "eq" and row.get(col) != val:
                return False
            if kind == "lt" and not (row.get(col) < val):
                return False
            if kind == "in" and row.get(col) not in val:
                return False
        return True

    def execute(self):
        if self._mode == "select":
            matched = [r for r in self._table_rows if self._matches(r)]
            if self._range is not None:
                start, end = self._range
                matched = matched[start:end + 1]
            return SimpleNamespace(data=matched)

        if self._mode == "upsert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            for new_row in payload:
                key = (new_row["ticker"], new_row["date"], new_row["granularity"])
                for i, r in enumerate(self._table_rows):
                    if (r["ticker"], r["date"], r["granularity"]) == key:
                        self._table_rows[i] = new_row
                        break
                else:
                    self._table_rows.append(new_row)
            return SimpleNamespace(data=payload)

        # delete
        removed = [r for r in self._table_rows if self._matches(r)]
        self._table_rows[:] = [r for r in self._table_rows if not self._matches(r)]
        return SimpleNamespace(data=removed)


class _FakePricesTable:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def select(self, *a, **k):
        return _FakePricesQuery(self.rows, "select")

    def upsert(self, payload):
        return _FakePricesQuery(self.rows, "upsert", payload=payload)

    def delete(self):
        return _FakePricesQuery(self.rows, "delete")


class _FakeCompactClient:
    """Stands in for the whole Supabase client, but only ever hands out the
    `prices` table - compact_ticker never touches any other table."""

    def __init__(self, rows: list[dict]):
        self._prices = _FakePricesTable(rows)

    def table(self, name):
        assert name == "prices", f"compact_ticker shouldn't touch table {name!r}"
        return self._prices


def _d(ticker, date_str, o, h, l, c, v):
    return {
        "ticker": ticker, "date": date_str, "granularity": "D",
        "open": o, "high": h, "low": l, "close": c, "volume": v,
    }


# ── bucket_by_age ────────────────────────────────────────────────────────────

class BucketByAgeTests(unittest.TestCase):
    """Boundary coverage for the "only compact a fully elapsed bucket" rule
    from bucket_by_age's docstring - the subtlest rule in the tiering logic.
    TODAY is fixed so each case's age relative to WEEKLY_TIER_START_DAYS
    (365 days) / MONTHLY_TIER_START_DAYS (5*365 days) is deterministic:
    weekly_cutoff = 2023-06-02 (a Friday - its ISO week is 2023-05-29 ..
    2023-06-04), monthly_cutoff = 2019-06-03 (a Monday, inside June 2019)."""

    TODAY = date(2024, 6, 1)

    def test_young_row_stays_daily(self):
        rows = [_d("NVDA", "2024-05-22", 10, 11, 9, 10.5, 100)]

        result = bucket_by_age(rows, self.TODAY)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["granularity"], "D")
        self.assertEqual(result[0]["date"], "2024-05-22")

    def test_row_in_a_fully_elapsed_week_is_compacted_to_weekly(self):
        """2023-05-23's ISO week (2023-05-22..2023-05-28) has fully elapsed
        past the weekly cutoff (2023-06-02) as of TODAY."""
        rows = [_d("NVDA", "2023-05-23", 10, 11, 9, 10.5, 100)]

        result = bucket_by_age(rows, self.TODAY)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["granularity"], "W")
        self.assertEqual(result[0]["date"], "2023-05-22")

    def test_row_older_than_the_cutoff_but_in_a_not_yet_elapsed_week_stays_daily(self):
        """2023-05-30 is already older than WEEKLY_TIER_START_DAYS as of
        TODAY, but its ISO week (2023-05-29..2023-06-04) hasn't FULLY
        elapsed past the weekly cutoff (2023-06-02) yet - part of the week
        is still on/after the cutoff. The whole day must be left daily so a
        later run's compact_ticker sweep can compact it once the week is
        genuinely done, instead of aggregating a partial week now."""
        rows = [_d("NVDA", "2023-05-30", 10, 11, 9, 10.5, 100)]

        result = bucket_by_age(rows, self.TODAY)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["granularity"], "D")
        self.assertEqual(result[0]["date"], "2023-05-30")

    def test_row_in_a_fully_elapsed_month_is_compacted_to_monthly(self):
        """2019-05-15's calendar month (May 2019) has fully elapsed past
        the monthly cutoff (2019-06-03) as of TODAY."""
        rows = [_d("NVDA", "2019-05-15", 10, 11, 9, 10.5, 100)]

        result = bucket_by_age(rows, self.TODAY)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["granularity"], "M")
        self.assertEqual(result[0]["date"], "2019-05-01")

    def test_row_past_the_monthly_day_count_but_in_a_not_yet_elapsed_month_stays_weekly(self):
        """2019-06-10 is already older than MONTHLY_TIER_START_DAYS as of
        TODAY, but its calendar month (June 2019) hasn't fully elapsed past
        the monthly cutoff (2019-06-03) yet, so it must NOT jump straight to
        monthly - it only qualifies for weekly (its own ISO week has fully
        elapsed), the tier a later run will eventually promote it from once
        the whole month is done."""
        rows = [_d("NVDA", "2019-06-10", 10, 11, 9, 10.5, 100)]

        result = bucket_by_age(rows, self.TODAY)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["granularity"], "W")
        self.assertEqual(result[0]["date"], "2019-06-10")

    def test_mixed_ages_are_split_across_all_three_tiers_in_one_call(self):
        rows = [
            _d("NVDA", "2024-05-22", 10, 12, 9, 11, 100),    # daily
            _d("NVDA", "2023-05-23", 20, 22, 19, 21, 200),   # weekly bucket...
            _d("NVDA", "2023-05-24", 21, 23, 20, 22, 300),   # ...same week
            _d("NVDA", "2019-05-15", 30, 32, 29, 31, 400),   # monthly
        ]

        result = bucket_by_age(rows, self.TODAY)

        by_granularity: dict[str, list[dict]] = {}
        for row in result:
            by_granularity.setdefault(row["granularity"], []).append(row)

        self.assertEqual(len(by_granularity["D"]), 1)
        self.assertEqual(len(by_granularity["W"]), 1)  # the two 2023 rows merged
        self.assertEqual(len(by_granularity["M"]), 1)

        week_row = by_granularity["W"][0]
        self.assertEqual(week_row["date"], "2023-05-22")
        self.assertEqual(week_row["open"], 20)   # bucket's first open
        self.assertEqual(week_row["close"], 22)  # bucket's last close
        self.assertEqual(week_row["high"], 23)
        self.assertEqual(week_row["low"], 19)
        self.assertEqual(week_row["volume"], 500)


class CompactTickerWeeklyTests(unittest.TestCase):
    # A Monday-anchored week (2023-01-02..2023-01-08) that has fully elapsed
    # past WEEKLY_TIER_START_DAYS as of this `today`, but is nowhere near old
    # enough to also fall into the monthly tier.
    TODAY = date(2024, 6, 1)
    WEEK_START = "2023-01-02"

    def test_fresh_bucket_is_aggregated(self):
        """No coarse row exists yet - this is a normal, first-time
        compaction, so the bucket gets aggregated and its sources removed."""
        rows = [
            _d("NVDA", "2023-01-02", 10, 12, 9, 11, 100),
            _d("NVDA", "2023-01-03", 11, 13, 10, 12, 200),
        ]
        client = _FakeCompactClient(rows)

        weeks, months, weeks_skipped, months_skipped = compact_ticker(client, "NVDA", self.TODAY)

        self.assertEqual((weeks, months, weeks_skipped, months_skipped), (1, 0, 0, 0))
        remaining = client._prices.rows
        self.assertEqual([r for r in remaining if r["granularity"] == "D"], [])
        week_rows = [r for r in remaining if r["granularity"] == "W"]
        self.assertEqual(len(week_rows), 1)
        self.assertEqual(week_rows[0]["date"], self.WEEK_START)
        self.assertEqual(week_rows[0]["open"], 10)
        self.assertEqual(week_rows[0]["close"], 12)

    def test_partially_compacted_bucket_is_cleaned_not_reaggregated(self):
        """Simulates a run that upserted the W candle and then died before
        deleting its D sources. A naive re-aggregation over just the
        leftover sources would silently overwrite the correct candle -
        instead the existing coarse row must be left untouched and only the
        leftover sources deleted."""
        correct_week_row = {
            "ticker": "NVDA", "date": self.WEEK_START, "granularity": "W",
            "open": 10, "high": 20, "low": 5, "close": 18, "volume": 999,
        }
        leftover_daily_rows = [
            # These alone would resample to open=11/high=13/low=10/close=12 -
            # very different from the correct candle above - proving that if
            # this bucket got re-aggregated, the assertions below would fail.
            _d("NVDA", "2023-01-03", 11, 13, 10, 12, 200),
        ]
        rows = [correct_week_row] + leftover_daily_rows
        client = _FakeCompactClient(rows)

        weeks, months, weeks_skipped, months_skipped = compact_ticker(client, "NVDA", self.TODAY)

        self.assertEqual((weeks, months, weeks_skipped, months_skipped), (0, 0, 1, 0))
        remaining = client._prices.rows
        self.assertEqual([r for r in remaining if r["granularity"] == "D"], [])
        week_rows = [r for r in remaining if r["granularity"] == "W"]
        self.assertEqual(week_rows, [correct_week_row])

    def test_second_consecutive_run_is_a_no_op(self):
        """After a clean (or now-recovered) compaction, re-running against
        the same state finds nothing left to do."""
        rows = [
            _d("NVDA", "2023-01-02", 10, 12, 9, 11, 100),
            _d("NVDA", "2023-01-03", 11, 13, 10, 12, 200),
        ]
        client = _FakeCompactClient(rows)
        compact_ticker(client, "NVDA", self.TODAY)

        second_run = compact_ticker(client, "NVDA", self.TODAY)

        self.assertEqual(second_run, (0, 0, 0, 0))


class CompactTickerMonthlyTests(unittest.TestCase):
    # A calendar month (2018-01) old enough to have fully elapsed past
    # MONTHLY_TIER_START_DAYS as of this `today`.
    TODAY = date(2024, 6, 1)
    MONTH_START = "2018-01-01"

    def test_mixed_daily_and_weekly_sources_are_aggregated(self):
        """A partially compacted month can hold a mix of D and W sources.
        Within one compact_ticker call the weekly pass always runs first
        and drains any D row old enough for the monthly tier too (its week
        is unavoidably old enough to already qualify for weekly
        compaction), so the stray D row becomes a fresh W candle before the
        monthly pass groups it with the pre-existing W row into one M
        candle - both granularities feed the same month either way."""
        rows = [
            _d("NVDA", "2018-01-02", 10, 12, 9, 11, 100),
            {
                "ticker": "NVDA", "date": "2018-01-08", "granularity": "W",
                "open": 11, "high": 15, "low": 10, "close": 14, "volume": 500,
            },
        ]
        client = _FakeCompactClient(rows)

        weeks, months, weeks_skipped, months_skipped = compact_ticker(client, "NVDA", self.TODAY)

        self.assertEqual((weeks, months, weeks_skipped, months_skipped), (1, 1, 0, 0))
        remaining = client._prices.rows
        self.assertEqual([r for r in remaining if r["granularity"] in ("D", "W")], [])
        month_rows = [r for r in remaining if r["granularity"] == "M"]
        self.assertEqual(len(month_rows), 1)
        self.assertEqual(month_rows[0]["date"], self.MONTH_START)
        self.assertEqual(month_rows[0]["close"], 14)

    def test_partially_compacted_month_is_cleaned_not_reaggregated(self):
        """Same crash-safety guarantee as the weekly pass: an M row already
        existing means a prior run died after upserting it but before
        deleting its leftover D/W sources - don't re-aggregate over the
        partial leftovers, just finish the cleanup. (The leftover D row
        still passes through the weekly pass first - see the comment above
        - but since it belongs to a week with no matching W candle, that
        pass aggregates it into a normal, freshly correct W row before the
        monthly pass ever sees it; the monthly pass then finds the existing
        M row and only deletes both leftover W rows, never overwriting the
        correct month candle.)"""
        correct_month_row = {
            "ticker": "NVDA", "date": self.MONTH_START, "granularity": "M",
            "open": 10, "high": 30, "low": 5, "close": 28, "volume": 9999,
        }
        leftover_sources = [
            _d("NVDA", "2018-01-02", 10, 12, 9, 11, 100),
            {
                "ticker": "NVDA", "date": "2018-01-08", "granularity": "W",
                "open": 11, "high": 15, "low": 10, "close": 14, "volume": 500,
            },
        ]
        rows = [correct_month_row] + leftover_sources
        client = _FakeCompactClient(rows)

        weeks, months, weeks_skipped, months_skipped = compact_ticker(client, "NVDA", self.TODAY)

        self.assertEqual((weeks, months, weeks_skipped, months_skipped), (1, 0, 0, 1))
        remaining = client._prices.rows
        self.assertEqual([r for r in remaining if r["granularity"] in ("D", "W")], [])
        self.assertEqual(remaining, [correct_month_row])


class CompactTickerCombinedCrashRecoveryTests(unittest.TestCase):
    """The trickiest interaction: a ticker with BOTH a half-finished weekly
    bucket and a half-finished monthly bucket in the same compact_ticker
    call. The monthly pass groups whatever W rows exist once the weekly
    pass has already run - including ones the weekly pass just created
    fresh in this same call (see CompactTickerMonthlyTests) - so this
    exercises that the monthly pass's existing-M-row check still correctly
    protects the month's candle even when part of its input was only
    created moments earlier by the weekly pass, and that it doesn't
    interfere with the independent, unrelated half-finished weekly bucket."""

    TODAY = date(2024, 6, 1)

    def test_independent_half_finished_buckets_are_both_recovered_correctly(self):
        # Half-finished weekly bucket: unrelated week, already has its W
        # candle, still has its leftover D source.
        correct_week_row = {
            "ticker": "NVDA", "date": "2023-01-02", "granularity": "W",
            "open": 10, "high": 20, "low": 5, "close": 18, "volume": 999,
        }
        leftover_daily_for_week = _d("NVDA", "2023-01-03", 11, 13, 10, 12, 200)

        # Half-finished monthly bucket: already has its M candle, still has
        # leftover D and W sources (a mix, per CompactTickerMonthlyTests).
        correct_month_row = {
            "ticker": "NVDA", "date": "2018-01-01", "granularity": "M",
            "open": 10, "high": 30, "low": 5, "close": 28, "volume": 9999,
        }
        leftover_daily_for_month = _d("NVDA", "2018-01-02", 10, 12, 9, 11, 100)
        leftover_weekly_for_month = {
            "ticker": "NVDA", "date": "2018-01-08", "granularity": "W",
            "open": 11, "high": 15, "low": 10, "close": 14, "volume": 500,
        }

        rows = [
            correct_week_row, leftover_daily_for_week,
            correct_month_row, leftover_daily_for_month, leftover_weekly_for_month,
        ]
        client = _FakeCompactClient(rows)

        weeks, months, weeks_skipped, months_skipped = compact_ticker(client, "NVDA", self.TODAY)

        # The month's leftover D row (2018-01-02) belongs to a week with no
        # existing W candle, so the weekly pass legitimately aggregates it
        # fresh (weeks=1) - that's correct, not a crash-safety violation,
        # per CompactTickerMonthlyTests. The unrelated week's existing W
        # candle is correctly left alone and only cleaned (weeks_skipped=1).
        # The month's existing M candle is correctly left alone and only
        # cleaned (months_skipped=1) even though one of its two W sources
        # was only just created by the weekly pass moments earlier.
        self.assertEqual((weeks, months, weeks_skipped, months_skipped), (1, 0, 1, 1))

        # Both leftover D sources, and the month's leftover/freshly-created W
        # sources, are gone - only the two correct coarse candles survive,
        # each exactly as it was before this run (never re-aggregated).
        remaining = client._prices.rows
        self.assertEqual([r for r in remaining if r["granularity"] == "D"], [])
        self.assertCountEqual(remaining, [correct_week_row, correct_month_row])


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
