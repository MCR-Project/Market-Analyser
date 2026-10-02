"""
Unit tests for keeping Untracked holdings listed instead of pruning them
(issue #168, docs/adr/0005-an-untracked-holding-stays-listed-with-no-prices.md).

A constituent under the weight threshold in every fund holding it used to be
deleted, holding row and all, so a fund like SPY kept ~46 of ~500 holdings and
nothing we could read said what the rest were. It now stays in `etf_holdings`
with its weight and `tracked = false`, and loses only what costs storage or a
daily fetch: its `ticker`, `prices`, `dividends` and `splits` rows.

Three things are pinned here, each the way a mistake would show:

- `plan_tracking` / `complete_holdings` (scripts/complete_database.py): the flag
  is a fact about the *stock* - its highest weight across every fund holding it -
  and is written on all of that stock's rows, so a stock at 0.4% in one fund and
  2% in another is tracked in both. A second run with the same file changes
  nothing. `tracked = true` never sits on a row with no `ticker` row behind it.
- The readers (`get_etf_holdings`'s DB read, `list_etf_summaries`, `sync_etfs`):
  each filters to tracked rows, or a fund's default view jumps from ~46
  holdings to ~500. The doubles in the older test files ignore `.eq`, so they
  could not tell; the one here applies filters, so leaving one off fails.
- `fetch_daily`'s price sync reads the `ticker` table alone, and a demoted stock
  has no row there, so it can never be selected.

Everything runs against an in-memory double of the Supabase client - no
network, no Supabase.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import contextlib
import io
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import fetch_daily
from scripts.complete_database import complete_holdings, plan_tracking
from services.market_data import _get_etf_holdings_db, list_etf_summaries
from services.supabase_client import SUPABASE_PAGE_SIZE

PRIMARY_KEYS = {
    "etf_holdings": ("etf_id", "ticker"),
    "ticker": ("id",),
    "prices": ("ticker", "date", "granularity"),
    "dividends": ("ticker", "date"),
    "splits": ("ticker", "date"),
    "etfs": ("id",),
    "untracked_metadata": ("id",),
}


class _Query:
    """One fluent Supabase query against an in-memory table. Unlike the
    stand-ins in the older test files it actually applies `.eq` / `.in_`,
    `.order` and `.range`, and it applies `upsert` / `update` / `delete` to the
    stored rows - what these tests assert is what the database ends up holding."""

    def __init__(self, db, name):
        self._db, self._name = db, name
        self._filters, self._orders = [], []
        self._start, self._end = 0, None
        self._op, self._payload = "select", None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters.append(lambda row: row.get(col) == val)
        return self

    def in_(self, col, vals):
        self._filters.append(lambda row: row.get(col) in vals)
        return self

    def order(self, col, desc=False):
        self._orders.append((col, desc))
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def upsert(self, rows):
        self._op, self._payload = "upsert", rows if isinstance(rows, list) else [rows]
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def _matching(self):
        return [r for r in self._db.tables.setdefault(self._name, []) if all(f(r) for f in self._filters)]

    def execute(self):
        table = self._db.tables.setdefault(self._name, [])
        if self._op == "upsert":
            key = PRIMARY_KEYS[self._name]
            for new in self._payload:
                existing = next((r for r in table if all(r.get(k) == new.get(k) for k in key)), None)
                if existing is None:
                    # a new row takes the column defaults the migration declares
                    table.append({"tracked": True, **new} if self._name == "etf_holdings" else dict(new))
                else:
                    existing.update(new)
            return SimpleNamespace(data=[])
        if self._op == "update":
            for row in self._matching():
                row.update(self._payload)
            return SimpleNamespace(data=[])
        if self._op == "delete":
            doomed = self._matching()
            self._db.tables[self._name] = [r for r in table if not any(r is d for d in doomed)]
            return SimpleNamespace(data=[])
        rows = self._matching()
        for col, desc in reversed(self._orders):
            rows = sorted(rows, key=lambda r: r[col], reverse=desc)
        return SimpleNamespace(data=[dict(r) for r in rows[self._start:None if self._end is None else self._end + 1]])


class _Db:
    def __init__(self, tables):
        self.tables = deepcopy(tables)

    def table(self, name):
        return _Query(self, name)

    def snapshot(self):
        return deepcopy(self.tables)

    def holding(self, etf_id, ticker):
        return next(
            (r for r in self.tables.get("etf_holdings", []) if r["etf_id"] == etf_id and r["ticker"] == ticker),
            None,
        )

    def rows_for(self, table, ticker):
        col = "id" if table == "ticker" else "ticker"
        return [r for r in self.tables.get(table, []) if r[col] == ticker]


def _stock_tables(*symbols):
    """The `ticker` / `prices` / `dividends` / `splits` rows a tracked stock has."""
    return {
        "ticker": [{"id": s, "active": True, "last_fetch": "2026-09-29"} for s in symbols],
        "prices": [{"ticker": s, "date": "2026-09-29", "granularity": "D", "close": 10.0} for s in symbols],
        "dividends": [{"ticker": s, "date": "2026-09-01", "dividends": 0.1} for s in symbols],
        "splits": [{"ticker": s, "date": "2020-01-01", "splits": 2.0} for s in symbols],
    }


def _row(etf_id, ticker, weight, tracked=True):
    return {"etf_id": etf_id, "ticker": ticker, "weight": weight, "tracked": tracked}


def _complete(db, normalized, tickers, min_weight=1.0, dry_run=False):
    with contextlib.redirect_stdout(io.StringIO()):
        return complete_holdings(db, normalized, set(tickers), min_weight, dry_run)


# ── plan_tracking ────────────────────────────────────────────────────────────

class PlanTrackingTests(unittest.TestCase):
    def test_a_stock_is_tracked_when_its_heaviest_weight_clears_the_threshold(self):
        """0.4% in fund A and 2% in fund B: Tracked, on both funds' rows - the
        flag belongs to the stock, not to one fund's holding of it."""
        plan = plan_tracking(
            stored_rows=[_row("B", "MIXED", 2.0)],
            normalized_by_etf={"A": {"MIXED": 0.4}},
            tickers={"MIXED"},
            min_weight=1.0,
        )
        self.assertTrue(plan.tracked["MIXED"])
        self.assertEqual(plan.demote, [])

    def test_a_stock_under_the_threshold_everywhere_is_untracked_and_demoted(self):
        plan = plan_tracking(
            stored_rows=[_row("B", "SMALL", 0.6)],
            normalized_by_etf={"A": {"SMALL": 0.4}},
            tickers={"SMALL"},
            min_weight=1.0,
        )
        self.assertFalse(plan.tracked["SMALL"])
        self.assertEqual(plan.demote, ["SMALL"])

    def test_an_untracked_stock_with_no_ticker_row_has_nothing_to_demote(self):
        plan = plan_tracking([], {"A": {"SMALL": 0.4}}, tickers=set(), min_weight=1.0)
        self.assertFalse(plan.tracked["SMALL"])
        self.assertEqual(plan.demote, [])

    def test_a_heavy_stock_with_no_ticker_row_is_not_flagged_tracked(self):
        """yfinance had no history for it, or its backfill failed: it stays
        listed but Untracked, because `tracked = true` promises a `ticker` row
        - and a reader would otherwise list a holding nothing can price."""
        plan = plan_tracking([], {"A": {"NOHIST": 5.0}}, tickers=set(), min_weight=1.0)
        self.assertFalse(plan.tracked["NOHIST"])
        self.assertEqual(plan.demote, [])

    def test_a_stock_rising_over_the_threshold_retags_its_rows_in_other_funds(self):
        """SMALL sat at 0.4% in fund B (flagged untracked); fund A's file now
        carries it at 2%. Fund B's row is not in this run, so it has to be
        retagged separately or it would disagree with fund A's."""
        plan = plan_tracking(
            stored_rows=[_row("B", "SMALL", 0.4, tracked=False)],
            normalized_by_etf={"A": {"SMALL": 2.0}},
            tickers={"SMALL"},  # inserted and backfilled earlier in the run
            min_weight=1.0,
        )
        self.assertTrue(plan.tracked["SMALL"])
        self.assertEqual(plan.retag, {"SMALL": True})

    def test_a_stock_falling_under_the_threshold_retags_its_rows_in_other_funds(self):
        """FALLEN was 3% in fund A and 0.8% in fund C; A's file now says 0.5%.
        C's row is not in this run and still says tracked, so it has to be
        retagged or the two funds would disagree about one stock."""
        plan = plan_tracking(
            stored_rows=[_row("A", "FALLEN", 3.0), _row("C", "FALLEN", 0.8)],
            normalized_by_etf={"A": {"FALLEN": 0.5}},
            tickers={"FALLEN"},
            min_weight=1.0,
        )
        self.assertFalse(plan.tracked["FALLEN"])
        self.assertEqual(plan.demote, ["FALLEN"])
        self.assertEqual(plan.retag, {"FALLEN": False})

    def test_this_runs_weight_replaces_the_stored_one_for_the_same_pair(self):
        """The stored 5% row for (A, X) is what the file just replaced with
        0.3%: judging X by the old weight would keep it tracked forever."""
        plan = plan_tracking(
            stored_rows=[_row("A", "X", 5.0)],
            normalized_by_etf={"A": {"X": 0.3}},
            tickers={"X"},
            min_weight=1.0,
        )
        self.assertFalse(plan.tracked["X"])

    def test_a_null_weight_counts_as_zero_not_as_heavy(self):
        plan = plan_tracking([], {"A": {"X": None}}, tickers={"X"}, min_weight=1.0)
        self.assertFalse(plan.tracked["X"])

    def test_rows_already_right_are_not_retagged(self):
        plan = plan_tracking(
            stored_rows=[_row("B", "OK", 2.0)],
            normalized_by_etf={"A": {"OK": 3.0}},
            tickers={"OK"},
            min_weight=1.0,
        )
        self.assertEqual(plan.retag, {})

    def test_a_hand_added_ticker_no_fund_holds_is_left_alone(self):
        """A watchlist entry has a `ticker` row and no holding row at all: it
        is in nobody's map, so there is nothing to judge it by or demote."""
        plan = plan_tracking([], {"A": {"AAPL": 5.0}}, tickers={"AAPL", "WATCHED"}, min_weight=1.0)
        self.assertNotIn("WATCHED", plan.tracked)
        self.assertEqual(plan.demote, [])


# ── complete_holdings ────────────────────────────────────────────────────────

class CompleteHoldingsTests(unittest.TestCase):
    def _spy_file(self):
        return {"SPY": {"AAPL": 7.0, "TINY1": 0.05, "TINY2": 0.02, "NOPRICE": 0.01}}

    def test_every_constituent_is_listed_and_the_light_ones_are_untracked(self):
        db = _Db({**_stock_tables("AAPL")})
        _complete(db, self._spy_file(), tickers={"AAPL"})

        held = {r["ticker"]: r for r in db.tables["etf_holdings"] if r["etf_id"] == "SPY"}
        self.assertEqual(set(held), {"AAPL", "TINY1", "TINY2", "NOPRICE"})
        self.assertEqual(held["TINY1"]["weight"], 0.05)
        self.assertTrue(held["AAPL"]["tracked"])
        for sym in ("TINY1", "TINY2", "NOPRICE"):
            self.assertFalse(held[sym]["tracked"], sym)
            for table in ("ticker", "prices", "dividends", "splits"):
                self.assertEqual(db.rows_for(table, sym), [], f"{table} row left for {sym}")

    def test_a_stock_at_04_in_one_fund_and_2_in_another_stays_tracked_in_both(self):
        db = _Db({**_stock_tables("MIXED"), "etf_holdings": [_row("B", "MIXED", 2.0)]})
        _complete(db, {"A": {"MIXED": 0.4}}, tickers={"MIXED"})

        self.assertTrue(db.holding("A", "MIXED")["tracked"])
        self.assertTrue(db.holding("B", "MIXED")["tracked"])
        self.assertEqual(len(db.rows_for("prices", "MIXED")), 1)

    def test_a_stock_falling_under_the_threshold_everywhere_loses_its_data_and_keeps_a_row(self):
        db = _Db({**_stock_tables("FALLEN", "KEPT"), "etf_holdings": [_row("A", "FALLEN", 3.0), _row("A", "KEPT", 3.0)]})
        _complete(db, {"A": {"FALLEN": 0.5, "KEPT": 3.0}}, tickers={"FALLEN", "KEPT"})

        for table in ("ticker", "prices", "dividends", "splits"):
            self.assertEqual(db.rows_for(table, "FALLEN"), [], table)
        held = db.holding("A", "FALLEN")
        self.assertIsNotNone(held)
        self.assertEqual(held["weight"], 0.5)
        self.assertFalse(held["tracked"])
        self.assertEqual(len(db.rows_for("prices", "KEPT")), 1)

    def test_a_stock_rising_over_the_threshold_is_flagged_tracked_everywhere(self):
        """The backfill itself is insert_new_tickers's (stage 3, unchanged);
        `tickers` here already contains the stock it inserted."""
        db = _Db({**_stock_tables("RISER"), "etf_holdings": [_row("B", "RISER", 0.4, tracked=False)]})
        _complete(db, {"A": {"RISER": 2.0}}, tickers={"RISER"})

        self.assertTrue(db.holding("A", "RISER")["tracked"])
        self.assertTrue(db.holding("B", "RISER")["tracked"])

    def test_a_second_run_with_the_same_file_changes_nothing(self):
        db = _Db({**_stock_tables("AAPL", "FALLEN"), "etf_holdings": [_row("SPY", "FALLEN", 3.0)]})
        file = {"SPY": {"AAPL": 7.0, "FALLEN": 0.5, "TINY1": 0.05}}
        _complete(db, file, {"AAPL", "FALLEN"})
        after_first = db.snapshot()

        # the second run starts from what the first left in `ticker`
        remaining = {r["id"] for r in db.tables["ticker"]}
        _complete(db, file, remaining)

        self.assertEqual(db.snapshot(), after_first)

    def test_a_dry_run_writes_nothing(self):
        db = _Db({**_stock_tables("FALLEN"), "etf_holdings": [_row("A", "FALLEN", 3.0)]})
        before = db.snapshot()
        demoted, failed = _complete(db, {"A": {"FALLEN": 0.5, "NEW": 0.1}}, {"FALLEN"}, dry_run=True)

        self.assertEqual(db.snapshot(), before)
        self.assertEqual(demoted, ["FALLEN"])
        self.assertEqual(failed, [])

    def test_a_stock_is_flagged_untracked_before_its_ticker_row_goes(self):
        """The order matters if a run dies between the two writes: flag first
        leaves an untracked holding with a leftover `ticker` row (harmless, and
        the next run finishes the demotion); the other order would leave a
        tracked holding with no `ticker` row behind it."""
        db = _Db({**_stock_tables("FALLEN"), "etf_holdings": [_row("A", "FALLEN", 3.0)]})
        seen = []
        real_execute = _Query.execute

        def spying(query):
            if query._name == "ticker" and query._op == "delete":
                seen.append(db.holding("A", "FALLEN")["tracked"])
            return real_execute(query)

        with patch.object(_Query, "execute", spying):
            _complete(db, {"A": {"FALLEN": 0.5}}, {"FALLEN"})

        self.assertEqual(seen, [False])

    def test_one_stock_failing_to_demote_does_not_stop_the_rest(self):
        db = _Db({
            **_stock_tables("BAD", "GOOD"),
            "etf_holdings": [_row("A", "BAD", 3.0), _row("A", "GOOD", 3.0)],
        })
        real_execute = _Query.execute

        def flaky(query):
            if query._name == "prices" and query._op == "delete" and query._filters[0]({"ticker": "BAD"}):
                raise RuntimeError("boom")
            return real_execute(query)

        with patch.object(_Query, "execute", flaky):
            demoted, failed = _complete(db, {"A": {"BAD": 0.1, "GOOD": 0.1}}, {"BAD", "GOOD"})

        self.assertEqual(failed, ["BAD"])
        self.assertEqual(demoted, ["GOOD"])
        self.assertEqual(db.rows_for("ticker", "GOOD"), [])

    def test_truncation_past_the_page_cap_does_not_demote_a_heavy_stock(self):
        """Issue #14's headline scenario, carried over from the prune stage it
        guarded. HEAVY's underweight row sits inside the first page and its real
        weight only on a row that sorts past PostgREST's 1000-row cap. Judged on
        a truncated read it would look underweight and lose its whole price
        history; the read has to see both pages."""
        rows = [_row("A", f"FILL{i:04d}", 0.05) for i in range(SUPABASE_PAGE_SIZE - 1)]
        rows.append(_row("A", "HEAVY", 0.1))                # last row of page 1
        self.assertEqual(len(rows), SUPABASE_PAGE_SIZE)
        rows.append(_row("B", "HEAVY", 5.0))                # first row of page 2
        db = _Db({**_stock_tables("HEAVY", "FILL0000"), "etf_holdings": rows})

        demoted, failed = _complete(db, {}, {"HEAVY", "FILL0000"})

        self.assertEqual(demoted, ["FILL0000"])
        self.assertEqual(len(db.rows_for("prices", "HEAVY")), 1)
        self.assertTrue(db.holding("B", "HEAVY")["tracked"])

    def test_the_price_sync_never_selects_a_demoted_stock(self):
        """fetch_daily.py's sync loop is built from `ticker` rows alone; a
        demoted stock has none, so it cannot be picked - even by the branch
        that takes an inactive ticker whose last_fetch is null."""
        db = _Db({**_stock_tables("AAPL", "FALLEN"), "etf_holdings": [_row("SPY", "FALLEN", 3.0)]})
        _complete(db, {"SPY": {"AAPL": 7.0, "FALLEN": 0.5}}, {"AAPL", "FALLEN"})

        with contextlib.redirect_stdout(io.StringIO()):
            selected = fetch_daily._select_tickers_needing_sync(
                [dict(r) for r in db.tables["ticker"]]
            )
        self.assertEqual([r["id"] for r in selected], ["AAPL"])

    def test_more_constituents_than_one_page_are_all_written(self):
        weights = {f"T{i:04d}": 0.01 for i in range(SUPABASE_PAGE_SIZE + 50)}
        db = _Db({})
        _complete(db, {"BIG": weights}, tickers=set())
        self.assertEqual(len(db.tables["etf_holdings"]), SUPABASE_PAGE_SIZE + 50)


# ── the readers ──────────────────────────────────────────────────────────────

class ReadersFilterToTrackedTests(unittest.TestCase):
    """A fund's default view must not change (issue #168's acceptance): the
    holdings, the count on the picker list and the daily ETF sync all see
    tracked rows only."""

    def _db(self):
        return _Db({
            "etfs": [{"id": "SPY", "name": "SPDR S&P 500", "cat": "Large Blend"}],
            "etf_holdings": [
                _row("SPY", "AAPL", 7.0),
                _row("SPY", "MSFT", 6.0),
                _row("SPY", "TINY", 0.02, tracked=False),
                _row("SPY", "TINIER", 0.01, tracked=False),
            ],
        })

    def test_get_etf_holdings_lists_tracked_rows_only(self):
        with patch("services.market_data.get_client_optional", return_value=self._db()):
            self.assertEqual(_get_etf_holdings_db("SPY"), [["AAPL", 7.0], ["MSFT", 6.0]])

    def test_a_fund_with_only_untracked_rows_reads_as_unsynced(self):
        db = _Db({"etf_holdings": [_row("SPY", "TINY", 0.02, tracked=False)]})
        with patch("services.market_data.get_client_optional", return_value=db):
            self.assertIsNone(_get_etf_holdings_db("SPY"))

    def test_holding_count_counts_tracked_rows_only(self):
        with patch("services.market_data.get_client_optional", return_value=self._db()):
            (summary,) = list_etf_summaries()
        self.assertEqual(summary["holdingCount"], 2)

    def test_the_daily_sync_counts_and_writes_tracked_holdings_only(self):
        db = self._db()
        info = {"name": "SPDR S&P 500", "cat": "Large Blend", "desc": "d"}
        live = [["AAPL", 7.5], ["TINY", 0.5]]  # TINY is Untracked: it has no ticker row
        out = io.StringIO()
        with patch.object(fetch_daily, "list_etfs", return_value=["SPY"]), \
             patch.object(fetch_daily, "_get_etf_info_live", return_value=info), \
             patch.object(fetch_daily, "_get_etf_holdings_live", return_value=live), \
             contextlib.redirect_stdout(out):
            failed = fetch_daily.sync_etfs(db, {"AAPL", "MSFT"})

        self.assertEqual(failed, [])
        self.assertEqual(db.holding("SPY", "AAPL")["weight"], 7.5)
        # the untracked row keeps its own weight and is not resurrected as tracked
        self.assertEqual(db.holding("SPY", "TINY")["weight"], 0.02)
        self.assertFalse(db.holding("SPY", "TINY")["tracked"])
        self.assertIn("   2 holdings", out.getvalue())

    def _sync(self, db, live, known):
        info = {"name": "Fund", "cat": "Blend", "desc": "d"}
        with patch.object(fetch_daily, "list_etfs", return_value=["A"]), \
             patch.object(fetch_daily, "_get_etf_info_live", return_value=info), \
             patch.object(fetch_daily, "_get_etf_holdings_live", return_value=live), \
             contextlib.redirect_stdout(io.StringIO()):
            return fetch_daily.sync_etfs(db, known)

    def test_a_new_row_for_a_stock_still_awaiting_its_backfill_is_written_untracked(self):
        """PENDING has a ticker row but every stored row of it says untracked
        (its backfill has not finished). A live top-10 weight for it in a fund
        with no stored row must not arrive as the column default `true` - that
        row would disagree with its siblings until the next completion run."""
        db = _Db({"etf_holdings": [_row("B", "PENDING", 2.0, tracked=False)]})
        self._sync(db, [["PENDING", 2.5]], {"PENDING"})

        self.assertEqual(db.holding("A", "PENDING")["weight"], 2.5)
        self.assertFalse(db.holding("A", "PENDING")["tracked"])
        self.assertFalse(db.holding("B", "PENDING")["tracked"])

    def test_a_new_row_for_a_tracked_stock_is_written_tracked(self):
        db = _Db({"etf_holdings": [_row("B", "AAPL", 2.0)]})
        self._sync(db, [["AAPL", 7.0]], {"AAPL"})
        self.assertTrue(db.holding("A", "AAPL")["tracked"])

    def test_a_hand_added_ticker_no_fund_holds_yet_is_written_tracked(self):
        db = _Db({})
        self._sync(db, [["WATCHED", 4.0]], {"WATCHED"})
        self.assertTrue(db.holding("A", "WATCHED")["tracked"])


if __name__ == "__main__":
    unittest.main()
