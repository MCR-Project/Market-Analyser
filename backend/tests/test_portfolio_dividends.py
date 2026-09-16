"""
Tests for dividend income reported beside a run (issue #68).

The whole feature is a number that must not change anything. `prices`
holds split- and dividend-adjusted closes (#13), so the income is already
inside every value the simulator reports — spent, the moment it arrived,
on more of the same holding. Reporting it is answering a second question
about the same run; adding it would be counting the same money twice.

So the cases here are mostly about restraint:

  - **Nothing moves.** The value series, the cash series, the metrics and
    every per-holding figure must come back exactly as they did before
    this existed, on a run with dividends and on a run without. Asserted
    against a run of the same portfolio with the reader silenced, so the
    comparison is the whole object rather than the fields somebody
    remembered to check.

  - **Shares at the ex-date, not shares at the start.** Under buy and
    hold the position drifts; under a rebalance it is reset; under
    contributions it grows. A dividend is paid on what was actually held
    the moment before it went ex, and the three cases give three
    different answers for the same dividend schedule.

  - **Silence is not zero.** A tracked holding with no dividend rows paid
    nothing, and says 0. An ETF has no row in `ticker` at all, so nothing
    is known about it and it says null — answering that with 0 would tell
    somebody SPY pays no dividend.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from fastapi.testclient import TestClient

from main import app
from services.portfolio import simulate_portfolio

client = TestClient(app, raise_server_exceptions=False)


def frame(columns: dict, dates: list[str]) -> pd.DataFrame:
    """A wide date x ticker close frame, shaped like get_closes returns."""
    return pd.DataFrame(columns, index=pd.to_datetime(dates))


def run(closes, holdings, dividends=None, on_record=None, value=1000.0, **kwargs):
    """Simulate with a fixed dividend record.

    `dividends` is {ticker: [(ex-date, amount per share), …]} exactly as
    get_dividends returns it, and `on_record` is which tickers the
    `ticker` table knows — defaulting to every one that pays, since a
    payer is necessarily tracked.
    """
    dividends = dividends or {}
    known = set(dividends) if on_record is None else set(on_record)
    with (
        patch("services.portfolio.get_closes", return_value=closes),
        patch("services.portfolio.get_dividends", return_value=dividends),
        patch("services.portfolio.tracked_tickers", return_value=known),
    ):
        return simulate_portfolio(
            holdings, value=value, start="2019-01-01", end="2023-12-31", **kwargs
        )


def holding(result, ticker):
    return next(h for h in result["holdings"] if h["ticker"] == ticker)


def without_income(result):
    """The run with every income field stripped, for comparing against a
    run that never had any."""
    stripped = {**result, "holdings": [dict(h) for h in result["holdings"]]}
    stripped["metrics"] = {
        key: value for key, value in result["metrics"].items()
        if key not in ("dividendIncome", "dividendYield", "incomeUnknownFor")
    }
    for entry in stripped["holdings"]:
        entry.pop("income", None)
    return stripped


# ── The value is untouched ───────────────────────────────────────────────────

class ValueUnchangedTests(unittest.TestCase):
    """The acceptance criterion this feature lives or dies by."""

    CLOSES = frame(
        {"KO": [50.0, 55.0, 52.0, 60.0], "PG": [100.0, 98.0, 105.0, 110.0]},
        ["2020-01-02", "2020-04-01", "2020-07-01", "2020-10-01"],
    )
    BASKET = [{"ticker": "KO", "weight": 60}, {"ticker": "PG", "weight": 40}]
    PAYING = {
        "KO": [("2020-03-13", 0.41), ("2020-06-12", 0.41), ("2020-09-14", 0.41)],
        "PG": [("2020-04-22", 0.79), ("2020-07-23", 0.79)],
    }

    def test_a_paying_portfolio_values_exactly_as_a_silent_one(self):
        """Same prices, same weights, same everything — one run knows
        about the dividends and one does not, and every number except the
        income itself has to match. Compared as whole objects: a field
        added later that quietly depended on the income would slip past a
        list of remembered assertions."""
        paying = run(self.CLOSES, self.BASKET, dividends=self.PAYING)
        silent = run(self.CLOSES, self.BASKET)

        self.assertEqual(without_income(paying), without_income(silent))
        # And the income was genuinely non-zero, so the comparison above
        # is not two runs that both found nothing.
        self.assertGreater(paying["metrics"]["dividendIncome"], 0)

    def test_income_is_not_added_to_the_value(self):
        """The one mistake this feature could make. 600 in KO at 50 is 12
        shares, 400 in PG at 100 is 4; at the end that is 12 x 60 + 4 x
        110 = 1160, and the dividends paid along the way are already
        inside those prices."""
        result = run(self.CLOSES, self.BASKET, dividends=self.PAYING)

        self.assertEqual(result["total"][-1], 1160.0)
        self.assertEqual(result["metrics"]["finalValue"], 1160.0)
        self.assertEqual(result["metrics"]["gain"], 160.0)
        # Income is reported beside that, not inside it.
        self.assertGreater(result["metrics"]["dividendIncome"], 0)
        self.assertNotEqual(
            result["metrics"]["finalValue"],
            1160.0 + result["metrics"]["dividendIncome"],
        )


# ── Shares held at the ex-date ───────────────────────────────────────────────

class SharesAtExDateTests(unittest.TestCase):
    def test_income_is_shares_times_dividend_on_each_ex_date(self):
        """The hand-computed case. $1,000 buys 10 shares at $100 and buy
        and hold never changes that, so two dividends of $2 and $3 pay
        10 x 2 + 10 x 3 = $50."""
        closes = frame({"KO": [100.0, 120.0, 90.0]},
                       ["2020-01-02", "2020-04-01", "2020-07-01"])

        result = run(
            closes, [{"ticker": "KO", "weight": 100}],
            dividends={"KO": [("2020-03-15", 2.0), ("2020-06-15", 3.0)]},
        )

        self.assertEqual(holding(result, "KO")["income"], 50.0)
        self.assertEqual(result["metrics"]["dividendIncome"], 50.0)
        # On $1,000 paid in.
        self.assertEqual(result["metrics"]["dividendYield"], 5.0)

    def test_a_dividend_on_the_first_row_pays_nothing(self):
        """Holding *before* the ex-date is what earns the payment, and on
        the window's first row the shares have not been bought yet — they
        are bought at that close, after the fact. Paying it would hand out
        money for a position nobody held."""
        closes = frame({"KO": [100.0, 110.0]}, ["2020-01-02", "2020-02-03"])

        result = run(
            closes, [{"ticker": "KO", "weight": 100}],
            dividends={"KO": [("2020-01-02", 5.0), ("2020-02-03", 5.0)]},
        )

        # Only the second one pays: 10 shares x $5.
        self.assertEqual(holding(result, "KO")["income"], 50.0)

    def test_a_dividend_before_the_window_is_not_paid(self):
        """get_dividends filters to the window, but a stray earlier event
        must not be credited either — the position did not exist."""
        closes = frame({"KO": [100.0, 110.0]}, ["2020-01-02", "2020-02-03"])

        result = run(
            closes, [{"ticker": "KO", "weight": 100}],
            dividends={"KO": [("2019-06-01", 9.0), ("2020-02-03", 1.0)]},
        )

        self.assertEqual(holding(result, "KO")["income"], 10.0)

    def test_a_late_listing_holding_earns_nothing_while_it_is_cash(self):
        """An allocation waiting in cash for its holding to list owns no
        shares, so a dividend in that stretch pays nothing. It starts
        earning at the first close it has."""
        closes = frame(
            {"OLD": [100.0, 100.0, 100.0], "NEW": [float("nan"), 50.0, 50.0]},
            ["2020-01-02", "2020-04-01", "2020-07-01"],
        )

        result = run(
            closes,
            [{"ticker": "OLD", "weight": 50}, {"ticker": "NEW", "weight": 50}],
            dividends={"NEW": [("2020-02-01", 1.0), ("2020-05-01", 1.0)]},
            on_record={"OLD", "NEW"},
        )

        # February: still cash, nothing. May: 500 bought 10 shares at 50,
        # so $10.
        self.assertEqual(holding(result, "NEW")["income"], 10.0)
        self.assertEqual(holding(result, "OLD")["income"], 0.0)

    def test_a_rebalance_changes_what_the_next_dividend_pays(self):
        """The case that makes "shares at the ex-date" more than a
        phrasing. KO doubles in Q1, so buy and hold leaves 12 shares while
        a rebalance sells some back — and the dividend that follows pays
        on whichever number is actually held."""
        closes = frame(
            {"KO": [50.0, 100.0, 100.0], "PG": [100.0, 100.0, 100.0]},
            ["2020-01-02", "2020-02-03", "2020-03-02"],
        )
        basket = [{"ticker": "KO", "weight": 60}, {"ticker": "PG", "weight": 40}]
        paying = {"KO": [("2020-03-01", 1.0)]}

        held = run(closes, basket, dividends=paying, on_record={"KO", "PG"})
        balanced = run(closes, basket, dividends=paying, on_record={"KO", "PG"},
                       rebalance="monthly")

        # Buy and hold: 600 at 50 is 12 shares, still 12 when KO goes ex.
        self.assertEqual(holding(held, "KO")["income"], 12.0)
        # Rebalanced in February: the basket is worth 1600, KO's 60% is
        # 960, which at 100 is 9.6 shares.
        self.assertEqual(holding(balanced, "KO")["income"], 9.6)

    def test_contributions_buy_shares_that_then_earn(self):
        """Money paid in (#67) buys shares like any other, and they are
        held at the next ex-date."""
        closes = frame({"KO": [100.0, 100.0, 100.0]},
                       ["2020-01-02", "2020-02-03", "2020-03-02"])

        result = run(
            closes, [{"ticker": "KO", "weight": 100}],
            dividends={"KO": [("2020-01-15", 1.0), ("2020-02-15", 1.0)]},
            contribution={"amount": 500, "frequency": "monthly"},
        )

        # The 15 January dividend is reached on the February row and pays
        # on the 10 shares held going into it. February's $500 buys 5
        # more; the 15 February dividend is reached on the March row and
        # pays on all 15. Total $25.
        self.assertEqual(holding(result, "KO")["income"], 25.0)
        self.assertEqual(result["metrics"]["dividendIncome"], 25.0)
        # Yield is on everything paid in — $1,000 plus two contributions,
        # so $25 on $2,000 is 1.25%. Divided by the opening amount alone
        # it would read 2.5%, crediting the deposits with the income they
        # earned while pretending they were never made.
        self.assertEqual(result["metrics"]["totalInvested"], 2000.0)
        self.assertEqual(result["metrics"]["dividendYield"], 1.25)


# ── Silence is not zero ──────────────────────────────────────────────────────

class UnknownIncomeTests(unittest.TestCase):
    CLOSES = frame({"SPY": [100.0, 110.0]}, ["2020-01-02", "2020-02-03"])

    def test_a_tracked_holding_with_no_events_reports_zero(self):
        """It is on record and the record is empty, which is a real
        answer: it paid nothing."""
        result = run(
            self.CLOSES, [{"ticker": "SPY", "weight": 100}],
            dividends={}, on_record={"SPY"},
        )

        self.assertEqual(holding(result, "SPY")["income"], 0.0)
        self.assertEqual(result["metrics"]["dividendIncome"], 0.0)
        self.assertEqual(result["metrics"]["dividendYield"], 0.0)
        self.assertEqual(result["metrics"]["incomeUnknownFor"], [])

    def test_an_untracked_holding_reports_that_it_does_not_know(self):
        """ETFs live in `etfs` and never get a `ticker` row, so the
        dividend table has nothing to say about SPY. Answering that with
        0.0 would state, in a figure, that SPY pays no dividend."""
        result = run(
            self.CLOSES, [{"ticker": "SPY", "weight": 100}],
            dividends={}, on_record=set(),
        )

        self.assertIsNone(holding(result, "SPY")["income"])
        self.assertEqual(result["metrics"]["incomeUnknownFor"], ["SPY"])
        # Nothing is known, so the total is zero and the caller is told
        # which holdings it could not include rather than being handed a
        # confident nought.
        self.assertEqual(result["metrics"]["dividendIncome"], 0.0)

    def test_a_partly_known_basket_names_what_it_left_out(self):
        closes = frame(
            {"KO": [100.0, 100.0], "SPY": [100.0, 100.0]},
            ["2020-01-02", "2020-02-03"],
        )

        result = run(
            closes,
            [{"ticker": "KO", "weight": 50}, {"ticker": "SPY", "weight": 50}],
            dividends={"KO": [("2020-02-01", 2.0)]},
            on_record={"KO"},
        )

        # 500 at 100 is 5 shares, x $2.
        self.assertEqual(holding(result, "KO")["income"], 10.0)
        self.assertIsNone(holding(result, "SPY")["income"])
        self.assertEqual(result["metrics"]["dividendIncome"], 10.0)
        self.assertEqual(result["metrics"]["incomeUnknownFor"], ["SPY"])

    def test_a_zero_amount_is_not_an_event(self):
        """get_dividends drops these, but the engine must not credit one
        if a row ever slips through: paying 0 is not being paid."""
        result = run(
            self.CLOSES, [{"ticker": "SPY", "weight": 100}],
            dividends={"SPY": [("2020-02-01", 0.0)]}, on_record={"SPY"},
        )

        self.assertEqual(holding(result, "SPY")["income"], 0.0)


# ── Through the endpoint ─────────────────────────────────────────────────────

class DividendRouteTests(unittest.TestCase):
    """The response carries income beside the series, on a run that goes
    through the real route rather than the engine directly."""

    class _Prices:
        ROWS = [
            {"ticker": "KO", "date": "2020-01-02", "close": 100.0},
            {"ticker": "KO", "date": "2020-06-01", "close": 120.0},
        ]

        def table(self, name):
            self.name = name
            return self

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def in_(self, *_args, **_kwargs):
            return self

        def gte(self, *_args, **_kwargs):
            return self

        def lte(self, *_args, **_kwargs):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def range(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def execute(self):
            from types import SimpleNamespace

            if self.name == "dividends":
                return SimpleNamespace(
                    data=[{"ticker": "KO", "date": "2020-03-01", "dividends": 2.0}]
                )
            if self.name == "ticker":
                return SimpleNamespace(data=[{"id": "KO"}])
            # get_risk_free_rate also reaches this fake now (issue #112) -
            # empty, not self.ROWS (which has no "rate" column), so it
            # answers None the same honest way an unsynced table would.
            if self.name == "risk_free_rate":
                return SimpleNamespace(data=[])
            return SimpleNamespace(data=self.ROWS)

    def test_the_response_reports_income_without_moving_the_value(self):
        body = {
            "holdings": [{"ticker": "KO", "weight": 100}],
            "value": 10_000,
            "start": "2020-01-01",
            "end": "2020-12-31",
        }
        with patch("services.market_data.get_client_optional", return_value=self._Prices()):
            resp = client.post("/api/portfolio/simulate", json=body)

        self.assertEqual(resp.status_code, 200)
        metrics = resp.json()["metrics"]
        # 100 shares at 100, worth 120 each at the end.
        self.assertEqual(metrics["finalValue"], 12_000.0)
        # 100 shares x $2, reported and not added.
        self.assertEqual(metrics["dividendIncome"], 200.0)
        self.assertEqual(metrics["dividendYield"], 2.0)
        self.assertEqual(metrics["incomeUnknownFor"], [])
        self.assertEqual(resp.json()["holdings"][0]["income"], 200.0)


if __name__ == "__main__":
    unittest.main()
