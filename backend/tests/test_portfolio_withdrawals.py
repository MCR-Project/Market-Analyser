"""
Tests for recurring withdrawals (issue #150).

A withdrawal is the mirror of a recurring contribution (issue #67, see
test_portfolio_contributions.py) and inherits its timing rule, but it is not
its sign flipped: money leaving has to come *from* somewhere, and it can run
out. So what is pinned down here is the parts that have no counterpart on the
paying-in side:

  - **Cash leaving is not a loss.** Taking $100 a month out of a portfolio
    whose prices never move must leave the return, the volatility and the
    drawdown at zero. Read straight off the total, the same run reports a
    slide.

  - **It comes out pro rata.** Every holding, and any cash still waiting for
    a holding to list, gives up the same fraction of its current value, so a
    withdrawal changes how much the portfolio holds and never what the mix
    is. Spreading it over the *target* weights the way a contribution is
    would try to sell more of a holding than it is now worth.

  - **It can run out, and says so.** A withdrawal the portfolio cannot cover
    takes what is left, and every figure downstream uses what was actually
    taken - never what was scheduled.

  - **One schedule at most** (ADR 0002). Paying in and drawing out at once is
    refused rather than guessed at.

Expected numbers are arithmetic a reader can check by hand, on synthetic
price frames like the contribution tests use.

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
from rate_limit import FixedWindowLimiter
from services.portfolio import DAYS_PER_YEAR, simulate_portfolio

client = TestClient(app, raise_server_exceptions=False)


def frame(columns: dict, dates: list[str]) -> pd.DataFrame:
    """A wide date x ticker close frame, shaped like get_closes returns."""
    return pd.DataFrame(columns, index=pd.to_datetime(dates))


def run(closes, holdings, value=1000.0, rebalance="none", withdrawal=None, **kwargs):
    # Patched for the same reason test_portfolio_contributions.run is:
    # dividends are a separate read, and leaving it unpatched reaches for
    # Supabase. The risk-free rate is a third (issue #112) - read once per
    # run to score Sharpe and Sortino, which nothing here asserts on.
    with (
        patch("services.portfolio.get_closes", return_value=closes),
        patch("services.portfolio.get_dividends", return_value={}),
        patch("services.portfolio.tracked_tickers", return_value=set()),
        patch("services.portfolio.get_risk_free_rate", return_value=None),
    ):
        return simulate_portfolio(
            holdings, value=value, start="2019-01-01", end="2023-12-31",
            rebalance=rebalance, withdrawal=withdrawal, **kwargs
        )


def holding(result, ticker):
    return next(h for h in result["holdings"] if h["ticker"] == ticker)


MONTHLY_100 = {"amount": 100, "frequency": "monthly"}


def npv(rate_percent: float, flows: list[tuple[str, float]]) -> float:
    """Present value of `flows` at an annual rate, computed here rather
    than imported, so a wrong discounting convention in the engine cannot
    be confirmed by the same wrong convention in the test."""
    origin = pd.Timestamp(flows[0][0])
    rate = rate_percent / 100
    return sum(
        amount / (1 + rate) ** ((pd.Timestamp(date) - origin).days / DAYS_PER_YEAR)
        for date, amount in flows
    )


# Rates are reported to PERCENT_DP, so discounting thousands of dollars back
# at the *rounded* rate lands near zero rather than on it. A cent is the
# honest tolerance: any larger residual is a wrong rate, not a rounded one.
NPV_TOLERANCE = 0.01


# ── Off by default ───────────────────────────────────────────────────────────

class WithdrawalsOffTests(unittest.TestCase):
    """The existing behaviour has to survive the feature untouched."""

    CLOSES = frame(
        {"NVDA": [100.0, 110.0, 90.0, 120.0], "AMD": [50.0, 55.0, 60.0, 40.0]},
        ["2020-01-02", "2020-02-03", "2020-03-02", "2020-04-01"],
    )
    BASKET = [{"ticker": "NVDA", "weight": 60}, {"ticker": "AMD", "weight": 40}]

    def test_no_withdrawal_null_and_zero_are_the_same_run(self):
        """Four ways of saying "no schedule", and they must not be four
        slightly different simulations."""
        absent = run(self.CLOSES, self.BASKET)
        null = run(self.CLOSES, self.BASKET, withdrawal=None)
        zero = run(self.CLOSES, self.BASKET, withdrawal={"amount": 0, "frequency": None})
        # An amount of zero with a frequency named is still off: nothing is
        # taken, so the schedule has nothing to schedule.
        scheduled_zero = run(
            self.CLOSES, self.BASKET, withdrawal={"amount": 0, "frequency": "monthly"}
        )

        self.assertEqual(absent, null)
        self.assertEqual(absent, zero)
        self.assertEqual(absent, scheduled_zero)
        self.assertIsNone(absent["withdrawal"])
        self.assertIsNone(absent["withdrawn"])

    def test_an_untouched_run_reports_nothing_taken_out(self):
        result = run(self.CLOSES, self.BASKET)

        self.assertEqual(result["metrics"]["withdrawn"], 0.0)
        self.assertIsNone(result["metrics"]["depletedOn"])
        self.assertEqual(
            result["metrics"]["gain"], round(result["metrics"]["finalValue"] - 1000.0, 2)
        )
        # No schedule of either kind, so nothing moved the flow-free series
        # away from the total.
        self.assertIsNone(result["unitValue"])


# ── Where the money leaves, and what it is not ───────────────────────────────

class WithdrawalScheduleTests(unittest.TestCase):
    FLAT = frame(
        {"NVDA": [100.0] * 5},
        ["2020-01-02", "2020-01-15", "2020-02-03", "2020-02-20", "2020-03-02"],
    )

    def test_money_leaves_on_the_first_row_of_each_new_month(self):
        """The window's own first row is the opening amount, never a
        withdrawal - so a five-row window spanning three months takes two,
        not three."""
        result = run(self.FLAT, [{"ticker": "NVDA", "weight": 100}], withdrawal=MONTHLY_100)

        self.assertEqual(result["total"], [1000.0, 1000.0, 900.0, 900.0, 800.0])
        # Rows 2 and 4: the first row of February, and the first of March.
        self.assertEqual(result["withdrawn"], [0.0, 0.0, 100.0, 100.0, 200.0])
        self.assertEqual(result["withdrawal"], {"amount": 100.0, "frequency": "monthly"})
        self.assertEqual(result["metrics"]["withdrawn"], 200.0)
        # Nothing is ever paid in beyond the opening amount.
        self.assertEqual(result["metrics"]["contributed"], 0.0)
        self.assertEqual(result["metrics"]["totalInvested"], 1000.0)
        self.assertEqual(result["invested"], [1000.0] * 5)

    def test_taking_money_out_of_a_flat_portfolio_reports_no_loss_and_no_risk(self):
        """A withdrawal is not a loss: read straight off the total, a $100
        step down out of $1,000 is a 10% fall on a day the market did
        nothing, and it would land in the return, the volatility and the
        drawdown."""
        result = run(self.FLAT, [{"ticker": "NVDA", "weight": 100}], withdrawal=MONTHLY_100)
        metrics = result["metrics"]

        self.assertEqual(metrics["totalReturn"], 0.0)
        self.assertEqual(metrics["volatility"], 0.0)
        self.assertEqual(metrics["maxDrawdown"]["value"], 0.0)
        # ...and it is not a gain either: it was spent, not earned.
        self.assertEqual(metrics["gain"], 0.0)
        # The flow-free series is published, because it now differs from the
        # total - which is what tells the comparison chart to use it.
        self.assertEqual(result["unitValue"], [1000.0] * 5)


# ── Running out ──────────────────────────────────────────────────────────────

class RunningOutTests(unittest.TestCase):
    """Shorting is not modelled, so a withdrawal the portfolio cannot cover
    takes what is left and nothing after that. The run keeps its window: it
    is a real answer to "would this have lasted", and shortening it would
    break a like-for-like comparison against a line that did."""

    MONTHS = frame(
        {"NVDA": [100.0] * 5},
        ["2020-01-02", "2020-02-03", "2020-03-02", "2020-04-01", "2020-05-01"],
    )

    def test_a_withdrawal_it_cannot_cover_takes_what_is_left(self):
        result = run(
            self.MONTHS, [{"ticker": "NVDA", "weight": 100}],
            withdrawal={"amount": 600, "frequency": "monthly"},
        )

        # February takes 600 of 1,000. March is asked for 600 and can give
        # only the 400 that is left. April and May find nothing to take.
        self.assertEqual(result["total"], [1000.0, 400.0, 0.0, 0.0, 0.0])
        self.assertEqual(result["withdrawn"], [0.0, 600.0, 1000.0, 1000.0, 1000.0])
        # What was actually taken, not what was scheduled: 4 x 600 is 2,400.
        self.assertEqual(result["metrics"]["withdrawn"], 1000.0)
        self.assertEqual(result["metrics"]["depletedOn"], "2020-03-02")
        self.assertEqual(result["metrics"]["gain"], 0.0)

    def test_a_withdrawal_that_exactly_empties_it_is_the_day_it_ran_out(self):
        """The balance is gone on that row whether or not the amount asked
        for was more than it held."""
        result = run(
            self.MONTHS, [{"ticker": "NVDA", "weight": 100}],
            withdrawal={"amount": 500, "frequency": "monthly"},
        )

        self.assertEqual(result["total"], [1000.0, 500.0, 0.0, 0.0, 0.0])
        self.assertEqual(result["metrics"]["withdrawn"], 1000.0)
        self.assertEqual(result["metrics"]["depletedOn"], "2020-03-02")

    def test_a_portfolio_that_never_runs_out_has_no_date_for_it(self):
        """Null here means "did not run out" - never "unknown"."""
        result = run(
            self.MONTHS, [{"ticker": "NVDA", "weight": 100}],
            withdrawal={"amount": 100, "frequency": "monthly"},
        )

        self.assertEqual(result["total"], [1000.0, 900.0, 800.0, 700.0, 600.0])
        self.assertIsNone(result["metrics"]["depletedOn"])

    def test_running_out_is_not_a_loss_to_the_portfolio(self):
        """The unit value only moves when prices do, so a portfolio drawn to
        nothing on flat prices has neither risen nor fallen - which is why
        `depletedOn` has to exist: nothing else here says the money is
        gone."""
        result = run(
            self.MONTHS, [{"ticker": "NVDA", "weight": 100}],
            withdrawal={"amount": 600, "frequency": "monthly"},
        )

        self.assertEqual(result["metrics"]["totalReturn"], 0.0)
        self.assertEqual(result["metrics"]["maxDrawdown"]["value"], 0.0)


# ── Refusals ─────────────────────────────────────────────────────────────────

class WithdrawalValidationTests(unittest.TestCase):
    CLOSES = frame({"NVDA": [100.0, 110.0]}, ["2020-01-02", "2020-02-03"])
    BASKET = [{"ticker": "NVDA", "weight": 100}]

    def test_paying_in_and_drawing_out_at_once_is_refused(self):
        """ADR 0002: a portfolio does one or the other. The money-weighted
        return is only guaranteed a single answer while the flows change
        sign once, and a deposit and a withdrawal in the same month mostly
        cancel out anyway."""
        with self.assertRaises(ValueError) as caught:
            run(self.CLOSES, self.BASKET, withdrawal=MONTHLY_100,
                contribution={"amount": 50, "frequency": "monthly"})
        message = str(caught.exception)
        self.assertIn("contribution", message)
        self.assertIn("withdrawal", message)

    def test_an_empty_contribution_beside_a_withdrawal_is_not_a_second_schedule(self):
        """Zero and null mean off, so they are not "both"."""
        for off in (None, {"amount": 0, "frequency": None}):
            with self.subTest(contribution=off):
                result = run(self.CLOSES, self.BASKET, withdrawal=MONTHLY_100, contribution=off)
                self.assertEqual(result["withdrawal"], {"amount": 100.0, "frequency": "monthly"})

    def test_an_amount_without_a_frequency_is_refused(self):
        """"$100" is not a schedule, and choosing one for the caller would
        take money out of their portfolio on dates they never named."""
        with self.assertRaises(ValueError) as caught:
            run(self.CLOSES, self.BASKET, withdrawal={"amount": 100})
        self.assertIn("withdrawal.frequency", str(caught.exception))

    def test_an_unknown_frequency_is_refused_by_name(self):
        with self.assertRaises(ValueError) as caught:
            run(self.CLOSES, self.BASKET,
                withdrawal={"amount": 100, "frequency": "fortnightly"})
        self.assertIn("fortnightly", str(caught.exception))

    def test_a_negative_withdrawal_is_refused_and_points_at_the_other_schedule(self):
        with self.assertRaises(ValueError) as caught:
            run(self.CLOSES, self.BASKET,
                withdrawal={"amount": -100, "frequency": "monthly"})
        message = str(caught.exception)
        self.assertIn("negative", message)
        self.assertIn("contribution", message)

    def test_a_negative_contribution_is_refused_and_points_at_withdrawal(self):
        """Money going out used to be "not modelled"; now it is, and it has
        its own field. A sign on the contribution is not how it is said - an
        older build reads an amount at or below zero as no schedule at all
        (ADR 0002)."""
        with self.assertRaises(ValueError) as caught:
            run(self.CLOSES, self.BASKET,
                contribution={"amount": -100, "frequency": "monthly"})
        message = str(caught.exception)
        self.assertIn("negative", message)
        self.assertIn("`withdrawal`", message)

    def test_an_amount_that_is_not_a_number_is_refused(self):
        for bad in ("100", True, float("nan"), float("inf")):
            with self.subTest(amount=bad):
                with self.assertRaises(ValueError):
                    run(self.CLOSES, self.BASKET,
                        withdrawal={"amount": bad, "frequency": "monthly"})

    def test_something_that_is_not_an_object_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            run(self.CLOSES, self.BASKET, withdrawal=100)
        self.assertIn("withdrawal", str(caught.exception))


# ── Where it comes out of ────────────────────────────────────────────────────

class WhereItComesOutOfTests(unittest.TestCase):
    """NVDA doubles while AMD stands still, so by February a 60/40 buy and
    hold is 1,200 NVDA against 400 AMD - 75/25 - and the target weights no
    longer describe what is held."""

    DRIFTED = frame(
        {"NVDA": [100.0, 200.0], "AMD": [50.0, 50.0]},
        ["2020-01-02", "2020-02-03"],
    )
    BASKET = [{"ticker": "NVDA", "weight": 60}, {"ticker": "AMD", "weight": 40}]
    TAKE_160 = {"amount": 160, "frequency": "monthly"}

    def test_every_holding_gives_up_the_same_fraction_of_what_it_is_worth(self):
        """160 of 1,600 is a tenth, so each holding is a tenth smaller and
        the 75/25 mix survives. Taken over the 60/40 *targets* it would be
        96 from NVDA and 64 from AMD, which leaves 1,104 against 336: a
        mix nobody chose."""
        result = run(self.DRIFTED, self.BASKET, withdrawal=self.TAKE_160)

        self.assertEqual(holding(result, "NVDA")["values"], [600.0, 1080.0])
        self.assertEqual(holding(result, "AMD")["values"], [400.0, 360.0])
        self.assertEqual(result["total"], [1000.0, 1440.0])

    def test_a_holdings_gain_adds_back_what_was_taken_out_of_it(self):
        """NVDA: worth 1,080, 120 taken out of it, 600 put in - it made
        600. AMD: worth 360, 40 taken out, 400 put in - it made nothing,
        whatever a smaller final value suggests. The two add up to the
        portfolio's own gain."""
        result = run(self.DRIFTED, self.BASKET, withdrawal=self.TAKE_160)

        self.assertEqual(holding(result, "NVDA")["contribution"], 600.0)
        self.assertEqual(holding(result, "AMD")["contribution"], 0.0)
        self.assertEqual(result["metrics"]["gain"], 600.0)
        self.assertEqual(
            sum(h["contribution"] for h in result["holdings"]), result["metrics"]["gain"]
        )

    def test_a_rebalance_on_the_same_row_restores_the_targets_from_what_is_left(self):
        """The withdrawal lands first, in the slot a contribution uses, so
        the targets are restored from 1,440 rather than sold down to from
        1,600 and then drawn on."""
        result = run(self.DRIFTED, self.BASKET, rebalance="monthly", withdrawal=self.TAKE_160)

        # 60% and 40% of 1,440.
        self.assertEqual(holding(result, "NVDA")["values"], [600.0, 864.0])
        self.assertEqual(holding(result, "AMD")["values"], [400.0, 576.0])
        self.assertEqual(result["metrics"]["gain"], 600.0)
        self.assertEqual(
            sum(h["contribution"] for h in result["holdings"]), result["metrics"]["gain"]
        )

    def test_cash_waiting_for_a_holding_to_list_gives_up_its_share_too(self):
        """NEW has no price until March, so half the money sits in cash.
        February's 100 comes off the whole 1,000 - 50 from each half - and
        what is left of the waiting cash (450) buys in when NEW lists, at
        that day's close, without moving the total. March's own 100 then
        comes off the two priced holdings, 50 from each."""
        closes = frame(
            {"NVDA": [100.0, 100.0, 100.0], "NEW": [float("nan"), float("nan"), 10.0]},
            ["2020-01-02", "2020-02-03", "2020-03-02"],
        )

        result = run(
            closes, [{"ticker": "NVDA", "weight": 50}, {"ticker": "NEW", "weight": 50}],
            withdrawal={"amount": 100, "frequency": "monthly"},
        )

        self.assertEqual(result["total"], [1000.0, 900.0, 800.0])
        self.assertEqual(result["cash"], [500.0, 450.0, 0.0])
        self.assertEqual(result["metrics"]["gain"], 0.0)
        self.assertEqual(
            sum(h["contribution"] for h in result["holdings"]), result["metrics"]["gain"]
        )


# ── The money-weighted return ────────────────────────────────────────────────

class MoneyWeightedReturnTests(unittest.TestCase):
    """The mirror of the contribution worked example, arranged so the answer
    can be solved on paper. Prices of 100, 200 and 88 on 2020-12-31,
    2021-06-30 and 2021-12-28, $1,000 at the start and $500 taken out at the
    top:

        $1,000 buys 10 shares at 100
        $500 out at 200 leaves 7.5 shares
        7.5 shares at 88 is $660

    The two dates are 181 and 362 days from the start, so the second gap is
    the first doubled. With y the growth factor over one such gap, the rate
    is the y that settles

        1000y² = 500y + 660    ⟹    y = 1.1

    - the money grew a tenth over each half, the same 21.2% a year the
    contribution example reaches from the other side. The holding itself
    fell 12%, and both are true: the $500 came out before the fall.
    """

    CLOSES = frame({"NVDA": [100.0, 200.0, 88.0]},
                   ["2020-12-31", "2021-06-30", "2021-12-28"])
    TAKE_500 = {"amount": 500, "frequency": "yearly"}

    def test_it_matches_the_rate_solved_on_paper(self):
        result = run(self.CLOSES, [{"ticker": "NVDA", "weight": 100}], withdrawal=self.TAKE_500)

        self.assertEqual(result["total"], [1000.0, 1500.0, 660.0])
        self.assertEqual(result["metrics"]["moneyWeightedReturn"], round(
            (1.1 ** (DAYS_PER_YEAR / 181) - 1) * 100, 4
        ))
        self.assertAlmostEqual(result["metrics"]["moneyWeightedReturn"], 21.2073, places=4)
        # Time-weighted, the holding lost 12%: a dollar left alone in it did.
        self.assertEqual(result["metrics"]["totalReturn"], -12.0)
        # 660 left plus 500 taken, against 1,000 put in.
        self.assertEqual(result["metrics"]["gain"], 160.0)

    def test_the_reported_rate_discounts_the_flows_back_to_zero(self):
        """IRR is defined by a property, so the property is checked: at the
        rate reported, the money in, discounted from the day it arrived, is
        worth what came back out and what was left."""
        result = run(self.CLOSES, [{"ticker": "NVDA", "weight": 100}], withdrawal=self.TAKE_500)

        flows = [("2020-12-31", -1000.0), ("2021-06-30", 500.0), ("2021-12-28", 660.0)]
        self.assertLess(abs(npv(result["metrics"]["moneyWeightedReturn"], flows)), NPV_TOLERANCE)

    def test_a_portfolio_drawn_to_nothing_reports_the_rate_that_reconciles_it(self):
        """Emptied out at the last row: every dollar that ever came back is
        a withdrawal, and the rate must still discount them to the opening
        amount - including the partial one on the run-out row."""
        closes = frame({"NVDA": [100.0] * 4},
                       ["2020-01-02", "2020-02-03", "2020-03-02", "2020-04-01"])

        result = run(closes, [{"ticker": "NVDA", "weight": 100}],
                     withdrawal={"amount": 600, "frequency": "monthly"})

        # 600, then the 400 that was left. Received 1,000 for 1,000 put in,
        # so the money earned nothing.
        self.assertEqual(result["metrics"]["withdrawn"], 1000.0)
        self.assertAlmostEqual(result["metrics"]["moneyWeightedReturn"], 0.0, places=3)


# ── Through the endpoint ─────────────────────────────────────────────────────

class WithdrawalRouteTests(unittest.TestCase):
    """The wiring: the request model carries the schedule, the response
    carries it back, and an unusable request is a 400 rather than a 500 or -
    worse - a 200 that quietly ignored the field.

    The fake answers `prices` with the **symbol** in the ticker column, which
    is what _closes_db pivots on (see ContributionRouteTests for the trap an
    id there sets), so the final-value assertions below are what make a run
    that sat in cash the whole time fail loudly.
    """

    class _Client:
        """Read-only stand-in for Supabase: AAPL on the 5th of each month of
        2020, rising 100, 110, 120 ... 210."""

        ROWS = [
            {"ticker": "AAPL", "date": f"2020-{month:02d}-05", "close": 90.0 + 10 * month}
            for month in range(1, 13)
        ]

        def table(self, *_args, **_kwargs):
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

            return SimpleNamespace(data=self.ROWS)

    def _post(self, body):
        with (
            patch("services.market_data.get_client_optional", return_value=self._Client()),
            patch("services.portfolio.get_risk_free_rate", return_value=None),
            # Every TestClient reports one address, so every simulate call in
            # the suite shares one 20-a-minute bucket (see backend/CLAUDE.md).
            # These tests are not about the limit, so they draw on their own
            # rather than push a later file's calls into a 429.
            patch("rate_limit.general_limiter", FixedWindowLimiter(limit=1000, window_seconds=60)),
            patch("rate_limit.simulate_limiter", FixedWindowLimiter(limit=1000, window_seconds=60)),
        ):
            return client.post("/api/portfolio/simulate", json=body)

    BODY = {
        "holdings": [{"ticker": "AAPL", "weight": 100}],
        "value": 10_000,
        "start": "2020-01-01",
        "end": "2020-12-31",
    }

    def test_a_schedule_is_carried_through_and_echoed_back(self):
        resp = self._post({**self.BODY, "withdrawal": {"amount": 500, "frequency": "monthly"}})

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["withdrawal"], {"amount": 500.0, "frequency": "monthly"})
        self.assertIsNone(body["contribution"])
        # Eleven withdrawals: every month after the one the window opens in.
        self.assertEqual(body["metrics"]["withdrawn"], 11 * 500)
        self.assertEqual(len(body["withdrawn"]), len(body["dates"]))
        self.assertEqual(body["withdrawn"][-1], 11 * 500)
        # Nothing is paid in beyond the opening amount.
        self.assertEqual(body["metrics"]["contributed"], 0.0)
        self.assertEqual(body["metrics"]["totalInvested"], 10_000)
        # The holding was actually priced and bought: 100 shares at 100, less
        # 500 sold at each of 110, 120 ... 210 - 64.18 shares at 210, worth
        # 13,477.90 - and nothing sat in cash. The gain adds back what was
        # taken: 13,477.90 + 5,500 - 10,000.
        self.assertEqual(body["cash"], [0.0] * len(body["dates"]))
        self.assertEqual(body["metrics"]["finalValue"], 13_477.9)
        self.assertEqual(body["metrics"]["gain"], 8_977.9)
        self.assertIsNone(body["metrics"]["depletedOn"])
        # The flow-free series is published: the money that left moved the
        # total away from it.
        self.assertEqual(len(body["unitValue"]), len(body["dates"]))

    def test_omitting_the_schedule_leaves_it_off(self):
        resp = self._post(self.BODY)

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsNone(body["withdrawal"])
        self.assertIsNone(body["withdrawn"])
        self.assertEqual(body["metrics"]["withdrawn"], 0.0)
        self.assertEqual(body["metrics"]["finalValue"], 21_000.0)

    def test_an_unusable_schedule_is_a_400_naming_it(self):
        resp = self._post({**self.BODY, "withdrawal": {"amount": 500, "frequency": "weekly"}})

        self.assertEqual(resp.status_code, 400)
        self.assertIn("withdrawal.frequency", resp.json()["detail"])

    def test_both_schedules_are_a_400_naming_both(self):
        resp = self._post({
            **self.BODY,
            "contribution": {"amount": 100, "frequency": "monthly"},
            "withdrawal": {"amount": 100, "frequency": "monthly"},
        })

        self.assertEqual(resp.status_code, 400)
        detail = resp.json()["detail"]
        self.assertIn("contribution", detail)
        self.assertIn("withdrawal", detail)

    def test_a_negative_contribution_is_a_400_pointing_at_withdrawal(self):
        resp = self._post({**self.BODY, "contribution": {"amount": -100, "frequency": "monthly"}})

        self.assertEqual(resp.status_code, 400)
        self.assertIn("`withdrawal`", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
