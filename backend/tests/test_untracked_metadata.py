"""
Unit tests for the descriptive data kept for Untracked holdings (issue #170,
docs/adr/0005-an-untracked-holding-stays-listed-with-no-prices.md).

A Deep-fill needs a sector and a market cap for ~450 stocks a fund holds without
a `ticker` row, and a yfinance `.info` call each is the slow, rate-limit-prone
part. `scripts/sync_untracked_metadata.py` stores one row per Untracked symbol
once a week; `market_data.get_untracked_info` reads it. Four things are pinned,
each the way a mistake would show:

- `plan_lookups` / `sync`: what gets looked up and when. New symbols first, then
  failed ones, then stale ones; a good row younger than 7 calendar days never
  again; a failed row on EVERY run, however recently it failed - and one bad
  symbol leaves the rest of the run, and the data a row already held, intact.
- Standing changes in `complete_database.complete_holdings`: a demoted stock's own
  `ticker` metadata is copied across with no `.info` call; a Tracked stock has no
  row here.
- The orphan sweep: a symbol no fund lists as Untracked has no row.
- `get_untracked_info`: `None` with a reason for a missing, failed or incomplete
  row, never a blank sector or an assumed currency.

Everything runs against the in-memory Supabase double of
test_untracked_holdings.py (it applies filters and writes) - no network, no
Supabase, no yfinance.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import contextlib
import io
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import complete_database, sync_untracked_metadata as sync_mod
from scripts.sync_untracked_metadata import RECHECK_AFTER_DAYS, SyncResult, plan_lookups, sync
from services.market_data import get_untracked_info
from test_untracked_holdings import _Db, _Query, _row, _stock_tables

NOW = datetime(2026, 10, 4, 6, 30, tzinfo=timezone.utc)   # a Sunday
TODAY = NOW.date()


def _info(sym, sector="Technology", cap=1_000_000):
    return {
        "ticker": sym, "name": f"{sym} Inc.", "sector": sector, "sectorTag": "TECH",
        "marketCap": cap, "currency": "USD", "exchange": "NMS", "logo": "", "website": f"https://{sym.lower()}.example",
    }


def _stored(sym, checked_at, failure=None, sector="Technology"):
    """A row of `untracked_metadata` as the weekly job leaves it."""
    return {
        "id": sym, "name": f"{sym} Inc.", "sector": sector, "market_cap": 5, "currency": "USD",
        "exchange": "NMS", "logo": "", "website": "", "checked_at": checked_at, "failure": failure,
    }


class _Lookups:
    """A stand-in for `_get_stock_info_live` that records what it was asked and
    can be told which symbols fail."""

    def __init__(self, fails=()):
        self.calls, self.fails = [], set(fails)

    def __call__(self, sym):
        self.calls.append(sym)
        if sym in self.fails:
            raise RuntimeError(f"yfinance said no to {sym}")
        return _info(sym)


def _sync(db, lookup, now=NOW, dry_run=False):
    with contextlib.redirect_stdout(io.StringIO()):
        return sync(db, now.date(), now, dry_run, lookup)


def _untracked_fund(*symbols, etf="SPY"):
    return [_row(etf, s, 0.05, tracked=False) for s in symbols]


# ── plan_lookups ─────────────────────────────────────────────────────────────

class PlanLookupsTests(unittest.TestCase):
    def test_new_symbols_are_looked_up_before_stale_ones(self):
        """A run cut short must have spent its calls on what a Deep-fill cannot
        describe at all, not on refreshing what it already can."""
        plan = plan_lookups(
            {"AAA", "OLD", "ZZZ"}, [_stored("OLD", "2026-09-01T06:00:00+00:00")], TODAY
        )
        self.assertEqual(plan.lookup, ["AAA", "ZZZ", "OLD"])

    def test_stale_symbols_are_looked_up_oldest_first(self):
        plan = plan_lookups(
            {"A", "B"},
            [_stored("A", "2026-09-20T06:00:00+00:00"), _stored("B", "2026-09-10T06:00:00+00:00")],
            TODAY,
        )
        self.assertEqual(plan.lookup, ["B", "A"])

    def test_a_row_checked_within_seven_days_is_left_alone(self):
        plan = plan_lookups({"X"}, [_stored("X", "2026-09-28T06:00:00+00:00")], TODAY)  # 6 days
        self.assertEqual(plan.lookup, [])
        self.assertEqual(plan.fresh, 1)

    def test_a_row_checked_seven_days_ago_is_due_whatever_the_hour(self):
        """GitHub starts the cron at a different hour each week. Counted in
        hours, a row checked at 07:40 last Sunday would not be due at 06:30 this
        Sunday and would wait a whole extra week."""
        plan = plan_lookups({"X"}, [_stored("X", "2026-09-27T07:40:00+00:00")], TODAY)
        self.assertEqual(RECHECK_AFTER_DAYS, 7)
        self.assertEqual(plan.lookup, ["X"])

    def test_a_failed_row_is_always_due_however_recently_it_failed(self):
        """The reader refuses a failed row, so until it succeeds the symbol is one a
        Deep-fill cannot describe; a re-run after an outage has to fix that, not
        skip it for a week."""
        for checked_at in ("2026-10-04T05:00:00+00:00", "2026-10-03T06:00:00+00:00", "2026-09-27T06:00:00+00:00"):
            failed = _stored("X", checked_at, failure="boom")
            self.assertEqual(plan_lookups({"X"}, [failed], TODAY).lookup, ["X"], checked_at)

    def test_a_failed_row_is_not_counted_as_left_alone(self):
        plan = plan_lookups({"X"}, [_stored("X", "2026-10-04T05:00:00+00:00", failure="boom")], TODAY)
        self.assertEqual(plan.fresh, 0)

    def test_new_symbols_come_first_then_failed_then_stale(self):
        """A run cut short should have spent its calls on what a Deep-fill cannot
        describe (no row, or a row the reader refuses) before refreshing what it can."""
        plan = plan_lookups(
            {"NEW", "FAILED", "STALE", "FRESH"},
            [
                _stored("STALE", "2026-09-01T06:00:00+00:00"),
                _stored("FAILED", "2026-10-03T06:00:00+00:00", failure="boom"),
                _stored("FRESH", "2026-10-03T06:00:00+00:00"),
            ],
            TODAY,
        )
        self.assertEqual(plan.lookup, ["NEW", "FAILED", "STALE"])
        self.assertEqual(plan.fresh, 1)

    def test_a_good_row_is_still_left_alone_when_it_is_a_failure_that_cleared(self):
        recovered = _stored("X", "2026-10-03T06:00:00+00:00", failure=None)
        self.assertEqual(plan_lookups({"X"}, [recovered], TODAY).lookup, [])

    def test_rows_for_symbols_that_are_not_untracked_any_more_are_orphans(self):
        plan = plan_lookups({"KEEP"}, [_stored("KEEP", "2026-10-03T00:00:00+00:00"), _stored("GONE", "2026-10-03T00:00:00+00:00")], TODAY)
        self.assertEqual(plan.orphans, ["GONE"])


# ── sync ─────────────────────────────────────────────────────────────────────

class SyncTests(unittest.TestCase):
    def test_every_untracked_symbol_has_a_row_after_a_run(self):
        db = _Db({"etf_holdings": _untracked_fund("A", "B") + _untracked_fund("B", "C", etf="QQQ")})
        lookups = _Lookups()
        result = _sync(db, lookups)

        rows = {r["id"]: r for r in db.tables["untracked_metadata"]}
        self.assertEqual(set(rows), {"A", "B", "C"})
        self.assertEqual(sorted(lookups.calls), ["A", "B", "C"])  # B is held twice, looked up once
        self.assertEqual(rows["A"]["sector"], "Technology")
        self.assertEqual(rows["A"]["market_cap"], 1_000_000)
        self.assertIsNone(rows["A"]["failure"])
        self.assertEqual(rows["A"]["checked_at"], NOW.isoformat())
        self.assertEqual(result.failed, {})

    def test_a_tracked_holding_is_never_looked_up(self):
        db = _Db({"etf_holdings": [_row("SPY", "AAPL", 7.0)] + _untracked_fund("TINY")})
        lookups = _Lookups()
        _sync(db, lookups)
        self.assertEqual(lookups.calls, ["TINY"])

    def test_a_second_run_the_same_day_looks_nothing_up(self):
        db = _Db({"etf_holdings": _untracked_fund("A", "B")})
        _sync(db, _Lookups())
        again = _Lookups()
        result = _sync(db, again)
        self.assertEqual(again.calls, [])
        self.assertEqual(result.skipped, 2)

    def test_rows_are_looked_up_again_a_week_later(self):
        db = _Db({"etf_holdings": _untracked_fund("A")})
        _sync(db, _Lookups())
        later = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)
        again = _Lookups()
        _sync(db, again, now=later)
        self.assertEqual(again.calls, ["A"])
        self.assertEqual(db.tables["untracked_metadata"][0]["checked_at"], later.isoformat())

    def test_one_failing_lookup_keeps_a_row_with_the_reason_and_finishes_the_run(self):
        db = _Db({"etf_holdings": _untracked_fund("BAD", "GOOD1", "GOOD2")})
        result = _sync(db, _Lookups(fails={"BAD"}))

        rows = {r["id"]: r for r in db.tables["untracked_metadata"]}
        self.assertEqual(set(rows), {"BAD", "GOOD1", "GOOD2"})
        self.assertIn("yfinance said no to BAD", rows["BAD"]["failure"])
        self.assertEqual(rows["BAD"]["checked_at"], NOW.isoformat())
        self.assertIsNone(rows["GOOD1"]["failure"])
        self.assertEqual(list(result.failed), ["BAD"])
        self.assertEqual(sorted(result.looked_up), ["GOOD1", "GOOD2"])

    def test_a_failed_refresh_keeps_the_data_the_row_already_had(self):
        old = _stored("X", "2026-09-20T06:00:00+00:00")
        db = _Db({"etf_holdings": _untracked_fund("X"), "untracked_metadata": [old]})
        _sync(db, _Lookups(fails={"X"}))

        (row,) = db.tables["untracked_metadata"]
        self.assertIsNotNone(row["failure"])
        self.assertEqual(row["sector"], "Technology")     # not blanked by a bad week
        self.assertEqual(row["market_cap"], 5)

    def test_a_failed_symbol_is_retried_by_the_very_next_run_and_the_failure_cleared(self):
        db = _Db({"etf_holdings": _untracked_fund("X", "OK")})
        _sync(db, _Lookups(fails={"X"}))
        retry = _Lookups()
        result = _sync(db, retry, now=datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc))  # the same day

        self.assertEqual(retry.calls, ["X"])             # OK is a good row from three hours ago: left alone
        self.assertIsNone(db.tables["untracked_metadata"][0]["failure"])
        self.assertEqual(result.failed, {})

    def test_a_symbol_that_keeps_failing_is_tried_on_every_run(self):
        db = _Db({"etf_holdings": _untracked_fund("X")})
        for hour in (6, 7, 8):
            lookups = _Lookups(fails={"X"})
            result = _sync(db, lookups, now=datetime(2026, 10, 4, hour, 0, tzinfo=timezone.utc))
            self.assertEqual(lookups.calls, ["X"], hour)
            self.assertEqual(list(result.failed), ["X"])

    def test_a_row_that_cannot_be_written_is_a_failure_not_a_lookup(self):
        db = _Db({"etf_holdings": _untracked_fund("BAD", "GOOD")})
        real_execute = _Query.execute

        def flaky(query):
            if query._name == "untracked_metadata" and query._op == "upsert" and query._payload[0]["id"] == "BAD":
                raise RuntimeError("write refused")
            return real_execute(query)

        with patch.object(_Query, "execute", flaky):
            result = _sync(db, _Lookups())

        self.assertEqual(list(result.failed), ["BAD"])
        self.assertEqual(result.looked_up, ["GOOD"])
        self.assertEqual([r["id"] for r in db.tables["untracked_metadata"]], ["GOOD"])

    def test_a_symbol_no_fund_lists_as_untracked_has_no_row(self):
        db = _Db({
            "etf_holdings": _untracked_fund("HELD"),
            "untracked_metadata": [
                _stored("HELD", "2026-10-03T06:00:00+00:00"),
                _stored("DROPPED", "2026-10-03T06:00:00+00:00"),   # no fund lists it any more
            ],
        })
        result = _sync(db, _Lookups())
        self.assertEqual([r["id"] for r in db.tables["untracked_metadata"]], ["HELD"])
        self.assertEqual(result.dropped, ["DROPPED"])

    def test_a_promoted_symbol_loses_its_row(self):
        """PROMO is Tracked now (its holding rows say so), so `ticker` owns its
        metadata and a row here would be a second, ageing copy."""
        db = _Db({
            "etf_holdings": [_row("SPY", "PROMO", 2.0, tracked=True)],
            "untracked_metadata": [_stored("PROMO", "2026-10-03T06:00:00+00:00")],
        })
        _sync(db, _Lookups())
        self.assertEqual(db.tables["untracked_metadata"], [])

    def test_more_symbols_than_one_page_are_all_looked_up(self):
        symbols = [f"S{i:04d}" for i in range(1_050)]
        db = _Db({"etf_holdings": _untracked_fund(*symbols)})
        lookups = _Lookups()
        _sync(db, lookups)
        self.assertEqual(len(lookups.calls), 1_050)
        self.assertEqual(len(db.tables["untracked_metadata"]), 1_050)

    def test_a_dry_run_plans_but_calls_and_writes_nothing(self):
        db = _Db({
            "etf_holdings": _untracked_fund("NEW"),
            "untracked_metadata": [_stored("DROPPED", "2026-10-03T06:00:00+00:00")],
        })
        before = db.snapshot()
        lookups = _Lookups()
        result = _sync(db, lookups, dry_run=True)

        self.assertEqual(lookups.calls, [])
        self.assertEqual(db.snapshot(), before)
        self.assertEqual(result.looked_up, ["NEW"])
        self.assertEqual(result.dropped, ["DROPPED"])


def _shell(asked):
    """What `_get_stock_info_live` answers for a symbol yfinance has nothing on
    (observed live for ZZZZQQ and for BRK.B): it does not raise."""
    return {
        "ticker": asked, "name": asked, "sector": "Unknown", "sectorTag": "UNKNOW",
        "marketCap": None, "currency": "USD", "exchange": "", "logo": "", "website": "",
    }


class YahooSymbolTests(unittest.TestCase):
    def test_a_share_class_is_dashed(self):
        self.assertEqual(sync_mod.yahoo_symbol("BRK.B"), "BRK-B")
        self.assertEqual(sync_mod.yahoo_symbol("BF.B"), "BF-B")

    def test_a_longer_exchange_suffix_keeps_its_dot(self):
        self.assertEqual(sync_mod.yahoo_symbol("NPN.SJ"), "NPN.SJ")

    def test_a_plain_symbol_is_unchanged(self):
        self.assertEqual(sync_mod.yahoo_symbol("AAPL"), "AAPL")


class EmptyShellTests(unittest.TestCase):
    """yfinance answers a symbol it has nothing on with a shell instead of an
    error. Stored as given it would be a sector of "Unknown" and a currency of
    "USD" that nobody looked up, handed out as fact by the reader."""

    def test_a_share_class_is_asked_for_the_way_yfinance_spells_it_and_keyed_as_the_repo_does(self):
        db = _Db({"etf_holdings": _untracked_fund("BF.B")})
        lookups = _Lookups()
        _sync(db, lookups)

        self.assertEqual(lookups.calls, ["BF-B"])
        self.assertEqual([r["id"] for r in db.tables["untracked_metadata"]], ["BF.B"])

    def test_a_single_letter_exchange_suffix_is_found_by_its_dotted_spelling(self):
        """ABC.L looks like a share class, so ABC-L is tried first and comes back
        a shell; the dotted original is what yfinance knows."""
        db = _Db({"etf_holdings": _untracked_fund("ABC.L")})
        calls = []

        def london_only(asked):
            calls.append(asked)
            return _info(asked) if asked == "ABC.L" else _shell(asked)

        _sync(db, london_only)
        self.assertEqual(calls, ["ABC-L", "ABC.L"])
        (row,) = db.tables["untracked_metadata"]
        self.assertEqual((row["id"], row["sector"]), ("ABC.L", "Technology"))

    def test_a_shell_is_stored_as_nothing_there_not_as_unknown_and_usd(self):
        db = _Db({"etf_holdings": _untracked_fund("CASHLINE")})
        result = _sync(db, _shell)

        (row,) = db.tables["untracked_metadata"]
        self.assertEqual(
            {k: row[k] for k in ("name", "sector", "market_cap", "currency", "exchange", "logo", "website", "failure")},
            {k: None for k in ("name", "sector", "market_cap", "currency", "exchange", "logo", "website", "failure")},
        )
        self.assertEqual(row["checked_at"], NOW.isoformat())
        self.assertEqual(result.failed, {})      # not a failure: nothing to retry it into
        self.assertEqual(result.looked_up, ["CASHLINE"])

    def test_a_shell_is_not_looked_up_again_within_the_week(self):
        db = _Db({"etf_holdings": _untracked_fund("CASHLINE")})
        _sync(db, _shell)
        calls = []
        _sync(db, lambda sym: calls.append(sym) or _shell(sym))
        self.assertEqual(calls, [])

    def test_the_reader_answers_a_shell_as_no_data_with_a_reason(self):
        db = _Db({"etf_holdings": _untracked_fund("CASHLINE")})
        _sync(db, _shell)
        with patch("services.market_data.get_client_optional", return_value=db):
            entry = get_untracked_info(["CASHLINE"])["CASHLINE"]
        self.assertIsNone(entry["info"])
        self.assertIn("no descriptive data", entry["reason"])

    def test_a_real_answer_with_no_market_cap_is_not_mistaken_for_a_shell(self):
        """A real answer with no market cap (a fund, say) keeps its sector and name."""
        def etf_like(asked):
            return {**_info(asked, sector="Unknown", cap=None), "name": "Some Fund"}
        db = _Db({"etf_holdings": _untracked_fund("FUNDX")})
        _sync(db, etf_like)
        (row,) = db.tables["untracked_metadata"]
        self.assertEqual(row["name"], "Some Fund")
        self.assertEqual(row["sector"], "Unknown")


class OrphanSweepFailureTests(unittest.TestCase):
    def test_a_failing_sweep_is_reported_and_the_lookups_before_it_are_kept(self):
        db = _Db({
            "etf_holdings": _untracked_fund("A"),
            "untracked_metadata": [_stored("DROPPED", "2026-10-03T06:00:00+00:00")],
        })
        real_execute = _Query.execute

        def refuse_delete(query):
            if query._name == "untracked_metadata" and query._op == "delete":
                raise RuntimeError("delete refused")
            return real_execute(query)

        with patch.object(_Query, "execute", refuse_delete):
            result = _sync(db, _Lookups())

        self.assertIn("orphan sweep", result.failed)
        self.assertEqual(result.looked_up, ["A"])
        self.assertIn("A", [r["id"] for r in db.tables["untracked_metadata"]])


class MainExitCodeTests(unittest.TestCase):
    def _run(self, result):
        out = io.StringIO()
        with patch.object(sync_mod, "get_client", return_value=object()), \
             patch.object(sync_mod, "sync", return_value=result), \
             patch.object(sys, "argv", ["sync_untracked_metadata.py"]), \
             contextlib.redirect_stdout(out):
            sync_mod.main()
        return out.getvalue()

    def test_a_failed_lookup_exits_1_naming_the_symbol(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(out):
            with patch.object(sync_mod, "get_client", return_value=object()), \
                 patch.object(sync_mod, "sync", return_value=SyncResult(["A"], 0, {"BAD": "RuntimeError: boom"}, [])), \
                 patch.object(sys, "argv", ["sync_untracked_metadata.py"]):
                sync_mod.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("BAD: RuntimeError: boom", out.getvalue())

    def test_a_clean_run_does_not_exit_nonzero(self):
        self.assertIn("1 symbol(s) looked up", self._run(SyncResult(["A"], 3, {}, [])))


# ── standing changes in complete_database ─────────────────────────────────────

def _complete(db, normalized, tickers, dry_run=False):
    with contextlib.redirect_stdout(io.StringIO()):
        return complete_database.complete_holdings(db, normalized, set(tickers), 1.0, dry_run)


class _NoInfoCalls:
    """Fails the test if anything asks yfinance for a stock's metadata."""

    def __enter__(self):
        def refuse(sym):
            raise AssertionError(f".info was called for {sym}")
        self._patches = [
            patch.object(complete_database, "_get_stock_info_live", refuse),
            patch.object(sync_mod, "_get_stock_info_live", refuse),
        ]
        for p in self._patches:
            p.start()

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


def _ticker_row(sym, sector="Energy"):
    return {
        "id": sym, "name": f"{sym} Corp", "active": True, "last_fetch": "2026-10-02", "sector": sector,
        "market_cap": 123_456, "currency": "USD", "exchange": "NYQ", "logo": "logo.png", "website": "https://x.example",
    }


class StandingChangeTests(unittest.TestCase):
    def _demotion_db(self, **ticker_overrides):
        tables = _stock_tables("FALLEN")
        tables["ticker"] = [{**_ticker_row("FALLEN"), **ticker_overrides}]
        return _Db({**tables, "etf_holdings": [_row("A", "FALLEN", 3.0)]})

    def test_a_demoted_stock_keeps_its_old_metadata_and_costs_no_info_call(self):
        db = self._demotion_db()
        with _NoInfoCalls():
            _complete(db, {"A": {"FALLEN": 0.5}}, {"FALLEN"})

        self.assertEqual(db.rows_for("ticker", "FALLEN"), [])
        (row,) = db.tables["untracked_metadata"]
        self.assertEqual(row["id"], "FALLEN")
        self.assertEqual(
            {k: row[k] for k in ("name", "sector", "market_cap", "currency", "exchange", "logo", "website")},
            {"name": "FALLEN Corp", "sector": "Energy", "market_cap": 123_456, "currency": "USD",
             "exchange": "NYQ", "logo": "logo.png", "website": "https://x.example"},
        )
        self.assertIsNone(row["failure"])
        self.assertTrue(row["checked_at"])

    def test_the_copy_is_made_before_the_ticker_row_is_deleted(self):
        db = self._demotion_db()
        seen = []
        real_execute = _Query.execute

        def spying(query):
            if query._name == "ticker" and query._op == "delete":
                seen.append([r["id"] for r in db.tables.get("untracked_metadata", [])])
            return real_execute(query)

        with patch.object(_Query, "execute", spying):
            _complete(db, {"A": {"FALLEN": 0.5}}, {"FALLEN"})
        self.assertEqual(seen, [["FALLEN"]])

    def test_a_ticker_that_was_never_synced_is_not_copied_as_an_answer(self):
        """A null sector is the never-synced sentinel; copying it would store a
        blank as if it were what yfinance said. The weekly lookup takes it."""
        db = self._demotion_db(sector=None)
        _complete(db, {"A": {"FALLEN": 0.5}}, {"FALLEN"})

        self.assertEqual(db.rows_for("ticker", "FALLEN"), [])
        self.assertEqual(db.tables.get("untracked_metadata", []), [])

    def test_a_failed_copy_does_not_stop_the_demotion(self):
        db = self._demotion_db()
        real_execute = _Query.execute

        def refuse(query):
            if query._name == "untracked_metadata":
                raise RuntimeError("table missing")
            return real_execute(query)

        with patch.object(_Query, "execute", refuse):
            demoted, failed = _complete(db, {"A": {"FALLEN": 0.5}}, {"FALLEN"})

        self.assertEqual(demoted, ["FALLEN"])
        self.assertEqual(failed, [])
        self.assertEqual(db.rows_for("ticker", "FALLEN"), [])

    def test_a_promoted_stock_has_no_row(self):
        db = _Db({
            **_stock_tables("RISER"),
            "etf_holdings": [_row("B", "RISER", 0.4, tracked=False)],
            "untracked_metadata": [_stored("RISER", "2026-10-01T06:00:00+00:00"), _stored("STAYS", "2026-10-01T06:00:00+00:00")],
        })
        _complete(db, {"A": {"RISER": 2.0}}, {"RISER"})

        self.assertEqual([r["id"] for r in db.tables["untracked_metadata"]], ["STAYS"])

    def test_a_dry_run_copies_and_deletes_nothing(self):
        db = self._demotion_db()
        db.tables["untracked_metadata"] = [_stored("RISER", "2026-10-01T06:00:00+00:00")]
        before = db.snapshot()
        _complete(db, {"A": {"FALLEN": 0.5, "RISER": 2.0}}, {"FALLEN", "RISER"}, dry_run=True)
        self.assertEqual(db.snapshot(), before)

    def test_a_second_run_changes_nothing(self):
        db = self._demotion_db()
        file = {"A": {"FALLEN": 0.5}}
        _complete(db, file, {"FALLEN"})
        after_first = db.snapshot()
        _complete(db, file, {r["id"] for r in db.tables["ticker"]})
        self.assertEqual(db.snapshot(), after_first)


# ── the reader ───────────────────────────────────────────────────────────────

class GetUntrackedInfoTests(unittest.TestCase):
    def _read(self, db, tickers):
        with patch("services.market_data.get_client_optional", return_value=db):
            return get_untracked_info(tickers)

    def test_a_stored_row_reads_back_with_the_stock_info_keys(self):
        db = _Db({"untracked_metadata": [_stored("TINY", "2026-10-03T06:00:00+00:00")]})
        entry = self._read(db, ["TINY"])["TINY"]

        self.assertIsNone(entry["reason"])
        self.assertEqual(
            entry["info"],
            {"ticker": "TINY", "name": "TINY Inc.", "sector": "Technology", "sectorTag": "TECH",
             "marketCap": 5, "currency": "USD", "exchange": "NMS", "logo": "", "website": ""},
        )

    def test_a_symbol_with_no_row_is_none_with_a_reason_not_a_blank_sector(self):
        entry = self._read(_Db({}), ["NEW"])["NEW"]
        self.assertIsNone(entry["info"])
        self.assertIn("not looked it up", entry["reason"])

    def test_a_failed_row_is_none_and_the_reason_says_why(self):
        db = _Db({"untracked_metadata": [_stored("BAD", "2026-10-03T06:00:00+00:00", failure="RuntimeError: boom")]})
        entry = self._read(db, ["BAD"])["BAD"]
        self.assertIsNone(entry["info"])
        self.assertIn("RuntimeError: boom", entry["reason"])

    def test_a_row_with_no_sector_is_none_not_an_empty_sector(self):
        db = _Db({"untracked_metadata": [_stored("HALF", "2026-10-03T06:00:00+00:00", sector=None)]})
        self.assertIsNone(self._read(db, ["HALF"])["HALF"]["info"])

    def test_an_unknown_market_cap_stays_null_not_zero(self):
        row = {**_stored("X", "2026-10-03T06:00:00+00:00"), "market_cap": None, "currency": None}
        info = self._read(_Db({"untracked_metadata": [row]}), ["X"])["X"]["info"]
        self.assertIsNone(info["marketCap"])
        self.assertIsNone(info["currency"])      # no assumed "USD"

    def test_every_requested_symbol_is_answered_once(self):
        db = _Db({"untracked_metadata": [_stored("A", "2026-10-03T06:00:00+00:00")]})
        result = self._read(db, ["A", "B", "A", ""])
        self.assertEqual(sorted(result), ["A", "B"])

    def test_a_tracked_symbol_has_no_row_here(self):
        self.assertIsNone(self._read(_Db({}), ["AAPL"])["AAPL"]["info"])

    def test_no_symbols_is_an_empty_answer_without_touching_the_database(self):
        with patch("services.market_data.get_client_optional", side_effect=AssertionError("db touched")):
            self.assertEqual(get_untracked_info([]), {})

    def test_an_unconfigured_database_answers_none_for_each_symbol_with_a_reason(self):
        with patch("services.market_data.get_client_optional", return_value=None):
            result = get_untracked_info(["A", "B"])
        for entry in result.values():
            self.assertIsNone(entry["info"])
            self.assertIn("could not be reached", entry["reason"])

    def test_a_failing_read_answers_none_instead_of_raising(self):
        class Broken:
            def table(self, name):
                raise RuntimeError("boom")

        result = self._read(Broken(), ["A"])
        self.assertIsNone(result["A"]["info"])
        self.assertIn("could not be read", result["A"]["reason"])

    def test_a_basket_larger_than_one_chunk_is_read_in_full(self):
        """~450 symbols ride in a URL filter; the list is chunked and each
        chunk paged, and no symbol may be lost to either."""
        symbols = [f"S{i:04d}" for i in range(1_250)]
        db = _Db({"untracked_metadata": [_stored(s, "2026-10-03T06:00:00+00:00") for s in symbols]})
        result = self._read(db, symbols)
        self.assertEqual(len(result), 1_250)
        self.assertTrue(all(entry["info"] for entry in result.values()))


if __name__ == "__main__":
    unittest.main()
