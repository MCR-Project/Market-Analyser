"""
Tests for the Deep-fill (issue #171, docs/adr/0006-deep-fill-writes-nothing-to-the-database.md):
fetching a fund's Untracked holdings from yfinance on request, holding them in
the backend's memory for a while, and letting every read of that fund see them.

Three seams, each tested from outside:

- `services.deep_fill` - start, cancel and status of the one background job, and
  what the in-memory cache does with what it fetched (reuse across funds, resume
  after a cancel, expiry, oldest-first eviction).
- The HTTP endpoints, through a TestClient, because the status codes are a
  contract with the frontend's retry logic (backend/CLAUDE.md, "Errors are the API").
- The reads a deep-filled fund changes: its holdings, Fund Index figures,
  correlation matrix, sector breakdown and measurements - and, as importantly,
  that they go back to exactly the answer they gave before once the Deep-fill
  has expired.

Nothing here touches the network. yfinance's `download` is replaced by a fake
that records what it was asked for, and Supabase by an in-memory double that is
**write-hostile**: any insert, upsert, update or delete raises, and the test that
ends the run asserts none was attempted. That is the ADR's whole claim - a
Deep-fill writes nothing - so it is checked on every path, not once.

The background job really runs on its own thread; `manager.join()` waits for it,
and a fake clock stands in for time so expiry needs no sleeping.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import os
import sys
import threading
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from yfinance.exceptions import YFRateLimitError

from main import app
from rate_limit import FixedWindowLimiter
from services import deep_fill, deep_fill_store
from services.cache import TTLCache
from services.market_data import DataUnavailable, _RateLimitCooldown

client = TestClient(app, raise_server_exceptions=False)


# ── Doubles ───────────────────────────────────────────────────────────────────

class _Query:
    """One fluent read against an in-memory table. Applies `.eq`, `.in_`,
    `.gte`/`.lte`, `.order` and `.range` - enough that a reader which forgets
    `.eq("tracked", True)` or a window bound fails here - and refuses every write."""

    def __init__(self, db, name):
        self._db, self._name = db, name
        self._filters, self._orders = [], []
        self._start, self._end, self._limit = 0, None, None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters.append(lambda row: row.get(col) == val)
        return self

    def in_(self, col, vals):
        self._filters.append(lambda row: row.get(col) in vals)
        return self

    def gte(self, col, val):
        self._filters.append(lambda row: row.get(col) >= val)
        return self

    def lte(self, col, val):
        self._filters.append(lambda row: row.get(col) <= val)
        return self

    def order(self, col, desc=False):
        self._orders.append((col, desc))
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _refuse(self, *a, **k):
        self._db.write_attempts.append(self._name)
        raise AssertionError(f"a Deep-fill must write nothing, but {self._name} was written")

    insert = upsert = update = delete = _refuse

    def execute(self):
        rows = [r for r in self._db.tables.get(self._name, []) if all(f(r) for f in self._filters)]
        for col, desc in reversed(self._orders):
            rows.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._end is not None:
            rows = rows[self._start: self._end + 1]
        return SimpleNamespace(data=[dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables
        self.write_attempts = []
        self.reads = []         # every table asked for, in order

    def table(self, name):
        self.reads.append(name)
        return _Query(self, name)


def _business_days(n=60):
    end = date.today() - timedelta(days=1)
    return list(pd.bdate_range(end=end, periods=n).date)


def _walk(symbol, n):
    """A deterministic random walk per symbol, so two symbols are unrelated
    and one symbol is the same every time it is asked for."""
    rng = np.random.RandomState(sum(map(ord, symbol)))
    return 100 * np.cumprod(1 + rng.normal(0, 0.01, n))


def _price_rows(symbol):
    days = _business_days()
    closes = _walk(symbol, len(days))
    return [
        {"ticker": symbol, "date": d.isoformat(), "open": c, "high": c, "low": c,
         "close": float(c), "volume": 1000, "granularity": "D"}
        for d, c in zip(days, closes)
    ]


def make_db(funds=None, extra_tables=None):
    """A database holding the funds' holdings (tracked rows with prices and a
    `ticker` row, untracked rows with a weight and metadata) and nothing else.

    `funds` is {etf_id: {"tracked": [(symbol, weight)], "untracked": [(symbol, weight)]}}.
    """
    funds = funds or {
        "FAKE": {
            "tracked": [("AAA", 30.0), ("BBB", 20.0)],
            "untracked": [("U1", 0.5), ("U2", 0.5), ("U3", 0.5), ("U4", 0.5), ("U5", 0.5), ("U6", 0.5)],
        }
    }
    tables = {"etfs": [], "etf_holdings": [], "ticker": [], "prices": [], "untracked_metadata": []}
    seen = set()
    for etf_id, parts in funds.items():
        tables["etfs"].append({"id": etf_id, "name": f"{etf_id} fund", "cat": "Test", "desc": ""})
        for symbol, weight in parts["tracked"]:
            tables["etf_holdings"].append({"etf_id": etf_id, "ticker": symbol, "weight": weight, "tracked": True})
            if symbol not in seen:
                seen.add(symbol)
                tables["ticker"].append({"id": symbol, "name": symbol, "sector": "Technology",
                                         "market_cap": 1e9, "currency": "USD", "exchange": "X",
                                         "logo": "", "website": ""})
                tables["prices"].extend(_price_rows(symbol))
        for symbol, weight in parts["untracked"]:
            tables["etf_holdings"].append({"etf_id": etf_id, "ticker": symbol, "weight": weight, "tracked": False})
            if symbol not in seen:
                seen.add(symbol)
                tables["untracked_metadata"].append({
                    "id": symbol, "name": f"{symbol} Inc", "sector": "Energy", "market_cap": 5e8,
                    "currency": "USD", "exchange": "X", "logo": "", "website": "", "failure": None,
                })
    tables.update(extra_tables or {})
    return FakeSupabase(tables)


class FakeYahoo:
    """Stands in for `yf.download`. Answers a MultiIndex frame grouped by
    ticker, one year-ish of daily rows per symbol it knows, and records every
    call so a test can say what was fetched and in what batches."""

    def __init__(self, missing=(), hook=None, fail=None):
        self.calls = []        # one list of symbols per call
        self.kwargs = []
        self.missing = set(missing)
        self.hook = hook       # called with the symbols, before answering
        self.fail = fail       # an exception to raise instead of answering

    @property
    def fetched(self):
        return [s for call in self.calls for s in call]

    def download(self, tickers, **kwargs):
        symbols = [tickers] if isinstance(tickers, str) else list(tickers)
        self.calls.append(symbols)
        self.kwargs.append(kwargs)
        if self.hook:
            self.hook(symbols)
        if self.fail is not None:
            raise self.fail
        days = pd.to_datetime(_business_days())
        parts = {}
        for symbol in symbols:
            if symbol in self.missing:
                continue
            closes = _walk(symbol, len(days))
            frame = pd.DataFrame(
                {"Open": closes, "High": closes, "Low": closes, "Close": closes,
                 "Volume": 5000.0, "Dividends": 0.0, "Stock Splits": 0.0},
                index=days,
            )
            frame.loc[days[10], "Dividends"] = 0.25
            parts[symbol] = frame
        if not parts:
            return pd.DataFrame()
        return pd.concat(parts, axis=1)


class FakeClock:
    def __init__(self, start=None):
        # Real time, not a round number: a result's coverage is judged against
        # `date.today()`, so the clock the store reads has to agree with it.
        self.now = time.time() if start is None else start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class DeepFillCase(unittest.TestCase):
    """A fresh store, job manager, caches and cooldown for every test, the
    Deep-fill switched on with small batches, and the doubles installed."""

    ENV = {"ALLOW_DEEP_FILL": "true", "DEEP_FILL_BATCH_SIZE": "4",
           "DEEP_FILL_TTL_SECONDS": "3600", "DEEP_FILL_MAX_FUNDS": "3"}
    FUNDS = None  # a test class may override

    def setUp(self):
        self.db = make_db(self.FUNDS)
        self.yahoo = FakeYahoo()
        self.clock = FakeClock()
        self.manager = deep_fill.DeepFill()
        self.waits = []
        for target, value in (
            ("services.deep_fill_store.store", deep_fill_store.DeepFillStore()),
            ("services.deep_fill.manager", self.manager),
            ("services.deep_fill_store._now", self.clock),
            # A fresh limiter of our own: every TestClient shares one address, so
            # the dozens of /api calls here would otherwise spend the real bucket
            # the rest of the suite relies on (backend/CLAUDE.md, "Tests").
            ("rate_limit.general_limiter", FixedWindowLimiter(limit=100_000)),
            ("rate_limit.simulate_limiter", FixedWindowLimiter(limit=100_000)),
            ("services.market_data.cache", TTLCache()),
            ("services.fund_metrics.cache", TTLCache()),
            ("services.market_data._rate_limit_cooldown", _RateLimitCooldown()),
            ("services.market_data.get_client_optional", lambda: self.db),
            ("services.deep_fill.yf.download", self.yahoo.download),
            ("services.deep_fill._wait", self._wait),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, self.ENV)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.manager.join, 5)

    def _wait(self, event, seconds):
        """Replaces the interruptible sleep: records it, never actually sleeps,
        and reports whether the job was asked to stop meanwhile."""
        self.waits.append(seconds)
        return event.is_set()

    def run_job(self, etf_id="FAKE"):
        status = deep_fill.start(etf_id)
        self.manager.join(10)
        return status, deep_fill.status(etf_id)

    def assertNothingWritten(self):
        self.assertEqual(self.db.write_attempts, [])


# ── The job ───────────────────────────────────────────────────────────────────

class RefusalTests(DeepFillCase):
    def test_start_is_refused_and_nothing_is_fetched_while_disabled(self):
        with patch.dict(os.environ, {"ALLOW_DEEP_FILL": "false"}):
            with self.assertRaises(deep_fill.DeepFillDisabled):
                deep_fill.start("FAKE")
            self.manager.join(1)
        self.assertEqual(self.yahoo.calls, [])
        self.assertNothingWritten()

    def test_status_still_answers_while_disabled_and_says_so(self):
        with patch.dict(os.environ, {"ALLOW_DEEP_FILL": "false"}):
            status = deep_fill.status("FAKE")
        self.assertFalse(status["enabled"])
        self.assertEqual(status["state"], "idle")
        self.assertEqual(status["untracked"]["count"], 6)


class CompletionTests(DeepFillCase):
    def test_the_job_runs_to_completion_and_status_reports_it(self):
        started, status = self.run_job()

        self.assertEqual(started["state"], "running")
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["progress"], {"done": 6, "total": 6, "failed": []})
        self.assertEqual(status["untracked"]["count"], 6)
        self.assertEqual(status["untracked"]["weight"], 3.0)
        # 3.0 of the fund's 53.0 listed weight
        self.assertAlmostEqual(status["untracked"]["weightShare"], 5.66, places=2)
        self.assertIsNotNone(status["asOf"])
        self.assertIsNotNone(status["expiresAt"])
        self.assertNothingWritten()

    def test_tickers_are_fetched_in_batches_of_the_configured_size(self):
        self.run_job()

        self.assertEqual([len(c) for c in self.yahoo.calls], [4, 2])
        self.assertEqual(sorted(self.yahoo.fetched), ["U1", "U2", "U3", "U4", "U5", "U6"])

    def test_prices_are_asked_for_adjusted_with_a_year_of_daily_history(self):
        self.run_job()

        for kwargs in self.yahoo.kwargs:
            self.assertIs(kwargs["auto_adjust"], True)
            self.assertEqual(kwargs["period"], "1y")
            self.assertEqual(kwargs["interval"], "1d")
            self.assertIs(kwargs["actions"], True)


class FailureTests(DeepFillCase):
    def test_a_ticker_with_no_history_is_named_with_a_reason_and_the_job_carries_on(self):
        self.yahoo.missing = {"U3"}

        _, status = self.run_job()

        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["progress"]["done"], 6)
        self.assertEqual([f["ticker"] for f in status["progress"]["failed"]], ["U3"])
        self.assertIn("no price history", status["progress"]["failed"][0]["reason"])

    def test_an_upstream_that_stays_down_ends_the_job_failed_and_keeps_what_was_fetched(self):
        calls = {"n": 0}

        def flaky(symbols):
            calls["n"] += 1
            if calls["n"] > 1:        # the first batch is fine, then Yahoo goes away
                raise ConnectionError("connection refused")

        self.yahoo.hook = flaky
        _, status = self.run_job()

        self.assertEqual(status["state"], "failed")
        self.assertIn("could not be reached", status["error"])
        self.assertEqual(status["progress"]["done"], 4)
        self.assertNothingWritten()

        # Pressing again resumes: only the two tickers the failed batch held.
        self.yahoo.hook = None
        self.yahoo.calls.clear()
        _, resumed = self.run_job()
        self.assertEqual(sorted(self.yahoo.fetched), ["U5", "U6"])
        self.assertEqual(resumed["state"], "ready")

    def test_a_share_class_is_asked_for_in_yahoos_spelling_and_kept_under_the_repos(self):
        self.db = make_db({"FAKE": {"tracked": [("AAA", 30.0), ("BBB", 20.0)],
                                    "untracked": [("BRK.B", 0.5), ("U2", 0.5)]}})

        _, status = self.run_job()

        self.assertEqual(sorted(self.yahoo.fetched), ["BRK-B", "U2"])
        self.assertEqual(status["progress"]["failed"], [])
        self.assertIsNotNone(deep_fill_store.store.ticker("BRK.B"))

    def test_a_symbol_empty_under_the_dashed_spelling_is_asked_again_as_written(self):
        self.db = make_db({"FAKE": {"tracked": [("AAA", 30.0), ("BBB", 20.0)],
                                    "untracked": [("ABC.L", 0.5), ("U2", 0.5)]}})
        self.yahoo.missing = {"ABC-L"}          # yfinance only knows the dotted listing

        _, status = self.run_job()

        self.assertEqual(self.yahoo.calls[-1], ["ABC.L"])
        self.assertEqual(status["progress"]["failed"], [])


class RateLimitTests(DeepFillCase):
    def test_a_running_cooldown_is_waited_out_before_anything_is_fetched(self):
        cooldown = _RateLimitCooldown(duration=60)
        cooldown.start()

        def clear(event, seconds):
            self.waits.append(seconds)
            cooldown._until = 0.0
            return False

        with patch("services.market_data._rate_limit_cooldown", cooldown), \
                patch("services.deep_fill._wait", clear):
            _, status = self.run_job()

        self.assertEqual(status["state"], "ready")
        self.assertEqual(len(self.waits), 1)
        self.assertGreaterEqual(self.waits[0], 1)

    def test_a_429_starts_the_cooldown_and_the_batch_is_retried_after_it(self):
        cooldown = _RateLimitCooldown(duration=60)
        outcomes = [YFRateLimitError()]

        def limited(symbols):
            if outcomes:
                raise outcomes.pop()

        def clear(event, seconds):
            self.waits.append(seconds)
            cooldown._until = 0.0
            return False

        self.yahoo.hook = limited
        with patch("services.market_data._rate_limit_cooldown", cooldown), \
                patch("services.deep_fill._wait", clear):
            _, status = self.run_job()

        self.assertEqual(status["state"], "ready")
        self.assertEqual(self.yahoo.calls[0], self.yahoo.calls[1])    # the same batch, twice
        self.assertGreaterEqual(self.waits[0], 1)


class CancelAndResumeTests(DeepFillCase):
    def test_cancel_keeps_what_was_fetched_and_start_fetches_only_what_is_missing(self):
        def cancel_during_first_batch(symbols):
            if len(self.yahoo.calls) == 1:
                deep_fill.cancel("FAKE")

        self.yahoo.hook = cancel_during_first_batch
        _, cancelled = self.run_job()

        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(cancelled["progress"]["done"], 4)
        self.assertEqual(len(self.yahoo.calls), 1)

        self.yahoo.hook = None
        self.yahoo.calls.clear()
        _, resumed = self.run_job()

        self.assertEqual(sorted(self.yahoo.fetched), ["U5", "U6"])
        self.assertEqual(resumed["state"], "ready")
        self.assertEqual(resumed["progress"], {"done": 6, "total": 6, "failed": []})
        self.assertNothingWritten()

    def test_cancelling_when_nothing_runs_only_reports_the_status(self):
        status = deep_fill.cancel("FAKE")

        self.assertEqual(status["state"], "idle")
        self.assertEqual(self.yahoo.calls, [])


class OneJobAtATimeTests(DeepFillCase):
    FUNDS = {
        "FAKE": {"tracked": [("AAA", 30.0), ("BBB", 20.0)],
                 "untracked": [("U1", 0.5), ("U2", 0.5), ("U3", 0.5), ("U4", 0.5), ("U5", 0.5), ("U6", 0.5)]},
        "OTHER": {"tracked": [("AAA", 30.0), ("BBB", 20.0)],
                  "untracked": [("U1", 0.5), ("U2", 0.5), ("U3", 0.5), ("V1", 0.5)]},
    }

    def _hold_the_first_batch(self):
        entered, release = threading.Event(), threading.Event()

        def block(symbols):
            entered.set()
            release.wait(5)

        self.yahoo.hook = block
        self.addCleanup(release.set)
        return entered, release

    def test_pressing_for_another_fund_is_refused_with_the_running_jobs_progress(self):
        entered, release = self._hold_the_first_batch()
        deep_fill.start("FAKE")
        entered.wait(5)

        with self.assertRaises(deep_fill.DeepFillBusy) as caught:
            deep_fill.start("OTHER")

        self.assertEqual(caught.exception.status["etfId"], "FAKE")
        self.assertEqual(caught.exception.status["state"], "running")
        self.assertEqual(deep_fill.status("OTHER")["running"], {"etfId": "FAKE", "done": 0, "total": 6})
        release.set()

    def test_pressing_again_for_the_running_fund_attaches_instead_of_starting_a_second_job(self):
        entered, release = self._hold_the_first_batch()
        deep_fill.start("FAKE")
        entered.wait(5)

        again = deep_fill.start("FAKE")
        release.set()
        self.manager.join(10)

        self.assertEqual(again["state"], "running")
        self.assertEqual([len(c) for c in self.yahoo.calls], [4, 2])    # one job's worth, not two

    def test_pressing_for_a_cancelled_but_still_running_fund_withdraws_the_cancel(self):
        entered, release = self._hold_the_first_batch()
        deep_fill.start("FAKE")
        entered.wait(5)
        self.assertTrue(deep_fill.cancel("FAKE")["cancelRequested"])

        resumed = deep_fill.start("FAKE")
        release.set()
        self.manager.join(10)

        self.assertFalse(resumed["cancelRequested"])
        self.assertEqual(deep_fill.status("FAKE")["state"], "ready")

    def test_a_second_fund_sharing_tickers_fetches_only_the_ones_not_already_held(self):
        self.run_job("FAKE")
        self.yahoo.calls.clear()

        _, status = self.run_job("OTHER")

        self.assertEqual(self.yahoo.fetched, ["V1"])
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["progress"]["done"], 4)


class LifetimeTests(DeepFillCase):
    FUNDS = OneJobAtATimeTests.FUNDS

    def test_after_the_ttl_the_fund_is_no_longer_deep_filled_and_its_tickers_are_gone(self):
        _, ready = self.run_job()
        self.assertEqual(ready["state"], "ready")

        self.clock.advance(3601)

        status = deep_fill.status("FAKE")
        self.assertEqual(status["state"], "idle")
        self.assertIsNone(status["asOf"])
        self.assertIsNone(deep_fill_store.store.ticker("U1"))

        # ...so pressing again pays for all of it again.
        self.yahoo.calls.clear()
        self.run_job()
        self.assertEqual(len(self.yahoo.fetched), 6)

    def test_expiry_is_the_oldest_ticker_the_result_was_built_from_plus_the_ttl(self):
        deep_fill.start("FAKE")
        self.manager.join(10)
        first = deep_fill.status("FAKE")["expiresAt"]

        self.clock.advance(1800)
        self.run_job("OTHER")                    # reuses the first fund's tickers, fetches V1

        # OTHER was built partly from data fetched half an hour ago, so it
        # does not outlive FAKE's data by the time it was built.
        self.assertEqual(deep_fill.status("OTHER")["expiresAt"], first)

    def test_holding_more_funds_than_the_limit_evicts_the_one_finished_longest_ago(self):
        with patch.dict(os.environ, {"DEEP_FILL_MAX_FUNDS": "1"}):
            self.run_job("FAKE")
            self.clock.advance(10)
            self.run_job("OTHER")

        self.assertEqual(deep_fill.status("FAKE")["state"], "idle")
        self.assertEqual(deep_fill.status("OTHER")["state"], "ready")
        # a ticker only the evicted fund used goes with it; a shared one stays
        self.assertIsNone(deep_fill_store.store.ticker("U5"))
        self.assertIsNotNone(deep_fill_store.store.ticker("U1"))


class StartRefusalTests(DeepFillCase):
    def test_a_fund_with_nothing_untracked_is_refused(self):
        self.db = make_db({"FAKE": {"tracked": [("AAA", 30.0), ("BBB", 20.0)], "untracked": []}})
        with self.assertRaises(ValueError):
            deep_fill.start("FAKE")
        self.assertEqual(self.yahoo.calls, [])

    def test_a_fund_with_more_untracked_holdings_than_memory_allows_is_refused(self):
        with patch("services.deep_fill.DEEP_FILL_MAX_UNTRACKED", 5):
            with self.assertRaises(ValueError) as caught:
                deep_fill.start("FAKE")
        self.assertIn("memory", str(caught.exception))
        self.assertEqual(self.yahoo.calls, [])

    def test_a_database_that_cannot_be_read_is_a_503_not_an_empty_fund(self):
        class Broken(FakeSupabase):
            def table(self, name):
                raise ConnectionError("down")

        self.db = Broken({})
        with self.assertRaises(DataUnavailable):
            deep_fill.start("FAKE")

    def test_a_result_still_held_is_answered_ready_and_nothing_is_fetched_again(self):
        self.run_job()
        self.yahoo.calls.clear()

        again = deep_fill.start("FAKE")

        self.assertEqual(again["state"], "ready")
        self.assertEqual(self.yahoo.calls, [])


# ── What a deep-filled fund reads ─────────────────────────────────────────────

class ReadCase(DeepFillCase):
    """The doubles of DeepFillCase plus a guard: a Deep-fill read that reaches
    yfinance for anything but the job's own batched download has gone live for
    ~450 tickers from inside a request."""

    TAIL = ["U1", "U2", "U3", "U4", "U5", "U6"]

    def setUp(self):
        super().setUp()
        patcher = patch("services.market_data.yf.Ticker", side_effect=AssertionError("went live"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, path):
        response = client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assertNoLiveReads(self, since):
        self.assertEqual(len(self.yahoo.calls), since, "a read went to yfinance")


class HoldingsTests(ReadCase):
    def test_a_deep_filled_fund_lists_its_untracked_holdings_after_the_tracked_ones(self):
        before = self.get("/api/etf/FAKE")
        self.assertEqual([h[0] for h in before["holdings"]], ["AAA", "BBB"])
        self.assertNotIn("untracked", before)

        self.run_job()
        after = self.get("/api/etf/FAKE")

        self.assertEqual([h[0] for h in after["holdings"]], ["AAA", "BBB"] + self.TAIL)
        self.assertEqual(after["holdings"][2], ["U1", 0.5])
        self.assertEqual(after["untracked"], self.TAIL)
        self.assertEqual(after["deepFill"]["asOf"], deep_fill.status("FAKE")["asOf"])
        self.assertFalse(after["stale"])

    def test_after_the_ttl_the_holdings_are_exactly_what_they_were_before(self):
        before = self.get("/api/etf/FAKE")
        self.run_job()
        self.clock.advance(3601)

        self.assertEqual(self.get("/api/etf/FAKE"), before)
        self.assertNothingWritten()


class CorrelationTests(ReadCase):
    def test_the_matrix_includes_the_tail_without_going_live_for_it(self):
        before = self.get("/api/correlation/FAKE")
        self.assertEqual(before["tickers"], ["AAA", "BBB"])

        self.run_job()
        fetched = len(self.yahoo.calls)
        after = self.get("/api/correlation/FAKE")

        self.assertEqual(after["tickers"], ["AAA", "BBB"] + self.TAIL)
        self.assertEqual(len(after["matrix"]["U1"]), 8)
        self.assertIsNotNone(after["matrix"]["U1"]["AAA"])
        self.assertEqual(after["deepFill"]["excluded"], {})
        self.assertNoLiveReads(fetched)

    def test_it_is_the_result_the_deep_fill_finished_with_not_computed_again(self):
        self.run_job()
        expected = self.get("/api/correlation/FAKE")
        market_data_cache = TTLCache()

        with patch("services.market_data.cache", market_data_cache), \
                patch("services.market_data._price_frame_bundle", side_effect=AssertionError("recomputed")):
            again = self.get("/api/correlation/FAKE")
            self.assertEqual(again["matrix"], expected["matrix"])
            self.assertEqual(again["clusters"], expected["clusters"])
            # the cached /etf/ holdings read still has to work with the cache emptied
            self.assertEqual(again["deepFill"]["asOf"], deep_fill.status("FAKE")["asOf"])

    def test_a_window_longer_than_the_fetched_year_leaves_the_tail_out_and_says_why(self):
        self.run_job()
        fetched = len(self.yahoo.calls)

        result = self.get("/api/correlation/FAKE?period=5y")

        self.assertEqual(result["tickers"], ["AAA", "BBB"])
        self.assertEqual(sorted(result["deepFill"]["excluded"]), self.TAIL)
        self.assertIn("one year", result["deepFill"]["excluded"]["U1"])
        self.assertNoLiveReads(fetched)

    def test_a_ticker_the_job_could_not_fetch_is_excluded_by_name_with_its_reason(self):
        self.yahoo.missing = {"U3"}
        self.run_job()

        result = self.get("/api/correlation/FAKE")

        self.assertNotIn("U3", result["tickers"])
        self.assertIn("no price history", result["deepFill"]["excluded"]["U3"])

    def test_after_the_ttl_the_matrix_is_exactly_the_pruned_one_again(self):
        before = self.get("/api/correlation/FAKE")
        self.run_job()
        self.get("/api/correlation/FAKE")
        self.clock.advance(3601)

        self.assertEqual(self.get("/api/correlation/FAKE"), before)


class FundMetricsTests(ReadCase):
    def metrics(self):
        from services.fund_metrics import compute_fund_metrics
        return compute_fund_metrics("FAKE")

    def test_a_pruned_answer_is_never_served_for_a_deep_filled_fund_or_the_reverse(self):
        pruned = self.metrics()
        self.assertEqual(pruned["trackedWeightCoverage"], 50.0)
        self.assertNotIn("deepFill", pruned)

        self.run_job()
        deep = self.metrics()
        self.assertEqual(deep["trackedWeightCoverage"], 53.0)
        self.assertEqual(deep["deepFill"]["untrackedWeight"], 3.0)
        self.assertEqual(deep["deepFill"]["withoutHistory"], {})
        self.assertNotEqual(deep["diversificationRatio"], pruned["diversificationRatio"])

        self.clock.advance(3601)
        self.assertEqual(self.metrics(), pruned)

    def test_a_holding_the_fetch_could_not_support_is_named_and_not_counted_as_covered(self):
        self.yahoo.missing = {"U3"}
        self.run_job()

        deep = self.metrics()

        self.assertEqual(deep["trackedWeightCoverage"], 52.5)
        self.assertEqual(sorted(deep["deepFill"]["withoutHistory"]), ["U3"])
        self.assertIn("no price history", deep["deepFill"]["withoutHistory"]["U3"])


class SectorTests(ReadCase):
    def test_the_breakdown_counts_the_tail_from_its_stored_metadata_not_a_live_lookup(self):
        before = self.get("/api/sectors/FAKE")
        self.assertEqual([s["name"] for s in before["sectors"]], ["Technology"])

        self.run_job()
        after = self.get("/api/sectors/FAKE")

        by_name = {s["name"]: s for s in after["sectors"]}
        self.assertEqual(by_name["Technology"]["weight"], 50.0)
        self.assertEqual(by_name["Energy"]["weight"], 3.0)
        self.assertEqual(by_name["Energy"]["count"], 6)

        self.clock.advance(3601)
        self.assertEqual(self.get("/api/sectors/FAKE"), before)

    def test_a_tail_holding_with_no_stored_metadata_is_unknown_not_looked_up(self):
        self.db.tables["untracked_metadata"] = [
            r for r in self.db.tables["untracked_metadata"] if r["id"] != "U2"
        ]
        self.run_job()

        after = self.get("/api/sectors/FAKE")

        by_name = {s["name"]: s for s in after["sectors"]}
        self.assertEqual(by_name["Unknown"]["count"], 1)
        self.assertEqual(by_name["Energy"]["count"], 5)


class StockBatchTests(ReadCase):
    def test_the_batch_describes_the_tail_from_stored_metadata_not_a_live_lookup(self):
        # The Table tab asks /api/stocks for every holding the fund lists, which
        # once deep-filled is ~450 Untracked ones (issue #172). `ReadCase` makes
        # any live yfinance read raise, so this passing means none was made.
        self.run_job()

        rows = self.get("/api/stocks?tickers=U1,U2,U3")

        self.assertEqual([r["ticker"] for r in rows], ["U1", "U2", "U3"])
        self.assertTrue(all(r["sector"] == "Energy" for r in rows))

    def test_a_tail_holding_with_nothing_stored_is_unknown_with_a_reason(self):
        self.db.tables["untracked_metadata"] = [
            r for r in self.db.tables["untracked_metadata"] if r["id"] != "U2"
        ]
        self.run_job()

        rows = {r["ticker"]: r for r in self.get("/api/stocks?tickers=U1,U2")}

        self.assertEqual(rows["U2"]["sector"], "Unknown")
        self.assertIsNone(rows["U2"]["name"])
        self.assertTrue(rows["U2"]["reason"])


class MeasurementTests(ReadCase):
    def column(self, path):
        return self.get(path)

    def test_a_window_measurement_reads_the_tail(self):
        self.run_job()
        fetched = len(self.yahoo.calls)

        result = self.column("/api/measurements/volatility/FAKE?window=1y")

        for ticker in self.TAIL:
            self.assertIsNotNone(result["per_ticker"][ticker], ticker)
        self.assertNoLiveReads(fetched)

    def test_beyond_the_fetched_year_the_tail_is_null_with_the_reason_and_the_tracked_part_is_not(self):
        self.run_job()

        result = self.column("/api/measurements/volatility/FAKE?window=5y")

        self.assertIsNotNone(result["per_ticker"]["AAA"])
        for ticker in self.TAIL:
            self.assertIsNone(result["per_ticker"][ticker])
            self.assertIn("one year", result["per_ticker_reason"][ticker])

    def test_a_ticker_that_failed_to_fetch_is_null_with_the_failure_as_its_reason(self):
        self.yahoo.missing = {"U3"}
        self.run_job()

        result = self.column("/api/measurements/volatility/FAKE?window=1y")

        self.assertIsNone(result["per_ticker"]["U3"])
        self.assertIn("no price history", result["per_ticker_reason"]["U3"])
        self.assertIsNotNone(result["per_ticker"]["U4"])

    def test_market_cap_comes_from_the_stored_metadata(self):
        self.run_job()

        result = self.column("/api/measurements/market-cap/FAKE")

        self.assertEqual(result["per_ticker"]["U1"], 0.5)

    def test_dividend_yield_uses_the_dividends_that_were_fetched(self):
        self.run_job()

        result = self.column("/api/measurements/dividend-income/FAKE")

        last_close = float(_walk("U1", 60)[-1])
        self.assertAlmostEqual(result["per_ticker"]["dividend_yield"]["U1"], 0.25 / last_close * 100, places=1)

    def test_the_fund_index_is_built_with_the_tail_in_it(self):
        from measurements.inputs.fund_index import get_fund_index

        self.run_job()
        weights = {"AAA": 30.0, "BBB": 20.0, **{t: 0.5 for t in self.TAIL}}

        index = get_fund_index(list(weights), weights)

        self.assertEqual(sorted(index["values_by_ticker"]), sorted(weights))
        self.assertIsNotNone(index["fund_values"])

    def test_after_the_ttl_a_measurement_answers_exactly_as_it_did_before(self):
        before = self.column("/api/measurements/volatility/FAKE?window=1y")
        self.run_job()
        self.column("/api/measurements/volatility/FAKE?window=1y")
        self.clock.advance(3601)

        self.assertEqual(self.column("/api/measurements/volatility/FAKE?window=1y"), before)


# ── The endpoints ─────────────────────────────────────────────────────────────

class EndpointTests(DeepFillCase):
    """The status codes are a contract with the frontend's retry logic: a 4xx is
    never retried, a 429/5xx is retried on a backoff. Every refusal here is a 4xx,
    because none of them heals by asking again on a schedule."""

    FUNDS = OneJobAtATimeTests.FUNDS

    def test_status_of_a_fund_nothing_has_happened_to_is_a_200_idle(self):
        response = client.get("/api/deep-fill/fake")        # the ticker is upper-cased

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["etfId"], "FAKE")
        self.assertEqual(body["state"], "idle")
        self.assertTrue(body["enabled"])
        self.assertEqual(body["untracked"]["count"], 6)
        self.assertIsNone(body["progress"])
        self.assertIsNone(body["asOf"])

    def test_status_says_how_long_a_result_is_kept_before_there_is_one(self):
        # The warning dialog (issue #172) tells someone how long the fund will
        # stay deep-filled *before* they press start, so the figure cannot wait
        # for a result to carry an expiry. It follows the setting, and is there
        # while Deep-fill is off too, where the dialog does not offer it.
        self.assertEqual(client.get("/api/deep-fill/FAKE").json()["ttlSeconds"], 3600)
        with patch.dict(os.environ, {"DEEP_FILL_TTL_SECONDS": "120"}):
            self.assertEqual(client.get("/api/deep-fill/FAKE").json()["ttlSeconds"], 120)

    def test_starting_answers_202_while_running_and_200_once_it_is_done(self):
        entered, release = threading.Event(), threading.Event()
        self.yahoo.hook = lambda symbols: (entered.set(), release.wait(5))
        self.addCleanup(release.set)

        started = client.post("/api/deep-fill/FAKE")
        entered.wait(5)
        self.assertEqual(started.status_code, 202)
        self.assertEqual(started.json()["state"], "running")
        self.assertEqual(client.get("/api/deep-fill/FAKE").json()["state"], "running")

        release.set()
        self.manager.join(10)
        done = client.get("/api/deep-fill/FAKE")
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["state"], "ready")
        self.assertEqual(client.post("/api/deep-fill/FAKE").status_code, 200)   # nothing re-fetched
        self.assertNothingWritten()

    def test_disabled_is_a_403_that_fetches_nothing(self):
        with patch.dict(os.environ, {"ALLOW_DEEP_FILL": "false"}):
            response = client.post("/api/deep-fill/FAKE")

        self.assertEqual(response.status_code, 403)
        self.assertIn("switched off", response.json()["detail"])
        self.assertEqual(self.yahoo.calls, [])
        self.assertNothingWritten()

    def test_another_funds_job_running_is_a_409_carrying_its_progress(self):
        entered, release = threading.Event(), threading.Event()
        self.yahoo.hook = lambda symbols: (entered.set(), release.wait(5))
        self.addCleanup(release.set)
        client.post("/api/deep-fill/FAKE")
        entered.wait(5)

        response = client.post("/api/deep-fill/OTHER")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["running"]["etfId"], "FAKE")
        self.assertEqual(response.json()["running"]["state"], "running")
        release.set()

    def test_a_fund_with_nothing_to_fill_is_a_400(self):
        response = client.post("/api/deep-fill/NOSUCHFUND")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.yahoo.calls, [])

    def test_cancel_answers_the_status_and_stops_the_job(self):
        def cancel_during_first_batch(symbols):
            if len(self.yahoo.calls) == 1:
                client.post("/api/deep-fill/FAKE/cancel")

        self.yahoo.hook = cancel_during_first_batch
        client.post("/api/deep-fill/FAKE")
        self.manager.join(10)

        status = client.get("/api/deep-fill/FAKE").json()
        self.assertEqual(status["state"], "cancelled")
        self.assertEqual(status["progress"]["done"], 4)

    def test_cancel_with_nothing_running_is_a_200(self):
        response = client.post("/api/deep-fill/FAKE/cancel")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "idle")

    def test_a_database_that_cannot_be_read_is_a_retryable_503(self):
        class Broken(FakeSupabase):
            def table(self, name):
                raise ConnectionError("down")

        self.db = Broken({})

        for response in (client.get("/api/deep-fill/FAKE"), client.post("/api/deep-fill/FAKE")):
            self.assertEqual(response.status_code, 503)
            self.assertIn("Retry-After", response.headers)

    def test_no_database_configured_at_all_is_not_a_503(self):
        """With no Supabase there is no list of Untracked holdings to fetch, and
        asking again will not conjure one - so the status is an honest zero and a
        start is a 400, neither of which the frontend retries."""
        with patch("services.market_data.get_client_optional", lambda: None), \
                patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": ""}):
            status = client.get("/api/deep-fill/FAKE")
            started = client.post("/api/deep-fill/FAKE")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["untracked"]["count"], 0)
        self.assertEqual(started.status_code, 400)


# ── Found in review ───────────────────────────────────────────────────────────

class ThrottledBatchTests(DeepFillCase):
    """`yf.download` does not raise for a ticker it could not fetch - it logs the
    error, a rate limit included, and returns an empty frame - so a throttled batch
    looks like a batch of delisted symbols. These pin that it is not read as one."""

    def test_a_batch_that_comes_back_entirely_empty_is_waited_out_and_asked_again(self):
        first_batch = {"U1", "U2", "U3", "U4"}
        asked = {"n": 0}

        def throttle_first_ask(symbols):
            asked["n"] += 1
            self.yahoo.missing = first_batch if asked["n"] == 1 else set()

        self.yahoo.hook = throttle_first_ask
        _, status = self.run_job()

        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["progress"]["failed"], [])
        self.assertEqual(self.yahoo.calls[0], self.yahoo.calls[1])
        self.assertEqual(self.waits[0], 60)

    def test_a_batch_that_stays_empty_ends_the_job_failed_not_fifty_named_failures(self):
        self.yahoo.missing = {"U1", "U2", "U3", "U4", "U5", "U6"}

        _, status = self.run_job()

        self.assertEqual(status["state"], "failed")
        self.assertIn("rate limiting", status["error"])
        self.assertEqual(status["progress"]["failed"], [])
        self.assertEqual(len(self.yahoo.calls), 3)

    def test_one_missing_ticker_in_a_batch_that_otherwise_answered_is_just_that_ticker(self):
        self.yahoo.missing = {"U2"}

        _, status = self.run_job()

        self.assertEqual(status["state"], "ready")
        self.assertEqual([f["ticker"] for f in status["progress"]["failed"]], ["U2"])
        self.assertEqual(self.waits, [])


class SpellingCollisionTests(DeepFillCase):
    FUNDS = {"FAKE": {"tracked": [("AAA", 30.0), ("BBB", 20.0)],
                      "untracked": [("BRK.B", 0.5), ("BRK-B", 0.4), ("U3", 0.3)]}}

    def test_two_symbols_with_one_yahoo_spelling_are_both_accounted_for(self):
        _, status = self.run_job()

        self.assertEqual(status["progress"]["done"], 3)
        failed = {f["ticker"]: f["reason"] for f in status["progress"]["failed"]}
        self.assertEqual(list(failed), ["BRK-B"])
        self.assertIn("BRK.B", failed["BRK-B"])
        self.assertEqual(self.yahoo.fetched.count("BRK-B"), 1)


class StartOrderTests(DeepFillCase):
    FUNDS = OneJobAtATimeTests.FUNDS

    def test_a_fund_already_deep_filled_is_ready_even_while_another_funds_job_runs(self):
        self.run_job("FAKE")
        entered, release = threading.Event(), threading.Event()
        self.yahoo.hook = lambda symbols: (entered.set(), release.wait(5))
        self.addCleanup(release.set)
        deep_fill.start("OTHER")
        entered.wait(5)

        again = deep_fill.start("FAKE")

        self.assertEqual(again["state"], "ready")
        release.set()


class NoWaitingUnderTheLockTests(DeepFillCase):
    def test_a_slow_status_read_for_another_fund_does_not_freeze_the_jobs_progress(self):
        self.db = make_db({
            "FAKE": self.FUNDS_FAKE, "IDLE": {"tracked": [("AAA", 30.0)], "untracked": [("Z1", 0.5)]},
        })
        entered, release = threading.Event(), threading.Event()
        batch_one_held = threading.Event()
        self.yahoo.hook = lambda symbols: batch_one_held.wait(5)
        self.addCleanup(batch_one_held.set)
        self.addCleanup(release.set)
        deep_fill.start("FAKE")

        from services import market_data as md
        real = md.get_untracked_holdings

        def slow(etf_id):
            if etf_id == "IDLE":
                entered.set()
                release.wait(5)
            return real(etf_id)

        poll = threading.Thread(target=lambda: deep_fill.status("IDLE"), daemon=True)
        with patch("services.market_data.get_untracked_holdings", slow):
            poll.start()
            entered.wait(5)
            batch_one_held.set()                     # the job can now make progress
            deadline = time.time() + 3
            while time.time() < deadline and self.manager._job.done < 6:
                time.sleep(0.01)
            progressed = self.manager._job.done
            release.set()
            poll.join(5)

        self.assertEqual(progressed, 6, "the job was blocked behind a status read")

    FUNDS_FAKE = {"tracked": [("AAA", 30.0), ("BBB", 20.0)],
                  "untracked": [("U1", 0.5), ("U2", 0.5), ("U3", 0.5), ("U4", 0.5), ("U5", 0.5), ("U6", 0.5)]}


class ReviewReadTests(ReadCase):
    def test_a_tail_holdings_missing_description_keeps_its_own_reason_not_a_price_one(self):
        self.yahoo.missing = {"U3"}
        self.db.tables["untracked_metadata"] = [
            r for r in self.db.tables["untracked_metadata"] if r["id"] != "U3"
        ]
        self.run_job()

        result = self.get("/api/measurements/market-cap/FAKE")

        self.assertIsNone(result["per_ticker"]["U3"])
        self.assertEqual(result["per_ticker_reason"]["U3"], "no market cap on record for this ticker")

    def test_stored_descriptions_are_not_read_again_for_every_request(self):
        self.run_job()
        self.get("/api/sectors/FAKE")
        reads = self.db.reads.count("untracked_metadata")

        self.get("/api/sectors/FAKE")
        self.get("/api/measurements/market-cap/FAKE")

        self.assertGreater(reads, 0)
        self.assertEqual(self.db.reads.count("untracked_metadata"), reads)

    def test_fund_metrics_computed_across_a_state_change_is_not_cached_under_either_state(self):
        from services import fund_metrics

        real = fund_metrics._compute
        calls = {"n": 0}

        def deep_fill_lands_midway(etf_id):
            calls["n"] += 1
            if calls["n"] == 1:
                self.run_job()
            return real(etf_id)

        with patch("services.fund_metrics._compute", deep_fill_lands_midway):
            fund_metrics.compute_fund_metrics("FAKE")      # key read as pruned, computed as deep
            fund_metrics.compute_fund_metrics("FAKE")
            self.assertEqual(calls["n"], 2)

            # Once the Deep-fill expires the fund is pruned again, and the pruned
            # key must not hold the figures computed while it was deep-filled.
            self.clock.advance(3601)
            after = fund_metrics.compute_fund_metrics("FAKE")

        self.assertEqual(calls["n"], 3)
        self.assertNotIn("deepFill", after)
        self.assertEqual(after["trackedWeightCoverage"], 50.0)


# ── The Full view's stored result ─────────────────────────────────────────────

class FullViewTests(ReadCase):
    """`GET /api/deep-fill/{id}/full-view` (issue #173): the whole-basket matrix and
    clusters the Deep-fill finished with, in a payload bounded for a ~500-holding
    fund, read back and never computed. A 404 - never retried - says there is no
    result to draw: never deep-filled, expired, or still running (a partial
    picture is not served)."""

    URL = "/api/deep-fill/FAKE/full-view"
    ALL = ["AAA", "BBB"] + ReadCase.TAIL

    def test_a_deep_filled_fund_answers_with_its_whole_basket(self):
        self.run_job()
        status = deep_fill.status("FAKE")

        body = self.get(self.URL)

        self.assertEqual(body["etfId"], "FAKE")
        self.assertEqual(body["period"], "1y")
        self.assertEqual(body["tickers"], self.ALL)
        self.assertEqual(body["weights"], [30.0, 20.0] + [0.5] * 6)
        self.assertEqual(body["excluded"], {})
        # The Deep-fill's own times, not the time of the request.
        self.assertEqual(body["asOf"], status["asOf"])
        self.assertEqual(body["expiresAt"], status["expiresAt"])

    def test_the_matrix_is_the_one_the_correlation_endpoint_serves_rounded_to_two_places(self):
        self.run_job()
        full = self.get(self.URL)
        matrix = self.get("/api/correlation/FAKE")

        self.assertEqual(full["correlation"]["decimals"], 2)
        rows = full["correlation"]["triangle"]
        # Lower triangle without the diagonal: row i is the i pairs to the
        # tickers before it, so 28 numbers carry all of an 8 x 8 matrix.
        self.assertEqual([len(row) for row in rows], list(range(len(self.ALL))))
        for i, a in enumerate(self.ALL):
            for j in range(i):
                self.assertEqual(rows[i][j], round(matrix["matrix"][a][self.ALL[j]], 2))
        self.assertEqual(full["clusters"], matrix["clusters"])
        self.assertEqual(
            full["averages"], [matrix["averages"][t] for t in self.ALL]
        )

    def test_a_pair_with_no_correlation_is_null_never_zero_and_a_small_negative_is_not_minus_zero(self):
        from services import full_view

        matrix = {
            "A": {"A": 1.0, "B": None, "C": -0.001},
            "B": {"A": None, "B": 1.0, "C": 0.4549},
            "C": {"A": -0.001, "B": 0.4549, "C": 1.0},
        }
        built = full_view.build(
            [["A", 3.0], ["B", 2.0], ["C", 1.0], ["D", 0.5]],
            {"matrix": matrix, "tickers": ["A", "B", "C"], "averages": {"A": -0.001, "B": 0.4549, "C": 0.2269},
             "clusters": []},
            {"D": "it could not be fetched"}, "1y",
        )

        self.assertEqual(built["correlation"]["triangle"], [[], [None], [0.0, 0.45]])
        self.assertEqual(str(built["correlation"]["triangle"][2][0]), "0.0")   # not "-0.0"
        self.assertEqual(built["excluded"], {"D": "it could not be fetched"})

    def test_it_is_read_back_never_computed_and_never_touches_the_database(self):
        self.run_job()
        expected = self.get(self.URL)
        reads = len(self.db.reads)

        with patch("services.market_data._price_frame_bundle", side_effect=AssertionError("recomputed")),                 patch("services.market_data.compute_correlation_matrix", side_effect=AssertionError("recomputed")),                 patch("services.market_data.cache", TTLCache()):
            again = self.get(self.URL)

        self.assertEqual(again, expected)
        self.assertEqual(len(self.db.reads), reads, "serving the stored result read the database")
        self.assertNothingWritten()

    def test_a_ticker_the_job_could_not_fetch_is_named_with_its_reason_and_not_drawn(self):
        self.yahoo.missing = {"U3"}
        self.run_job()

        body = self.get(self.URL)

        self.assertNotIn("U3", body["tickers"])
        self.assertEqual(len(body["weights"]), len(body["tickers"]))
        self.assertEqual(list(body["excluded"]), ["U3"])
        self.assertIn("no price history", body["excluded"]["U3"])

    def test_a_fund_never_deep_filled_is_a_404(self):
        response = client.get(self.URL)

        self.assertEqual(response.status_code, 404)
        self.assertIn("not deep-filled", response.json()["detail"])

    def test_a_fund_with_a_job_still_running_is_a_404_not_a_partial_picture(self):
        entered, release = threading.Event(), threading.Event()
        self.yahoo.hook = lambda symbols: (entered.set(), release.wait(5))
        self.addCleanup(release.set)
        deep_fill.start("FAKE")
        entered.wait(5)

        self.assertEqual(client.get(self.URL).status_code, 404)
        release.set()

    def test_after_the_ttl_it_is_a_404_again(self):
        self.run_job()
        self.assertEqual(client.get(self.URL).status_code, 200)

        self.clock.advance(3601)

        self.assertEqual(client.get(self.URL).status_code, 404)

    def test_the_fund_is_upper_cased_like_every_other_route(self):
        self.run_job()

        self.assertEqual(client.get("/api/deep-fill/fake/full-view").status_code, 200)

    def test_a_server_with_deep_fill_off_has_nothing_to_show(self):
        with patch.dict(os.environ, {"ALLOW_DEEP_FILL": "false"}):
            response = client.get(self.URL)

        self.assertEqual(response.status_code, 404)

    def test_a_deep_fill_whose_matrix_could_not_be_derived_has_no_full_view(self):
        """If the tracked half could not be read when the job finished, nothing
        was held (see `_derive`) and each read computes for itself - but a Full
        view is only ever read back, so there is none to open."""
        with patch("services.market_data.compute_correlation_matrix", side_effect=DataUnavailable("down")):
            self.run_job()

        self.assertEqual(deep_fill.status("FAKE")["state"], "ready")
        self.assertEqual(client.get(self.URL).status_code, 404)

    def test_a_payload_that_cannot_be_built_leaves_the_fund_deep_filled_without_a_full_view(self):
        """The result is already held when the payload is built, so a failure there
        must not turn a finished Deep-fill into a `failed` job."""
        with patch("services.full_view.build", side_effect=KeyError("boom")):
            self.run_job()

        self.assertEqual(deep_fill.status("FAKE")["state"], "ready")
        self.assertEqual(client.get(self.URL).status_code, 404)
        self.assertEqual(self.get("/api/correlation/FAKE")["tickers"], self.ALL)

    def test_a_second_fund_has_its_own_result(self):
        self.run_job()

        self.assertEqual(client.get("/api/deep-fill/OTHER/full-view").status_code, 404)


if __name__ == "__main__":
    unittest.main()
