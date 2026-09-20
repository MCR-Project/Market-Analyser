"""
Tests for recurring contributions (issue #67).

The reason this is its own file rather than more cases in
test_portfolio.py is that contributions break an assumption every metric
in test_portfolio_metrics.py was written under: that the total moves only
because prices moved. Once money keeps arriving that is false, and a
metric read straight off the total starts reporting deposits as
performance. So what is pinned down here is mostly the *separation*:

  - **Off is off.** A run with no contribution, with a null one, and with
    an amount of zero must all be the same object as each other and as
    the run before this feature existed. That is the promise the rest of
    the suite depends on, so it is asserted on the whole response rather
    than on a few fields.

  - **A deposit is not a gain.** Paying money into a portfolio whose
    prices never move must leave the return at zero, the volatility at
    zero and the drawdown at zero. Read off the raw total instead, the
    same run reports a rally.

  - **The two returns answer different questions.** A stock that gains
    54% while the money in it earns 21% a year is not a contradiction,
    and the worked example below is arranged so both numbers can be
    derived by hand and neither can be reached from the other.

  - **IRR is checked against its own definition, not against itself.**
    One case solves a quadratic on paper; the others discount the
    reported rate back over the flows with arithmetic written here, and
    require the result to come back to zero. An IRR that agreed with a
    second copy of the same solver would prove nothing.

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
from services.portfolio import DAYS_PER_YEAR, simulate_portfolio

client = TestClient(app, raise_server_exceptions=False)


def frame(columns: dict, dates: list[str]) -> pd.DataFrame:
    """A wide date x ticker close frame, shaped like get_closes returns."""
    return pd.DataFrame(columns, index=pd.to_datetime(dates))


def run(closes, holdings, value=1000.0, rebalance="none", contribution=None, **kwargs):
    # Dividends are read separately from the prices (#68), so patching
    # only the price read would leave the simulation reaching for Supabase
    # - slow wherever it answers, and a different run depending on whether
    # it did. Silenced here; income has its own file.
    with (
        patch("services.portfolio.get_closes", return_value=closes),
        patch("services.portfolio.get_dividends", return_value={}),
        patch("services.portfolio.tracked_tickers", return_value=set()),
    ):
        return simulate_portfolio(
            holdings, value=value, start="2019-01-01", end="2023-12-31",
            rebalance=rebalance, contribution=contribution, **kwargs
        )


def holding(result, ticker):
    return next(h for h in result["holdings"] if h["ticker"] == ticker)


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


# Rates are reported to PERCENT_DP, which is a millionth in absolute
# terms, so discounting thousands of dollars back at the *rounded* rate
# lands near zero rather than on it. A cent is the honest tolerance: any
# larger residual is a wrong rate, not a rounded one.
NPV_TOLERANCE = 0.01


def steps(invested: list[float]) -> list[int]:
    """Which rows money arrived on, by index."""
    return [i for i in range(1, len(invested)) if invested[i] != invested[i - 1]]


# ── Off by default ───────────────────────────────────────────────────────────

class ContributionsOffTests(unittest.TestCase):
    """The existing behaviour has to survive the feature untouched."""

    CLOSES = frame(
        {"NVDA": [100.0, 110.0, 90.0, 120.0], "AMD": [50.0, 55.0, 60.0, 40.0]},
        ["2020-01-02", "2020-02-03", "2020-03-02", "2020-04-01"],
    )
    BASKET = [{"ticker": "NVDA", "weight": 60}, {"ticker": "AMD", "weight": 40}]

    def test_no_contribution_null_and_zero_are_the_same_run(self):
        """Three ways of saying "just the lump sum", and they must not be
        three slightly different simulations."""
        absent = run(self.CLOSES, self.BASKET)
        null = run(self.CLOSES, self.BASKET, contribution=None)
        zero = run(self.CLOSES, self.BASKET, contribution={"amount": 0, "frequency": None})
        # An amount of zero with a frequency named is still off: nothing
        # is being paid, so the schedule has nothing to schedule.
        scheduled_zero = run(
            self.CLOSES, self.BASKET, contribution={"amount": 0, "frequency": "monthly"}
        )

        self.assertEqual(absent, null)
        self.assertEqual(absent, zero)
        self.assertEqual(absent, scheduled_zero)
        self.assertIsNone(absent["contribution"])

    def test_an_untouched_run_reports_nothing_paid_in_beyond_the_start(self):
        result = run(self.CLOSES, self.BASKET)
        metrics = result["metrics"]

        self.assertEqual(metrics["contributed"], 0.0)
        self.assertEqual(metrics["totalInvested"], 1000.0)
        self.assertEqual(metrics["gain"], round(metrics["finalValue"] - 1000.0, 2))
        # Money arrived once, at the start, and never again.
        self.assertEqual(result["invested"], [1000.0, 1000.0, 1000.0, 1000.0])

    def test_with_one_lump_sum_the_two_returns_are_the_same_number(self):
        """A single payment at the start is the case where "what the
        portfolio did" and "what the money earned" cannot differ: there is
        only one dollar-weighting and it is uniform. CAGR and IRR are
        computed by completely different routes - one compounds a ratio,
        the other solves for a discount rate - so their agreeing here is
        a real check on both."""
        result = run(self.CLOSES, self.BASKET)
        metrics = result["metrics"]

        self.assertIsNotNone(metrics["cagr"])
        self.assertAlmostEqual(metrics["moneyWeightedReturn"], metrics["cagr"], places=3)


# ── Where the money lands ────────────────────────────────────────────────────

class ContributionScheduleTests(unittest.TestCase):
    def test_money_arrives_on_the_first_row_of_each_new_month(self):
        """The window's own first row is the opening amount, never a
        contribution - so a five-row window spanning three months takes
        two payments, not three."""
        closes = frame(
            {"NVDA": [100.0] * 5},
            ["2020-01-02", "2020-01-15", "2020-02-03", "2020-02-20", "2020-03-02"],
        )

        result = run(
            closes, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 100, "frequency": "monthly"},
        )

        # Rows 2 and 4: the first row of February, and the first of March.
        self.assertEqual(steps(result["invested"]), [2, 4])
        self.assertEqual(result["invested"], [1000.0, 1000.0, 1100.0, 1100.0, 1200.0])
        self.assertEqual(result["metrics"]["contributed"], 200.0)
        self.assertEqual(result["metrics"]["totalInvested"], 1200.0)

    def test_a_contribution_date_that_is_not_a_trading_day_moves_forward(self):
        """1 February 2020 was a Saturday and 1 March a Sunday, so neither
        month begins on a row. The payment lands on the first row the
        month actually has rather than being skipped, which is the same
        rule a rebalance follows."""
        closes = frame(
            {"NVDA": [100.0] * 4},
            ["2020-01-31", "2020-02-03", "2020-02-28", "2020-03-02"],
        )

        result = run(
            closes, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 100, "frequency": "monthly"},
        )

        self.assertEqual(steps(result["invested"]), [1, 3])
        self.assertEqual(
            [result["dates"][i] for i in steps(result["invested"])],
            ["2020-02-03", "2020-03-02"],
        )

    def test_the_total_contributed_is_the_number_of_payments_times_the_amount(self):
        """Twelve monthly rows from January to December take eleven
        payments: every month after the one the window opens in."""
        months = [f"2020-{month:02d}-05" for month in range(1, 13)]
        closes = frame({"NVDA": [100.0] * 12}, months)

        result = run(
            closes, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 100, "frequency": "monthly"},
        )

        payments = steps(result["invested"])
        self.assertEqual(len(payments), 11)
        self.assertEqual(result["metrics"]["contributed"], len(payments) * 100)

    def test_quarterly_and_yearly_pay_on_their_own_boundaries(self):
        months = [f"2020-{month:02d}-05" for month in range(1, 13)] + ["2021-01-05"]
        closes = frame({"NVDA": [100.0] * 13}, months)

        quarterly = run(
            closes, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 100, "frequency": "quarterly"},
        )
        yearly = run(
            closes, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 100, "frequency": "yearly"},
        )

        # April, July, October, January.
        self.assertEqual(steps(quarterly["invested"]), [3, 6, 9, 12])
        self.assertEqual(steps(yearly["invested"]), [12])
        self.assertEqual(yearly["metrics"]["contributed"], 100.0)

    def test_each_payment_buys_at_its_own_dates_price(self):
        """A contribution is not averaged in at some notional price: it
        buys what it can afford on the day it arrives. $1,000 at $100 is
        ten shares; the same $1,000 after the stock doubles is five."""
        closes = frame({"NVDA": [100.0, 200.0]}, ["2020-01-02", "2020-02-03"])

        result = run(
            closes, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 1000, "frequency": "monthly"},
        )

        # 10 shares, then 5 more, all worth $200: $3,000 against $2,000 in.
        self.assertEqual(result["total"], [1000.0, 3000.0])
        self.assertEqual(result["invested"], [1000.0, 2000.0])
        self.assertEqual(result["metrics"]["gain"], 1000.0)
        # The stock doubled, and that is what the portfolio returned - the
        # deposit neither added to it nor diluted it.
        self.assertEqual(result["metrics"]["totalReturn"], 100.0)

    def test_a_payment_is_split_across_the_target_weights(self):
        closes = frame(
            {"NVDA": [100.0, 100.0], "AMD": [50.0, 50.0]},
            ["2020-01-02", "2020-02-03"],
        )

        result = run(
            closes,
            [{"ticker": "NVDA", "weight": 75}, {"ticker": "AMD", "weight": 25}],
            contribution={"amount": 400, "frequency": "monthly"},
        )

        # 750 + 300 and 250 + 100, at unchanged prices.
        self.assertEqual(holding(result, "NVDA")["values"], [750.0, 1050.0])
        self.assertEqual(holding(result, "AMD")["values"], [250.0, 350.0])
        self.assertEqual(result["total"], [1000.0, 1400.0])

    def test_a_payment_for_an_unlisted_holding_waits_in_cash(self):
        """The rule the opening allocation already follows (#56): money
        for a holding with no price yet is not spent on the others, and
        not spent at an invented price either. It sits in cash and buys in
        at the first close there is."""
        closes = frame(
            {"NVDA": [100.0, 100.0, 100.0], "AMD": [float("nan"), float("nan"), 50.0]},
            ["2020-01-02", "2020-02-03", "2020-03-02"],
        )

        result = run(
            closes,
            [{"ticker": "NVDA", "weight": 50}, {"ticker": "AMD", "weight": 50}],
            contribution={"amount": 200, "frequency": "monthly"},
        )

        # February: NVDA's 100 is bought, AMD's 100 joins the 500 waiting.
        self.assertEqual(result["cash"], [500.0, 600.0, 0.0])
        self.assertEqual(holding(result, "AMD")["values"], [0.0, 0.0, 700.0])
        # Nothing was lost or invented along the way.
        self.assertEqual(result["total"], [1000.0, 1200.0, 1400.0])
        self.assertEqual(result["invested"], [1000.0, 1200.0, 1400.0])
        self.assertEqual(result["metrics"]["gain"], 0.0)

    def test_contributions_and_rebalancing_coexist(self):
        """Both fire on the first row of a new period, so on a rebalance
        month they land together. The money is paid in at the target
        weights and the portfolio is then restored to them, which is the
        same answer in either order - what must not happen is one of them
        being skipped."""
        closes = frame(
            {"NVDA": [100.0, 200.0], "AMD": [100.0, 100.0]},
            ["2020-01-02", "2020-02-03"],
        )

        result = run(
            closes,
            [{"ticker": "NVDA", "weight": 50}, {"ticker": "AMD", "weight": 50}],
            rebalance="monthly",
            contribution={"amount": 500, "frequency": "monthly"},
        )

        # 500 doubles to 1000, 500 stays: 1500, plus 500 paid in is 2000,
        # rebalanced to 1000 each.
        self.assertEqual(result["total"], [1000.0, 2000.0])
        self.assertEqual(holding(result, "NVDA")["values"], [500.0, 1000.0])
        self.assertEqual(holding(result, "AMD")["values"], [500.0, 1000.0])
        self.assertEqual(result["metrics"]["totalInvested"], 1500.0)


# ── A deposit is not performance ─────────────────────────────────────────────

class TimeWeightedTests(unittest.TestCase):
    def test_paying_into_a_flat_portfolio_reports_no_return_and_no_risk(self):
        """The case that decides whether the metrics were separated from
        the flows at all. Prices never move, so every honest number is
        zero - but the total climbs from 1,000 to 1,400 on the way, and
        anything reading that total sees three rallies and calls the
        portfolio volatile."""
        closes = frame(
            {"NVDA": [100.0] * 5},
            ["2020-01-02", "2020-02-03", "2020-03-02", "2020-04-01", "2020-05-01"],
        )

        result = run(
            closes, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 100, "frequency": "monthly"},
        )
        metrics = result["metrics"]

        self.assertEqual(result["total"], [1000.0, 1100.0, 1200.0, 1300.0, 1400.0])
        self.assertEqual(metrics["totalReturn"], 0.0)
        self.assertEqual(metrics["cagr"], 0.0)
        self.assertEqual(metrics["volatility"], 0.0)
        self.assertEqual(metrics["maxDrawdown"]["value"], 0.0)
        # And the money side reports the deposits honestly.
        self.assertEqual(metrics["contributed"], 400.0)
        self.assertEqual(metrics["gain"], 0.0)
        self.assertEqual(metrics["moneyWeightedReturn"], 0.0)

    def test_a_deposit_does_not_hide_a_fall(self):
        """The mirror image: a portfolio that halves while money is paid
        in still shows the fall. Read off the total, the deposit props the
        number up and the drawdown shrinks."""
        closes = frame(
            {"NVDA": [100.0, 50.0, 50.0]},
            ["2020-01-02", "2020-02-03", "2020-03-02"],
        )

        result = run(
            closes, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 1000, "frequency": "monthly"},
        )

        # 1000 halves to 500, plus 1000 paid in is 1500 - up on the day.
        self.assertEqual(result["total"], [1000.0, 1500.0, 2500.0])
        self.assertEqual(result["metrics"]["totalReturn"], -50.0)
        self.assertEqual(result["metrics"]["maxDrawdown"]["value"], -50.0)
        self.assertEqual(result["metrics"]["maxDrawdown"]["peakDate"], "2020-01-02")
        self.assertEqual(result["metrics"]["maxDrawdown"]["troughDate"], "2020-02-03")

    def test_the_flow_free_series_is_published_only_when_it_differs(self):
        """A chart plotting return rather than value needs the series the
        metrics were read off, or it draws a line that contradicts the
        summary beside it. Null without contributions, because then it is
        the total again and a copy would imply a difference."""
        dates = ["2020-01-02", "2020-02-03", "2020-03-02"]
        closes = frame({"NVDA": [100.0, 100.0, 200.0]}, dates)

        plain = run(closes, [{"ticker": "NVDA", "weight": 100}])
        funded = run(
            closes, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 1000, "frequency": "monthly"},
        )

        self.assertIsNone(plain["unitValue"])
        # $1,000 buys 10 shares at 100. February pays in 1,000 more at an
        # unchanged 100, for 20 shares. March doubles the price - 20
        # shares are worth 4,000 - and pays in another 1,000, ending at
        # 25 shares and 5,000. The account tripled; a dollar left in it
        # from the start only doubled, which is what the price did.
        self.assertEqual(funded["total"], [1000.0, 2000.0, 5000.0])
        self.assertEqual(funded["unitValue"], [1000.0, 1000.0, 2000.0])
        self.assertEqual(funded["metrics"]["totalReturn"], 100.0)
        self.assertEqual(funded["metrics"]["totalInvested"], 3000.0)
        self.assertEqual(funded["metrics"]["gain"], 2000.0)

    def test_the_time_weighted_return_is_the_holdings_own_return(self):
        """A portfolio of one ticker returns what that ticker returned,
        however much money was paid into it along the way. If that is not
        true, the contribution has leaked into the performance."""
        closes = frame({"NVDA": [100.0, 200.0, 154.0]},
                       ["2020-12-31", "2021-06-30", "2021-12-28"])

        result = run(
            closes, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 1000, "frequency": "yearly"},
        )

        self.assertEqual(holding(result, "NVDA")["return"], 54.0)
        self.assertEqual(result["metrics"]["totalReturn"], 54.0)


# ── The money-weighted return ────────────────────────────────────────────────

class MoneyWeightedReturnTests(unittest.TestCase):
    """The worked example, and then the definition.

    Prices of 100, 200 and 154 on 2020-12-31, 2021-06-30 and 2021-12-28,
    with $1,000 at the start and $1,000 paid in halfway:

        $1,000 buys 10 shares at 100
        $1,000 buys  5 shares at 200
        15 shares at 154 is $2,310

    The two payment dates are 181 and 362 days from the start, so the
    second gap is exactly the first doubled. Writing y for the growth
    factor over one such gap, the internal rate of return is the y that
    settles

        1000y² + 1000y − 2310 = 0    ⟹    y² + y − 2.31 = 0

    which factorises to (y − 1.1)(y + 2.1), so y = 1.1: the money grew a
    tenth over each half. Annualising that half - 181 days against a
    365.25-day year - is the rate the engine has to report.

    The year is chosen so that both payments land where they should:
    2021-06-30 opens a new year against a 2020 start and takes the
    payment, and 2021-12-28 is still 2021, so the closing row does not.
    """

    CLOSES = frame({"NVDA": [100.0, 200.0, 154.0]},
                   ["2020-12-31", "2021-06-30", "2021-12-28"])

    def test_it_matches_the_rate_solved_on_paper(self):
        result = run(
            self.CLOSES, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 1000, "frequency": "yearly"},
        )

        self.assertEqual(result["total"], [1000.0, 3000.0, 2310.0])
        self.assertEqual(result["invested"], [1000.0, 2000.0, 2000.0])

        expected = (1.1 ** (DAYS_PER_YEAR / 181) - 1) * 100
        # Rounded to the fourth decimal, which is where rates are reported.
        self.assertEqual(result["metrics"]["moneyWeightedReturn"], round(expected, 4))
        self.assertAlmostEqual(result["metrics"]["moneyWeightedReturn"], 21.2073, places=4)
        # The holding gained 54% over a window of about a year, and the
        # money in it earned 21% - not a contradiction. The second $1,000
        # arrived at the top and was working for only half the window,
        # while the first was there for the whole of it.
        self.assertEqual(result["metrics"]["totalReturn"], 54.0)

    def test_the_reported_rate_discounts_the_flows_back_to_zero(self):
        """IRR is defined by a property rather than by a formula, so the
        property is what gets checked: at the rate reported, every dollar
        paid in, discounted from the day it arrived, is worth exactly what
        the portfolio ended up worth."""
        result = run(
            self.CLOSES, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 1000, "frequency": "yearly"},
        )

        flows = [
            ("2020-12-31", -1000.0),
            ("2021-06-30", -1000.0),
            ("2021-12-28", 2310.0),
        ]
        self.assertLess(abs(npv(result["metrics"]["moneyWeightedReturn"], flows)), NPV_TOLERANCE)

    def test_it_holds_for_a_long_irregular_schedule(self):
        """The same property over twelve months of payments against a
        wandering price, where nobody could solve it on paper."""
        months = [f"2020-{month:02d}-05" for month in range(1, 13)] + ["2021-01-05"]
        prices = [100.0, 118.0, 92.0, 105.0, 131.0, 127.0,
                  140.0, 121.0, 155.0, 149.0, 168.0, 172.0, 181.0]
        closes = frame({"NVDA": prices}, months)

        result = run(
            closes, [{"ticker": "NVDA", "weight": 100}],
            contribution={"amount": 250, "frequency": "monthly"},
        )

        paid = [(months[0], -1000.0)]
        paid += [(months[i], -250.0) for i in steps(result["invested"])]
        paid.append((months[-1], result["total"][-1]))

        self.assertEqual(result["metrics"]["contributed"], 12 * 250)
        self.assertLess(abs(npv(result["metrics"]["moneyWeightedReturn"], paid)), NPV_TOLERANCE)

    def test_a_portfolio_that_lost_everything_reports_minus_one_hundred(self):
        """No rate describes losing all of it better than all of it. The
        solver has no root to find here - the discounted deposits can
        never reach zero - so this is answered rather than searched for."""
        closes = frame({"NVDA": [100.0, 0.0]}, ["2020-01-02", "2020-02-03"])

        result = run(closes, [{"ticker": "NVDA", "weight": 100}])

        self.assertEqual(result["total"][-1], 0.0)
        self.assertEqual(result["metrics"]["moneyWeightedReturn"], -100.0)

    def test_a_window_of_one_row_has_no_rate_to_report(self):
        """No time passed, so there is no annual anything. Null rather
        than zero, which would claim a flat year."""
        closes = frame({"NVDA": [100.0]}, ["2020-01-02"])

        result = run(closes, [{"ticker": "NVDA", "weight": 100}])

        self.assertIsNone(result["metrics"]["moneyWeightedReturn"])
        self.assertIsNone(result["metrics"]["cagr"])


# ── Refusals ─────────────────────────────────────────────────────────────────

class ContributionValidationTests(unittest.TestCase):
    CLOSES = frame({"NVDA": [100.0, 110.0]}, ["2020-01-02", "2020-02-03"])
    BASKET = [{"ticker": "NVDA", "weight": 100}]

    def test_an_amount_without_a_frequency_is_refused(self):
        """"$100" is not a schedule, and choosing one for the caller would
        put money into their portfolio on dates they never named."""
        with self.assertRaises(ValueError) as caught:
            run(self.CLOSES, self.BASKET, contribution={"amount": 100})
        self.assertIn("frequency", str(caught.exception))

    def test_an_unknown_frequency_is_refused_by_name(self):
        with self.assertRaises(ValueError) as caught:
            run(self.CLOSES, self.BASKET,
                contribution={"amount": 100, "frequency": "fortnightly"})
        self.assertIn("fortnightly", str(caught.exception))

    def test_a_negative_amount_is_refused(self):
        """Money going out has its own field (`withdrawal`, issue #150 and
        ADR 0002) - see test_portfolio_withdrawals.py, which pins that the
        refusal says so. Here it is only that a sign on the contribution is
        not how it is said."""
        with self.assertRaises(ValueError) as caught:
            run(self.CLOSES, self.BASKET,
                contribution={"amount": -100, "frequency": "monthly"})
        self.assertIn("negative", str(caught.exception))

    def test_an_amount_that_is_not_a_number_is_refused(self):
        for bad in ("100", True, float("nan"), float("inf")):
            with self.subTest(amount=bad):
                with self.assertRaises(ValueError):
                    run(self.CLOSES, self.BASKET,
                        contribution={"amount": bad, "frequency": "monthly"})

    def test_something_that_is_not_an_object_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            run(self.CLOSES, self.BASKET, contribution=100)
        self.assertIn("contribution", str(caught.exception))


# ── Through the endpoint ─────────────────────────────────────────────────────

class ContributionRouteTests(unittest.TestCase):
    """The wiring: the request model carries the schedule and the response
    carries it back, and a bad schedule is a 400 rather than a 500.

    The fake below answers `prices` with the **symbol** in the ticker
    column, which is what _closes_db pivots on. Answering with a numeric id
    instead leaves the column named 1, AAPL looks like a holding with no
    prices, and the whole run sits in cash - which still satisfies every
    assertion about contributions while proving nothing, and reaches for
    the network to check whether AAPL is a real symbol. The final-value
    assertions here exist to make that failure loud rather than silent.
    """

    class _Client:
        """Read-only stand-in for Supabase. AAPL on the 5th of each month
        of 2020, rising 100, 110, 120 … so a contribution buying at a
        later date buys visibly less."""

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
            # get_risk_free_rate also reaches get_client_optional now
            # (issue #112) - _Client answers any table with these price
            # rows, which have no "rate" column, so this is patched
            # separately rather than taught to the fake.
            patch("services.portfolio.get_risk_free_rate", return_value=None),
        ):
            return client.post("/api/portfolio/simulate", json=body)

    BODY = {
        "holdings": [{"ticker": "AAPL", "weight": 100}],
        "value": 10_000,
        "start": "2020-01-01",
        "end": "2020-12-31",
    }

    def test_a_schedule_is_carried_through_and_echoed_back(self):
        resp = self._post({
            **self.BODY,
            "contribution": {"amount": 500, "frequency": "monthly"},
        })

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["contribution"], {"amount": 500.0, "frequency": "monthly"})
        # Eleven payments: every month after the one the window opens in.
        self.assertEqual(body["metrics"]["contributed"], 11 * 500)
        self.assertEqual(body["metrics"]["totalInvested"], 10_000 + 11 * 500)
        self.assertEqual(len(body["invested"]), len(body["dates"]))
        self.assertEqual(body["invested"][-1], body["metrics"]["totalInvested"])
        # The holding was actually priced and actually bought: nothing is
        # left in cash, and the price rose 100 to 210 over the window.
        self.assertEqual(body["cash"], [0.0] * len(body["dates"]))
        self.assertEqual(body["metrics"]["totalReturn"], 110.0)
        self.assertGreater(body["metrics"]["gain"], 0)

    def test_omitting_the_schedule_leaves_it_off(self):
        resp = self._post(self.BODY)

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsNone(body["contribution"])
        self.assertIsNone(body["unitValue"])
        self.assertEqual(body["metrics"]["contributed"], 0.0)
        self.assertEqual(body["metrics"]["totalInvested"], 10_000)
        # 100 to 210 is 110%, on the lump sum alone.
        self.assertEqual(body["metrics"]["finalValue"], 21_000.0)
        self.assertEqual(body["metrics"]["gain"], 11_000.0)

    def test_an_unusable_schedule_is_a_400_naming_it(self):
        resp = self._post({
            **self.BODY,
            "contribution": {"amount": 500, "frequency": "weekly"},
        })

        self.assertEqual(resp.status_code, 400)
        self.assertIn("frequency", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
