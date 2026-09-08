"""
Tests for pricing a basket Supabase only partly holds (issue #86).

`_closes_db` returns a frame as soon as it has `min_tickers` columns, so
one tracked holding was enough for an untracked one — every ETF, since
those live in `etfs` and never get `prices` rows — to be left out of the
frame entirely. Downstream that was not read as a missing column but as a
wrong answer: the simulator took the absence for a holding that had not
listed yet and valued it at zero for the whole run, reporting the
difference as cash.

Two halves, and both matter:

  - **The merge.** The columns the database could not answer for are
    fetched live and put onto the calendar the database frame already
    uses. `prices` tiers history by age, and a bucket's `close` is its
    *last* close while its `date` is its *anchor* — the Monday, the 1st.
    Those are different days, so aligning by "the last live value at or
    before each anchor" puts the merged column a whole bucket behind the
    ones it is joining. Against real data that error is up to 33% on half
    the rows, and it is completely invisible: the column is populated, the
    chart is smooth, every number is wrong. Most of this file is about
    that one off-by-one.

  - **The guard.** Whatever the read manages, the simulator must not go
    on treating an absent column as cash when the holding demonstrably has
    prices older than the window. Three situations look identical from the
    price read alone and need three different answers, and the resolver is
    what tells them apart.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from services.market_data import (
    DataUnavailable,
    SymbolNotFound,
    _onto_calendar,
    get_closes,
)
from services.portfolio import simulate_portfolio


def frame(columns: dict, dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns, index=pd.to_datetime(dates))


# ── Putting a daily series onto a bucketed calendar ──────────────────────────

class CalendarAlignmentTests(unittest.TestCase):
    """The off-by-one that would be invisible if it were wrong."""

    # A fortnight of weekdays, closing at 100, 101, 102 … so every date is
    # identifiable from its value alone.
    DAILY = frame(
        {"SPY": [100.0 + i for i in range(10)]},
        ["2021-09-13", "2021-09-14", "2021-09-15", "2021-09-16", "2021-09-17",
         "2021-09-20", "2021-09-21", "2021-09-22", "2021-09-23", "2021-09-24"],
    )

    def test_a_weekly_anchor_takes_that_weeks_closing_price(self):
        """The whole point. A weekly bucket is dated on its Monday and
        holds the Friday close, so the anchor 2021-09-13 must take Friday
        the 17th's 104 — not Monday's own 100, and emphatically not the
        previous Friday's."""
        weekly = pd.to_datetime(["2021-09-13", "2021-09-20"])

        aligned = _onto_calendar(self.DAILY, weekly)

        self.assertEqual(list(aligned["SPY"]), [104.0, 109.0])

    def test_daily_anchors_take_their_own_close(self):
        """The same rule with buckets one row wide, which is what lets one
        implementation serve all three tiers. A real daily calendar names
        every trading day, so each bucket contains exactly its own row and
        "the last close inside the bucket" is that day's close."""
        aligned = _onto_calendar(self.DAILY, self.DAILY.index)

        self.assertEqual(list(aligned["SPY"]), list(self.DAILY["SPY"]))

    def test_a_gap_in_the_calendar_widens_the_bucket_before_it(self):
        """Stated rather than discovered. A bucket runs from its anchor to
        the next one, so a calendar that skips days makes the preceding
        bucket wider - the merged value is the last close before the next
        anchor, not the anchor's own.

        For the calendars this actually meets that is a distinction
        without a difference: two US-listed securities share their trading
        days, so a daily frame's gaps are weekends and holidays where the
        live series has no row either. Merging a real tracked ticker onto
        a real tiered frame reproduces what the database itself stored to
        within 0.0008%.
        """
        gappy = pd.to_datetime(["2021-09-14", "2021-09-16", "2021-09-21"])

        aligned = _onto_calendar(self.DAILY, gappy)

        # 09-14 covers the 14th and 15th; 09-16 covers the 16th to the
        # 20th; 09-21 is last, so it runs to the end of the series.
        self.assertEqual(list(aligned["SPY"]), [102.0, 105.0, 109.0])

    def test_a_monthly_anchor_takes_the_months_last_close(self):
        monthly = pd.to_datetime(["2021-09-01"])

        aligned = _onto_calendar(self.DAILY, monthly)

        self.assertEqual(list(aligned["SPY"]), [109.0])

    def test_live_dates_before_the_first_anchor_are_dropped(self):
        """There is no bucket for them, and the frame being merged into
        does not reach back that far."""
        later = pd.to_datetime(["2021-09-20"])

        aligned = _onto_calendar(self.DAILY, later)

        # Only the second week's rows count; the first week is outside.
        self.assertEqual(list(aligned["SPY"]), [109.0])

    def test_an_anchor_with_no_live_rows_inside_it_is_empty(self):
        """A gap in the live series is a gap, not the previous bucket's
        price wearing this bucket's date."""
        weekly = pd.to_datetime(["2021-09-06", "2021-09-13", "2021-09-20"])

        aligned = _onto_calendar(self.DAILY, weekly)

        # Nothing live before the 13th, so the first week stays empty.
        self.assertTrue(pd.isna(aligned["SPY"].iloc[0]))
        self.assertEqual(aligned["SPY"].iloc[1], 104.0)

    def test_the_last_anchor_runs_to_the_end_of_the_live_series(self):
        """It has no next anchor to stop at, so it takes the freshest
        close it has — which is what that bucket will hold once the daily
        fetch compacts it."""
        weekly = pd.to_datetime(["2021-09-13", "2021-09-20"])

        aligned = _onto_calendar(self.DAILY, weekly)

        self.assertEqual(aligned["SPY"].iloc[-1], 109.0)

    def test_the_naive_alignment_would_be_wrong(self):
        """Pinned so the cheap implementation cannot quietly come back:
        reindexing with a forward fill takes the close from *before* each
        bucket began."""
        weekly = pd.to_datetime(["2021-09-13", "2021-09-20"])

        correct = _onto_calendar(self.DAILY, weekly)["SPY"]
        naive = self.DAILY.reindex(weekly, method="ffill")["SPY"]

        self.assertEqual(list(correct), [104.0, 109.0])
        self.assertEqual(list(naive), [100.0, 105.0])   # a bucket behind
        self.assertFalse(correct.equals(naive))


# ── The merge ────────────────────────────────────────────────────────────────

class MergeTests(unittest.TestCase):
    DATES = ["2021-09-13", "2021-09-20", "2021-09-27"]

    def _get(self, db, live, tickers):
        with (
            patch("services.market_data._closes_db", return_value=db),
            patch("services.market_data._closes_live", return_value=live),
        ):
            return get_closes(tickers, start="2021-09-01", end="2021-10-01", min_tickers=1)

    def test_a_column_the_database_lacks_is_fetched_and_merged(self):
        db = frame({"TXN": [10.0, 11.0, 12.0]}, self.DATES)
        live = frame({"SPY": [100.0, 200.0, 300.0]}, self.DATES)

        merged = self._get(db, live, ["TXN", "SPY"])

        self.assertEqual(sorted(merged.columns), ["SPY", "TXN"])
        self.assertEqual(list(merged["TXN"]), [10.0, 11.0, 12.0])
        self.assertEqual(list(merged["SPY"]), [100.0, 200.0, 300.0])
        # The database's calendar is kept; the live series comes to it.
        self.assertEqual(list(merged.index), list(pd.to_datetime(self.DATES)))

    def test_the_merged_column_lands_on_the_databases_calendar(self):
        """The live series is daily and the database frame is weekly, so
        each merged value is that week's last close."""
        db = frame({"TXN": [10.0, 11.0]}, ["2021-09-13", "2021-09-20"])
        live = frame(
            {"SPY": [100.0, 104.0, 200.0, 209.0]},
            ["2021-09-13", "2021-09-17", "2021-09-20", "2021-09-24"],
        )

        merged = self._get(db, live, ["TXN", "SPY"])

        self.assertEqual(list(merged["SPY"]), [104.0, 209.0])

    def test_a_full_database_answer_is_not_touched(self):
        """No live call at all when nothing is missing - the merge must
        not turn every basket into an upstream fetch."""
        db = frame({"TXN": [10.0], "NVDA": [20.0]}, ["2021-09-13"])

        with (
            patch("services.market_data._closes_db", return_value=db),
            patch("services.market_data._closes_live") as live,
        ):
            merged = get_closes(["TXN", "NVDA"], start="2021-09-01", end="2021-10-01",
                                min_tickers=1)

        live.assert_not_called()
        self.assertEqual(sorted(merged.columns), ["NVDA", "TXN"])

    def test_only_the_missing_tickers_are_asked_for(self):
        db = frame({"TXN": [10.0], "NVDA": [20.0]}, ["2021-09-13"])
        live = frame({"SPY": [100.0]}, ["2021-09-13"])

        with (
            patch("services.market_data._closes_db", return_value=db),
            patch("services.market_data._closes_live", return_value=live) as fetch,
        ):
            get_closes(["TXN", "NVDA", "SPY"], start="2021-09-01", end="2021-10-01",
                       min_tickers=1)

        self.assertEqual(fetch.call_args.args[0], ["SPY"])

    def test_a_symbol_with_no_live_rows_stays_absent(self):
        """Not an error here: absent still means one thing, and the
        simulator is what decides whether that is cash or a failure."""
        db = frame({"TXN": [10.0, 11.0]}, ["2021-09-13", "2021-09-20"])

        merged = self._get(db, None, ["TXN", "GONE"])

        self.assertEqual(list(merged.columns), ["TXN"])

    def test_an_all_empty_merged_column_is_left_out(self):
        """A live frame with the column present but nothing in it says as
        little as no column at all, and must not read as a priced holding
        worth nothing."""
        db = frame({"TXN": [10.0, 11.0]}, ["2021-09-13", "2021-09-20"])
        live = frame({"SPY": [float("nan"), float("nan")]}, ["2021-09-13", "2021-09-20"])

        merged = self._get(db, live, ["TXN", "SPY"])

        self.assertEqual(list(merged.columns), ["TXN"])

    def test_nothing_from_the_database_still_goes_live_for_everything(self):
        """The original fallback, untouched."""
        live = frame({"SPY": [100.0], "QQQ": [200.0]}, ["2021-09-13"])

        merged = self._get(None, live, ["SPY", "QQQ"])

        self.assertEqual(sorted(merged.columns), ["QQQ", "SPY"])


# ── What an absent column means ──────────────────────────────────────────────

class AbsentHoldingTests(unittest.TestCase):
    """Three situations that look identical from the price read, and the
    three different answers they need."""

    CLOSES = frame({"OLD": [100.0, 120.0]}, ["2020-01-02", "2020-06-01"])
    BASKET = [{"ticker": "OLD", "weight": 50}, {"ticker": "GHOST", "weight": 50}]

    def _run(self, resolved):
        with (
            patch("services.portfolio.get_closes", return_value=self.CLOSES),
            patch("services.portfolio.get_dividends", return_value={}),
            patch("services.portfolio.tracked_tickers", return_value=set()),
            patch("services.portfolio.resolve_ticker", side_effect=resolved),
        ):
            return simulate_portfolio(
                self.BASKET, value=1000.0, start="2020-01-01", end="2020-12-31"
            )

    def test_a_holding_that_had_not_listed_is_still_cash(self):
        """The #56 rule, untouched: history starting after the window is
        exactly why the window has none of it."""
        result = self._run(lambda t: {"symbol": t, "firstDate": "2021-03-01"})

        self.assertEqual(result["cash"], [500.0, 500.0])
        ghost = next(h for h in result["holdings"] if h["ticker"] == "GHOST")
        self.assertEqual(ghost["values"], [0.0, 0.0])
        self.assertIsNone(ghost["firstDate"])

    def test_a_holding_with_older_prices_is_refused(self):
        """There is no reading of "has prices since 1993, none here" where
        the right answer is to value it at zero and call it cash. It is a
        failed read, and 503 says so - retryable, because the upstream that
        should have supplied those prices is what failed."""
        with self.assertRaises(DataUnavailable) as caught:
            self._run(lambda t: {"symbol": t, "firstDate": "1993-01-29"})

        self.assertIn("GHOST", str(caught.exception))
        self.assertIn("1993-01-29", str(caught.exception))

    def test_a_holding_with_no_history_at_all_still_404s(self):
        """The #58 rule, untouched."""
        def typo(ticker):
            raise SymbolNotFound(f"no price history for '{ticker}'")

        with self.assertRaises(SymbolNotFound):
            self._run(typo)

    def test_a_holding_listing_on_the_first_row_is_not_refused(self):
        """The boundary: `firstDate` equal to the window's start is not
        older than it, so this is a late lister and not a failed read."""
        result = self._run(lambda t: {"symbol": t, "firstDate": "2020-01-02"})

        self.assertEqual(result["cash"], [500.0, 500.0])


if __name__ == "__main__":
    unittest.main()
