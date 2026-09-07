"""
Tests for services/tickers.py — searching the tracked universe and
resolving a symbol outside it (issue #58).

The split between the two is the thing under test as much as either half:

  - **Search must never reach the network.** It runs on every keystroke of
    a picker, so it answers from a cached snapshot of `ticker` and `etfs`.
    A yfinance call in that path would be invisible in development and
    ruinous in use, so the tests assert the live helpers are not called at
    all rather than merely that the answer looked right.

  - **Resolution must tell three outcomes apart.** A symbol that is real,
    a symbol that does not exist, and an upstream that could not be
    reached are three different answers - 200, 404 and 503 - and the
    frontend retries only the last. Collapsing any two of them is what
    #47 was about.

Resolution is also what stands between a typo and a holding quietly
simulated as a pile of cash, since a made-up ticker's info request comes
back as a shell dict rather than an error: the test is price history, not
a name.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from main import app
from services.cache import TTLCache
from services.market_data import DataUnavailable
from services.tickers import resolve_ticker, search_tickers

client = TestClient(app, raise_server_exceptions=False)

TICKERS = [
    {"id": "AMD", "name": "Advanced Micro Devices, Inc.", "sector": "Technology", "logo": ""},
    {"id": "ENVX", "name": "Enovix Corporation", "sector": "Industrials", "logo": ""},
    {"id": "NVDA", "name": "NVIDIA Corporation", "sector": "Technology", "logo": "nvda.png"},
    {"id": "NVS", "name": "Novartis AG", "sector": "Healthcare", "logo": ""},
    {"id": "TSM", "name": "Taiwan Semiconductor Manufacturing", "sector": "Technology", "logo": ""},
]
ETFS = [
    {"id": "SMH", "name": "VanEck Semiconductor ETF", "cat": "Technology"},
    {"id": "SOXX", "name": "iShares Semiconductor ETF", "cat": "Technology"},
]
PRICES = [{"ticker": "NVDA", "date": "1999-01-01"}, {"ticker": "AMD", "date": "1999-01-01"}]


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)
        self._start, self._end, self._limit = 0, None, None

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def eq(self, column, value):
        self._rows = [row for row in self._rows if row.get(column) == value]
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        rows = self._rows[self._start:None if self._end is None else self._end + 1]
        if self._limit is not None:
            rows = rows[:self._limit]
        return SimpleNamespace(data=rows)


class _FakeClient:
    """Serves the three tables tickers.py reads, and counts the reads so a
    test can prove the universe was fetched once rather than per query."""

    def __init__(self, tickers=None, etfs=None, prices=None):
        self._tables = {
            "ticker": TICKERS if tickers is None else tickers,
            "etfs": ETFS if etfs is None else etfs,
            "prices": PRICES if prices is None else prices,
        }
        self.reads = []

    def table(self, name):
        self.reads.append(name)
        return _FakeQuery(self._tables.get(name, []))


class _Fixture(unittest.TestCase):
    """Every test runs against an empty cache, so one test's cached
    universe or resolution cannot answer another's question."""

    def setUp(self):
        self.db = _FakeClient()
        self._patches = [
            patch("services.tickers.cache", TTLCache()),
            patch("services.tickers.get_client_optional", return_value=self.db),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)


# ── Search ───────────────────────────────────────────────────────────────────

class SearchTests(_Fixture):
    def test_a_symbol_fragment_finds_the_ticker(self):
        results = search_tickers("NV")

        self.assertEqual([r["symbol"] for r in results], ["NVDA", "NVS", "ENVX"])
        # ENVX is here for its symbol containing NV, not for its name.

    def test_symbol_matches_outrank_name_matches(self):
        """Someone typing SM wants the fund called SMH before the three
        companies with "Semiconductor" in their names."""
        results = [r["symbol"] for r in search_tickers("SM")]

        self.assertEqual(results[0], "SMH")
        self.assertLess(results.index("SMH"), results.index("TSM"))

    def test_a_name_matches_only_where_one_of_its_words_starts(self):
        """Matching anywhere inside a word pulls Invesco QQQ up for "NV",
        two keystrokes into a search for NVDA - noise from a fund about
        neither letter."""
        noisy = search_tickers("NV")

        self.assertNotIn("QQQ", [r["symbol"] for r in noisy])
        self.assertIn("NVDA", [r["symbol"] for r in noisy])

    def test_an_exact_symbol_comes_first(self):
        self.assertEqual(search_tickers("smh")[0]["symbol"], "SMH")

    def test_a_name_fragment_finds_both_funds(self):
        results = search_tickers("semiconductor")

        self.assertEqual(sorted(r["symbol"] for r in results), ["SMH", "SOXX", "TSM"])

    def test_search_is_case_insensitive(self):
        self.assertEqual(search_tickers("nvda")[0]["symbol"], "NVDA")

    def test_results_carry_what_a_picker_row_needs(self):
        stock = search_tickers("NVDA")[0]
        fund = search_tickers("SMH")[0]

        self.assertEqual(stock["kind"], "stock")
        self.assertTrue(stock["tracked"])
        self.assertEqual(stock["name"], "NVIDIA Corporation")
        self.assertEqual(stock["sector"], "Technology")
        self.assertEqual(stock["sectorTag"], "TECH")
        self.assertEqual(stock["logo"], "nvda.png")
        self.assertEqual(fund["kind"], "etf")
        self.assertEqual(fund["category"], "Technology")

    def test_an_empty_query_lists_the_universe(self):
        """A picker that has been opened but not typed into still has
        something to show."""
        results = search_tickers("")

        self.assertEqual([r["symbol"] for r in results],
                         ["AMD", "ENVX", "NVDA", "NVS", "SMH", "SOXX", "TSM"])

    def test_the_limit_is_respected(self):
        self.assertEqual(len(search_tickers("", limit=2)), 2)

    def test_nothing_matching_is_an_empty_list(self):
        self.assertEqual(search_tickers("ZZZZ"), [])

    def test_the_universe_is_read_once_however_many_searches_run(self):
        """The as-you-type path: five keystrokes must not be five round
        trips to Supabase."""
        for query in ("N", "NV", "NVD", "NVDA", "SMH"):
            search_tickers(query)

        self.assertEqual(self.db.reads.count("ticker"), 1)
        self.assertEqual(self.db.reads.count("etfs"), 1)

    def test_search_never_calls_yfinance(self):
        with patch("services.tickers.get_price_series") as series, \
             patch("services.tickers.get_stock_info") as info:
            search_tickers("NV")

        series.assert_not_called()
        info.assert_not_called()

    def test_an_unreachable_supabase_finds_nothing_rather_than_failing(self):
        with patch("services.tickers.get_client_optional", return_value=None):
            self.assertEqual(search_tickers("NV"), [])


# ── Resolution ───────────────────────────────────────────────────────────────

class ResolveTrackedTests(_Fixture):
    def test_a_tracked_stock_resolves_from_the_database_alone(self):
        with patch("services.tickers.get_price_series") as series:
            resolved = resolve_ticker("nvda")

        series.assert_not_called()
        self.assertEqual(resolved["symbol"], "NVDA")
        self.assertTrue(resolved["tracked"])
        self.assertEqual(resolved["kind"], "stock")
        self.assertEqual(resolved["firstDate"], "1999-01-01")

    def test_a_tracked_etf_falls_back_to_live_history_for_its_first_date(self):
        """`prices.ticker` references `ticker.id` and ETFs live in `etfs`,
        so a tracked fund has no price rows of its own - the earliest date
        has to come from upstream, and it is still a tracked result."""
        with patch("services.tickers.get_price_series",
                   return_value=[{"date": "1993-01-29", "close": 25.0}]) as series:
            resolved = resolve_ticker("SMH")

        series.assert_called_once_with("SMH", period="max")
        self.assertTrue(resolved["tracked"])
        self.assertEqual(resolved["kind"], "etf")
        self.assertEqual(resolved["firstDate"], "1993-01-29")

    def test_a_resolution_is_cached(self):
        with patch("services.tickers.get_price_series",
                   return_value=[{"date": "1993-01-29", "close": 25.0}]) as series:
            resolve_ticker("SMH")
            resolve_ticker("SMH")

        series.assert_called_once()


class ResolveUntrackedTests(_Fixture):
    def test_a_real_untracked_symbol_resolves_live_and_reports_its_first_close(self):
        history = [{"date": "2004-08-19", "close": 2.5}, {"date": "2004-08-20", "close": 2.6}]
        with patch("services.tickers.get_price_series", return_value=history), \
             patch("services.tickers.get_stock_info",
                   return_value={"name": "Alphabet Inc.", "sector": "Communication Services",
                                 "sectorTag": "COMMS", "logo": "goog.png"}):
            resolved = resolve_ticker("GOOG")

        self.assertFalse(resolved["tracked"])
        self.assertEqual(resolved["name"], "Alphabet Inc.")
        self.assertEqual(resolved["firstDate"], "2004-08-19")
        # Nothing in a live lookup says whether this is a fund or a company.
        self.assertIsNone(resolved["kind"])

    def test_a_symbol_with_no_history_is_not_found_and_is_named(self):
        """The check is history, not a name: yfinance answers a made-up
        ticker's info request with a shell dict, so a name proves nothing."""
        with patch("services.tickers.get_price_series", return_value=[]):
            with self.assertRaises(Exception) as ctx:
                resolve_ticker("ZZZZ")

        self.assertIn("ZZZZ", str(ctx.exception))

    def test_an_upstream_outage_is_not_a_missing_symbol(self):
        """The distinction the frontend acts on: it retries a 503 forever
        and never retries a 404."""
        with patch("services.tickers.get_price_series",
                   side_effect=DataUnavailable("upstream is down")):
            with self.assertRaises(DataUnavailable):
                resolve_ticker("GOOG")

    def test_a_failed_resolution_is_not_cached(self):
        with patch("services.tickers.get_price_series",
                   side_effect=DataUnavailable("upstream is down")):
            with self.assertRaises(DataUnavailable):
                resolve_ticker("GOOG")

        history = [{"date": "2004-08-19", "close": 2.5}]
        with patch("services.tickers.get_price_series", return_value=history), \
             patch("services.tickers.get_stock_info", return_value={"name": "Alphabet Inc."}):
            self.assertEqual(resolve_ticker("GOOG")["firstDate"], "2004-08-19")

    def test_something_that_is_not_a_symbol_is_rejected_before_asking_upstream(self):
        with patch("services.tickers.get_price_series") as series:
            for candidate in ("", "  ", "WAY-TOO-LONG-SYMBOL", "AB CD", "../etc"):
                with self.subTest(candidate=candidate):
                    with self.assertRaises(ValueError):
                        resolve_ticker(candidate)

        series.assert_not_called()


# ── The endpoints ────────────────────────────────────────────────────────────

class TickerRouteTests(_Fixture):
    def test_search_is_not_swallowed_by_the_symbol_route(self):
        """/tickers/search would be read as a symbol called "search" if the
        routes were declared the other way round - it answers with a list,
        not with a resolution."""
        resp = client.get("/api/tickers/search?q=NV")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r["symbol"] for r in resp.json()], ["NVDA", "NVS", "ENVX"])

    def test_the_limit_is_a_query_parameter(self):
        resp = client.get("/api/tickers/search?q=&limit=3")

        self.assertEqual(len(resp.json()), 3)

    def test_resolving_a_tracked_symbol(self):
        resp = client.get("/api/tickers/nvda")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["symbol"], "NVDA")
        self.assertEqual(resp.json()["firstDate"], "1999-01-01")

    def test_an_unknown_symbol_is_a_404_naming_it(self):
        with patch("services.tickers.get_price_series", return_value=[]):
            resp = client.get("/api/tickers/ZZZZ")

        self.assertEqual(resp.status_code, 404)
        self.assertIn("ZZZZ", resp.json()["detail"])

    def test_an_outage_is_a_retryable_503(self):
        with patch("services.tickers.get_price_series",
                   side_effect=DataUnavailable("upstream is down")):
            resp = client.get("/api/tickers/GOOG")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.headers.get("Retry-After"), "3")

    def test_something_that_is_not_a_symbol_is_a_400(self):
        resp = client.get("/api/tickers/WAY-TOO-LONG-SYMBOL")

        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
