"""
Tests for reading price history over an explicit start/end window
(issue #55).

Two properties are worth locking down here, because breaking either is
silent rather than loud:

  - The DB path and the live path must answer the *same* request the same
    way. `prices` is filtered with an inclusive `date <= end` while
    yfinance's own `end` stops the day before, so the live call is shifted
    by a day - without that, a one-day window comes back populated from
    Supabase and empty from yfinance depending only on which path served
    it, the same by-construction agreement auto_adjust=True keeps between
    them (issue #13).

  - A window is part of a read's identity. Two different stretches of the
    same ticker's history are different answers, so they must not share a
    cache entry - the failure mode being a backtest quietly charting
    somebody else's dates.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from fastapi.testclient import TestClient

from main import app
from services.cache import TTLCache
from services.market_data import (
    DEFAULT_PERIOD,
    _closes_db,
    _closes_live,
    _get_price_series_db,
    _get_price_series_live,
    get_price_series,
    resolve_window,
)

client = TestClient(app, raise_server_exceptions=False)

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


class _FakeQuery:
    """Supabase fluent query builder stand-in that actually applies the
    filters it is given, so a test asserts the rows a window returns rather
    than only the calls that were made. Same paginated_select-driving shape
    as the fake in test_list_etf_summaries.py, plus the eq/in_/gte/lte the
    `prices` reads use."""

    def __init__(self, rows):
        self._rows = rows
        self._start = 0
        self._end = None
        self.filters = []

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        self._rows = [r for r in self._rows if r[column] == value]
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, values))
        self._rows = [r for r in self._rows if r[column] in values]
        return self

    def gte(self, column, value):
        self.filters.append(("gte", column, value))
        self._rows = [r for r in self._rows if r[column] >= value]
        return self

    def lte(self, column, value):
        self.filters.append(("lte", column, value))
        self._rows = [r for r in self._rows if r[column] <= value]
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows[self._start:self._end + 1])


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def table(self, name):
        query = _FakeQuery(sorted(self._rows, key=lambda r: (r["date"], r["granularity"])))
        self.queries.append(query)
        return query


def _price_rows():
    """One ticker's history as `prices` actually stores it: old months
    compacted into 'M' buckets anchored on the 1st, recent days left 'D'
    (see scripts/fetch_daily.py's bucket_by_age)."""
    return [
        {"ticker": "NVDA", "date": "2019-01-01", "close": 3.0, "volume": 10, "granularity": "M"},
        {"ticker": "NVDA", "date": "2019-02-01", "close": 4.0, "volume": 20, "granularity": "M"},
        {"ticker": "NVDA", "date": "2024-06-06", "close": 120.0, "volume": 30, "granularity": "D"},
        {"ticker": "NVDA", "date": "2024-06-07", "close": 121.0, "volume": 40, "granularity": "D"},
    ]


# ── resolve_window ───────────────────────────────────────────────────────────

class ResolveWindowTests(unittest.TestCase):
    def test_naming_neither_reads_the_default_period(self):
        self.assertEqual(resolve_window(None, None, None), (DEFAULT_PERIOD, None, None))

    def test_a_period_alone_passes_through(self):
        self.assertEqual(resolve_window("5y", None, None), ("5y", None, None))

    def test_a_window_drops_the_period(self):
        """A window answers for itself - the period slot must come back
        None so the DB path doesn't then overwrite the bounds with a
        lookback from today."""
        self.assertEqual(
            resolve_window(None, "2020-01-01", "2020-12-31"),
            (None, "2020-01-01", "2020-12-31"),
        )

    def test_either_bound_may_be_omitted(self):
        self.assertEqual(resolve_window(None, "2020-01-01", None), (None, "2020-01-01", None))
        self.assertEqual(resolve_window(None, None, "2020-12-31"), (None, None, "2020-12-31"))

    def test_period_and_window_together_are_rejected(self):
        """Honouring both would silently ignore one of them: a period is
        anchored to today and a window is not."""
        with self.assertRaises(ValueError) as ctx:
            resolve_window("1y", "2020-01-01", None)
        self.assertIn("mutually exclusive", str(ctx.exception))

    def test_an_unparseable_date_names_the_parameter_at_fault(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_window(None, "01/01/2020", None)
        self.assertIn("`start`", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            resolve_window(None, None, "not-a-date")
        self.assertIn("`end`", str(ctx.exception))

    def test_an_end_in_the_future_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_window(None, None, TOMORROW)
        self.assertIn("`end`", str(ctx.exception))

    def test_end_before_or_equal_to_start_is_rejected(self):
        for start, end in (("2020-12-31", "2020-01-01"), ("2020-01-01", "2020-01-01")):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError) as ctx:
                    resolve_window(None, start, end)
                self.assertIn("before", str(ctx.exception))

    def test_today_is_a_usable_end(self):
        today = date.today().isoformat()
        self.assertEqual(resolve_window(None, "2020-01-01", today), (None, "2020-01-01", today))


# ── Live path ────────────────────────────────────────────────────────────────

class LiveWindowTests(unittest.TestCase):
    def _fake_history(self):
        return pd.DataFrame(
            {"Close": [120.5], "Volume": [1_000_000]},
            index=pd.to_datetime(["2024-06-07"]),
        )

    def test_series_shifts_the_exclusive_end_by_a_day(self):
        """yfinance's `end` is exclusive; the DB's `date <= end` is not.
        Asking for a window ending on the 7th must include the 7th on both
        paths, so the live call asks for the 8th."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._fake_history()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            rows = _get_price_series_live("NVDA", None, "1d", start="2024-06-06", end="2024-06-07")

        mock_ticker.history.assert_called_once_with(
            start="2024-06-06", end="2024-06-08", interval="1d", auto_adjust=True
        )
        self.assertEqual(rows[0]["date"], "2024-06-07")

    def test_series_rows_carry_a_granularity(self):
        """Every row says which bucket it is, whichever path produced it -
        a caller must not have to know where the row came from to know
        whether it covers a day or a month."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._fake_history()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker):
            daily = _get_price_series_live("NVDA", "1y", "1d")
            monthly = _get_price_series_live("NVDA", "max", "1mo")

        self.assertEqual(daily[0]["granularity"], "D")
        self.assertEqual(monthly[0]["granularity"], "M")

    def test_closes_shifts_the_exclusive_end_by_a_day(self):
        """Same shift for the multi-ticker download the basket reads go
        through."""
        columns = pd.MultiIndex.from_tuples([("Close", "NVDA"), ("Close", "SMH")])
        frame = pd.DataFrame(
            [[120.5, 201.0]], index=pd.to_datetime(["2024-06-07"]), columns=columns
        )
        with patch("services.market_data.yf.download", return_value=frame) as mock_download:
            _closes_live(["NVDA", "SMH"], None, "1d", start="2024-06-06", end="2024-06-07")

        mock_download.assert_called_once_with(
            ["NVDA", "SMH"], start="2024-06-06", end="2024-06-08", interval="1d",
            progress=False, threads=True, auto_adjust=True,
        )


# ── Supabase path ────────────────────────────────────────────────────────────

class DbWindowTests(unittest.TestCase):
    def test_window_returns_only_rows_inside_it(self):
        db = _FakeClient(_price_rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            rows = _get_price_series_db("NVDA", None, start="2019-02-01", end="2024-06-06")

        self.assertEqual([r["date"] for r in rows], ["2019-02-01", "2024-06-06"])
        self.assertIn(("gte", "date", "2019-02-01"), db.queries[0].filters)
        self.assertIn(("lte", "date", "2024-06-06"), db.queries[0].filters)

    def test_window_spanning_tiers_reports_each_rows_own_granularity(self):
        """A window reaching years back is answered in monthly buckets for
        its old half and daily rows for its recent one (issue #10's tiered
        retention). Reading every row as one trading day would be wrong
        about the older half, so each row carries its own bucket."""
        db = _FakeClient(_price_rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            rows = _get_price_series_db("NVDA", None, start="2019-01-01", end="2024-06-07")

        self.assertEqual([r["granularity"] for r in rows], ["M", "M", "D", "D"])

    def test_a_period_still_reads_a_lookback_from_today(self):
        """The window parameters are additive: a period read must keep
        filtering on its own cutoff and must not acquire an upper bound."""
        db = _FakeClient(_price_rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            _get_price_series_db("NVDA", "1y")

        filters = db.queries[0].filters
        cutoff = (date.today() - timedelta(days=365)).isoformat()
        self.assertIn(("gte", "date", cutoff), filters)
        self.assertEqual([f for f in filters if f[0] == "lte"], [])

    def test_a_window_with_no_rows_is_a_miss(self):
        """None, not [] - an empty window is indistinguishable from a
        ticker that isn't synced yet, so it falls through to the live path
        rather than being served as a fact."""
        db = _FakeClient(_price_rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            self.assertIsNone(
                _get_price_series_db("NVDA", None, start="2021-01-01", end="2021-12-31")
            )

    def test_basket_window_filters_and_pivots(self):
        rows = _price_rows() + [
            {"ticker": "SMH", "date": "2024-06-06", "close": 200.0, "volume": 1, "granularity": "D"},
            {"ticker": "SMH", "date": "2024-06-07", "close": 201.0, "volume": 2, "granularity": "D"},
        ]
        db = _FakeClient(rows)
        with patch("services.market_data.get_client_optional", return_value=db):
            closes = _closes_db(["NVDA", "SMH"], None, start="2024-06-06", end="2024-06-07")

        self.assertEqual(list(closes.index), ["2024-06-06", "2024-06-07"])
        self.assertEqual(sorted(closes.columns), ["NVDA", "SMH"])

    def test_a_single_ticker_basket_is_a_hit_when_asked_for(self):
        """min_tickers is why _closes_db is shareable: correlation needs a
        pair before the DB counts as having answered, a one-holding
        portfolio does not - and would otherwise go live on every request
        for data Supabase is holding."""
        db = _FakeClient(_price_rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            for_correlation = _closes_db(["NVDA"], None, start="2024-06-06", end="2024-06-07")
            for_portfolio = _closes_db(
                ["NVDA"], None, start="2024-06-06", end="2024-06-07", min_tickers=1
            )

        self.assertIsNone(for_correlation)
        self.assertEqual(list(for_portfolio.columns), ["NVDA"])


# ── Caching and fallback ─────────────────────────────────────────────────────

class WindowCachingTests(unittest.TestCase):
    def test_two_windows_do_not_serve_each_others_rows(self):
        windows = {
            ("2019-01-01", "2019-02-01"): [
                {"date": "2019-01-01", "close": 3.0, "volume": 10, "granularity": "M"}
            ],
            ("2024-06-06", "2024-06-07"): [
                {"date": "2024-06-06", "close": 120.0, "volume": 30, "granularity": "D"}
            ],
        }

        def fake_db(ticker, period, start=None, end=None):
            return windows[(start, end)]

        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._get_price_series_db", side_effect=fake_db):
            old = get_price_series("NVDA", start="2019-01-01", end="2019-02-01")
            recent = get_price_series("NVDA", start="2024-06-06", end="2024-06-07")

        self.assertEqual(old[0]["date"], "2019-01-01")
        self.assertEqual(recent[0]["date"], "2024-06-06")

    def test_the_same_window_is_served_from_cache(self):
        rows = [{"date": "2024-06-06", "close": 120.0, "volume": 30, "granularity": "D"}]
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._get_price_series_db", return_value=rows) as mock_db:
            get_price_series("NVDA", start="2024-06-06", end="2024-06-07")
            get_price_series("NVDA", start="2024-06-06", end="2024-06-07")

        mock_db.assert_called_once()

    def test_a_db_miss_falls_back_live_with_the_same_window(self):
        """The window has to survive the fallback intact - a live call that
        quietly answered a different stretch of history would be worse than
        no answer at all."""
        rows = [{"date": "2024-06-06", "close": 120.0, "volume": 30, "granularity": "D"}]
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._get_price_series_db", return_value=None), \
             patch("services.market_data._get_price_series_live", return_value=rows) as mock_live:
            result = get_price_series("NVDA", start="2024-06-06", end="2024-06-07")

        mock_live.assert_called_once_with(
            "NVDA", None, "1d", start="2024-06-06", end="2024-06-07"
        )
        self.assertEqual(result, rows)


# ── GET /api/series ──────────────────────────────────────────────────────────

class SeriesRouteTests(unittest.TestCase):
    def test_a_window_reaches_the_service(self):
        rows = [{"date": "2020-01-02", "close": 1.0, "volume": 1, "granularity": "D"}]
        with patch("api.routes.get_price_series", return_value=rows) as mock_series:
            resp = client.get("/api/series/aapl?start=2020-01-01&end=2020-12-31")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), rows)
        mock_series.assert_called_once_with(
            "AAPL", period=None, interval="1d", start="2020-01-01", end="2020-12-31"
        )

    def test_a_period_request_is_unchanged(self):
        rows = [{"date": "2020-01-02", "close": 1.0, "volume": 1, "granularity": "D"}]
        with patch("api.routes.get_price_series", return_value=rows) as mock_series:
            resp = client.get("/api/series/AAPL?period=5d")

        self.assertEqual(resp.status_code, 200)
        mock_series.assert_called_once_with(
            "AAPL", period="5d", interval="1d", start=None, end=None
        )

    def test_an_unusable_window_is_a_400_naming_the_parameter(self):
        """A 400, not an empty array and not a 503: the request is wrong,
        and the frontend deliberately never retries a 4xx."""
        cases = [
            ("start=2020-12-31&end=2020-01-01", "before"),
            ("start=01/01/2020", "`start`"),
            (f"end={TOMORROW}", "`end`"),
            ("period=1y&start=2020-01-01", "mutually exclusive"),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                resp = client.get(f"/api/series/AAPL?{query}")
                self.assertEqual(resp.status_code, 400)
                self.assertIn(expected, resp.json()["detail"])

    def test_an_unusable_window_never_reaches_the_data_layer(self):
        with patch("services.market_data.get_client_optional") as mock_db, \
             patch("services.market_data.yf.Ticker") as mock_yf:
            resp = client.get("/api/series/AAPL?start=2021-01-01&end=2020-01-01")

        self.assertEqual(resp.status_code, 400)
        mock_db.assert_not_called()
        mock_yf.assert_not_called()


if __name__ == "__main__":
    unittest.main()
