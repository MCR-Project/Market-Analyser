"""
Tests for the metrics a simulated portfolio reports (issue #57).

Every expected number here is worked out by hand in the test that asserts
it, because a metric computed the same wrong way twice still agrees with
itself. The cases that matter:

  - **The conventions are the metric.** A volatility annualised as though
    monthly buckets were trading days is out by a factor of about 4.6, and
    it is out silently - the number still looks like a percentage. So the
    annualisation is read off the run's own calendar, and there is a test
    for each kind of row.

  - **Contributions add up.** Once a rebalance moves money between
    holdings, a final value no longer says who earned it. The flows have
    to net out exactly, or the per-holding breakdown quietly disagrees
    with the total it is breaking down.

  - **A degenerate run says so.** Two days of history is not a portfolio
    with zero risk and no growth rate; volatility and CAGR come back null
    rather than 0, which is a different claim.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import math
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
    return pd.DataFrame(columns, index=pd.to_datetime(dates))


def run(closes, holdings, value=1000.0, rebalance="none"):
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
            holdings, value=value, start="2015-01-01", end="2024-12-31",
            rebalance=rebalance,
        )


def one(ticker="A", weight=100):
    return [{"ticker": ticker, "weight": weight}]


def holding(result, ticker):
    return next(h for h in result["holdings"] if h["ticker"] == ticker)


# ── Total return, final value, CAGR ──────────────────────────────────────────

class ReturnTests(unittest.TestCase):
    def test_total_return_and_final_value(self):
        closes = frame({"A": [100.0, 120.0]}, ["2020-01-02", "2020-03-02"])

        metrics = run(closes, one())["metrics"]

        self.assertEqual(metrics["startValue"], 1000.0)
        self.assertEqual(metrics["finalValue"], 1200.0)
        self.assertEqual(metrics["totalReturn"], 20.0)

    def test_cagr_compounds_over_the_calendar_time_covered(self):
        """Doubling over two years is not a 100% annual rate. 2020-01-01
        to 2022-01-01 is 731 days, so the rate is 2 ** (365.25/731) - 1 =
        41.39%."""
        closes = frame({"A": [100.0, 200.0]}, ["2020-01-01", "2022-01-01"])

        metrics = run(closes, one())["metrics"]

        self.assertAlmostEqual(metrics["cagr"], 41.3876, places=3)
        self.assertEqual(metrics["totalReturn"], 100.0)

    def test_cagr_is_the_same_rate_however_finely_the_year_is_sampled(self):
        """The same year of history answered in monthly buckets and in
        daily rows must annualise identically - CAGR counts elapsed days,
        not rows, which is what makes the tiered `prices` storage
        invisible here."""
        monthly = frame(
            {"A": [100.0 * (1.01 ** i) for i in range(13)]},
            [f"2021-{month:02d}-01" for month in range(1, 13)] + ["2022-01-01"],
        )
        endpoints = frame({"A": [100.0, 100.0 * (1.01 ** 12)]}, ["2021-01-01", "2022-01-01"])

        self.assertAlmostEqual(
            run(monthly, one())["metrics"]["cagr"],
            run(endpoints, one())["metrics"]["cagr"],
            places=6,
        )


# ── Volatility ───────────────────────────────────────────────────────────────

class VolatilityTests(unittest.TestCase):
    # Returns of +10%, -10%, +10%: mean 1/30, sample standard deviation
    # sqrt(0.0266.../2) = 0.11547.
    SIGMA = 0.1154700538

    # The four rows below are one gap apart in each test; a return covering
    # `days` of calendar time covers days x 252/365.25 of trading time
    # (except consecutive daily rows, which are one trading day apart
    # however many weekend days fall between them).
    WEEK = 7 * 252 / 365.25          # ~4.83 trading days
    MONTH = 30 * 252 / 365.25        # ~20.7 trading days

    def _volatility_of(self, dates):
        closes = frame({"A": [100.0, 110.0, 99.0, 108.9]}, dates)
        return run(closes, one())["metrics"]["volatility"]

    def test_daily_rows_are_the_textbook_daily_standard_deviation(self):
        """Nothing is scaled when the rows are already daily: this is
        std(returns) x root 252, exactly as anyone checking the number by
        hand would compute it."""
        volatility = self._volatility_of(
            ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
        )

        self.assertAlmostEqual(volatility, self.SIGMA * math.sqrt(252) * 100, places=2)

    def test_a_weekend_between_two_daily_rows_is_still_one_trading_day(self):
        """Friday to Monday is one day of market. Treating the three
        calendar days as three days of risk would make every weekly wrap
        look calmer than the days around it."""
        friday_to_monday = self._volatility_of(
            ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"]
        )
        consecutive = self._volatility_of(
            ["2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09"]
        )

        self.assertAlmostEqual(friday_to_monday, consecutive, places=6)

    def test_weekly_buckets_are_scaled_by_the_trading_time_they_cover(self):
        """The same three returns a week apart are not a week's worth of
        daily risk: each is divided by the root of ~4.83 trading days
        before the annualisation, which lands near the familiar root 52."""
        volatility = self._volatility_of(
            ["2018-01-01", "2018-01-08", "2018-01-15", "2018-01-22"]
        )

        self.assertAlmostEqual(
            volatility, self.SIGMA / math.sqrt(self.WEEK) * math.sqrt(252) * 100, places=2
        )
        self.assertAlmostEqual(volatility, self.SIGMA * math.sqrt(52.2) * 100, places=1)

    def test_monthly_buckets_are_scaled_the_same_way(self):
        """Reading these as daily would claim about 4.6x the risk actually
        run - the silent lie the tiered storage makes possible."""
        volatility = self._volatility_of(
            ["2016-01-01", "2016-01-31", "2016-03-01", "2016-03-31"]
        )

        self.assertAlmostEqual(
            volatility, self.SIGMA / math.sqrt(self.MONTH) * math.sqrt(252) * 100, places=2
        )
        self.assertAlmostEqual(volatility, self.SIGMA * math.sqrt(12.2) * 100, places=1)

    def test_a_window_spanning_tiers_scales_each_return_by_its_own_gap(self):
        """The case a single factor cannot serve: one week-long gap among
        daily rows. Its return must count for a week, so the answer sits
        below reading everything as daily and above reading everything as
        weekly."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-10", "2020-01-13"]
        closes = frame({"A": [100.0, 110.0, 99.0, 108.9]}, dates)

        mixed = run(closes, one())["metrics"]["volatility"]
        all_daily = self._volatility_of(
            ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
        )
        all_weekly = self._volatility_of(
            ["2018-01-01", "2018-01-08", "2018-01-15", "2018-01-22"]
        )

        self.assertLess(mixed, all_daily)
        self.assertGreater(mixed, all_weekly)

    def test_a_flat_portfolio_has_no_volatility(self):
        closes = frame({"A": [100.0, 100.0, 100.0]},
                       ["2020-01-02", "2020-01-03", "2020-01-06"])

        self.assertEqual(run(closes, one())["metrics"]["volatility"], 0.0)


# ── Drawdown ─────────────────────────────────────────────────────────────────

class DrawdownTests(unittest.TestCase):
    def test_the_deepest_fall_is_reported_with_both_of_its_dates(self):
        """Peak 1200 on the 3rd, trough 900 on the 6th: -25%. The later
        recovery to 1100 does not erase the fall that happened."""
        closes = frame({"A": [100.0, 120.0, 90.0, 110.0]},
                       ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])

        drawdown = run(closes, one())["metrics"]["maxDrawdown"]

        self.assertAlmostEqual(drawdown["value"], -25.0, places=4)
        self.assertEqual(drawdown["peakDate"], "2020-01-03")
        self.assertEqual(drawdown["troughDate"], "2020-01-06")

    def test_a_run_that_only_rises_has_no_drawdown_and_no_dates(self):
        """Zero, and no dates to point at - naming the first date would
        invent a peak and a trough that never happened."""
        closes = frame({"A": [100.0, 110.0, 120.0]},
                       ["2020-01-02", "2020-01-03", "2020-01-06"])

        drawdown = run(closes, one())["metrics"]["maxDrawdown"]

        self.assertEqual(drawdown["value"], 0.0)
        self.assertIsNone(drawdown["peakDate"])
        self.assertIsNone(drawdown["troughDate"])

    def test_the_deepest_fall_wins_over_the_longest_one(self):
        closes = frame({"A": [100.0, 90.0, 100.0, 200.0, 120.0]},
                       ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"])

        drawdown = run(closes, one())["metrics"]["maxDrawdown"]

        self.assertAlmostEqual(drawdown["value"], -40.0, places=4)
        self.assertEqual(drawdown["peakDate"], "2020-01-07")
        self.assertEqual(drawdown["troughDate"], "2020-01-08")


# ── Per-holding metrics ──────────────────────────────────────────────────────

class PerHoldingTests(unittest.TestCase):
    def test_each_holding_reports_its_own_return_value_and_share(self):
        closes = frame({"UP": [100.0, 200.0], "FLAT": [100.0, 100.0]},
                       ["2020-01-02", "2020-06-01"])

        result = run(closes, [{"ticker": "UP", "weight": 50}, {"ticker": "FLAT", "weight": 50}])

        up, flat = holding(result, "UP"), holding(result, "FLAT")
        self.assertEqual(up["return"], 100.0)
        self.assertEqual(flat["return"], 0.0)
        self.assertEqual(up["finalValue"], 1000.0)
        self.assertAlmostEqual(up["share"], 66.6667, places=3)
        self.assertAlmostEqual(flat["share"], 33.3333, places=3)

    def test_contributions_add_up_to_the_portfolios_gain(self):
        closes = frame({"UP": [100.0, 200.0], "FLAT": [100.0, 100.0]},
                       ["2020-01-02", "2020-06-01"])

        result = run(closes, [{"ticker": "UP", "weight": 50}, {"ticker": "FLAT", "weight": 50}])

        gain = result["metrics"]["finalValue"] - result["metrics"]["startValue"]
        self.assertEqual(gain, 500.0)
        self.assertEqual(holding(result, "UP")["contribution"], 500.0)
        self.assertEqual(holding(result, "FLAT")["contribution"], 0.0)
        self.assertAlmostEqual(
            sum(h["contribution"] for h in result["holdings"]), gain, places=2
        )

    def test_contributions_still_add_up_once_a_rebalance_moves_money(self):
        """The point of netting the flows out: after February's rebalance
        FLAT holds 750 without having earned a cent of it, and UP holds 750
        having earned 500. A final value alone would credit them equally."""
        closes = frame({"UP": [100.0, 200.0, 200.0], "FLAT": [100.0, 100.0, 100.0]},
                       ["2020-01-02", "2020-01-15", "2020-02-03"])

        result = run(closes, [{"ticker": "UP", "weight": 50}, {"ticker": "FLAT", "weight": 50}],
                     rebalance="monthly")

        self.assertEqual(holding(result, "UP")["finalValue"], 750.0)
        self.assertEqual(holding(result, "FLAT")["finalValue"], 750.0)
        self.assertEqual(holding(result, "UP")["contribution"], 500.0)
        self.assertEqual(holding(result, "FLAT")["contribution"], 0.0)
        gain = result["metrics"]["finalValue"] - result["metrics"]["startValue"]
        self.assertAlmostEqual(
            sum(h["contribution"] for h in result["holdings"]), gain, places=2
        )

    def test_a_late_listing_holdings_return_runs_from_its_first_close(self):
        """There is no price before it listed, so its return cannot be
        measured from the window's start - and its contribution counts only
        the money that was actually in it."""
        closes = frame(
            {"OLD": [100.0, 100.0, 100.0], "NEW": [float("nan"), 50.0, 100.0]},
            ["2020-01-02", "2020-01-03", "2020-01-06"],
        )

        result = run(closes, [{"ticker": "OLD", "weight": 50}, {"ticker": "NEW", "weight": 50}])

        new = holding(result, "NEW")
        self.assertEqual(new["return"], 100.0)
        self.assertEqual(new["contribution"], 500.0)
        gain = result["metrics"]["finalValue"] - result["metrics"]["startValue"]
        self.assertAlmostEqual(
            sum(h["contribution"] for h in result["holdings"]), gain, places=2
        )

    def test_a_holding_that_never_listed_has_no_return_and_earned_nothing(self):
        """Its allocation sat in cash: no price return to report, and a
        contribution of exactly zero rather than a loss of the whole
        allocation."""
        closes = frame({"OLD": [100.0, 120.0]}, ["2020-01-02", "2020-02-03"])

        with patch("services.portfolio.resolve_ticker",
                   return_value={"symbol": "NEW", "name": "New Co", "tracked": False, "firstDate": "2021-01-04"}):
            result = run(closes, [{"ticker": "OLD", "weight": 50},
                                  {"ticker": "NEW", "weight": 50}])

        new = holding(result, "NEW")
        self.assertIsNone(new["return"])
        self.assertEqual(new["contribution"], 0.0)
        self.assertEqual(new["share"], 0.0)
        gain = result["metrics"]["finalValue"] - result["metrics"]["startValue"]
        self.assertAlmostEqual(
            sum(h["contribution"] for h in result["holdings"]), gain, places=2
        )


# ── Degenerate runs ──────────────────────────────────────────────────────────

class DegenerateRunTests(unittest.TestCase):
    def test_a_single_row_window_has_no_growth_rate_and_no_volatility(self):
        """Explicitly null, not 0: one observation supports neither claim."""
        closes = frame({"A": [100.0]}, ["2020-01-02"])

        metrics = run(closes, one())["metrics"]

        self.assertEqual(metrics["totalReturn"], 0.0)
        self.assertIsNone(metrics["cagr"])
        self.assertIsNone(metrics["volatility"])
        self.assertEqual(metrics["maxDrawdown"]["value"], 0.0)

    def test_two_rows_give_a_return_but_still_no_volatility(self):
        """One return has no dispersion to measure - reporting 0 would
        call a two-day holding riskless."""
        closes = frame({"A": [100.0, 110.0]}, ["2020-01-02", "2020-01-03"])

        metrics = run(closes, one())["metrics"]

        self.assertEqual(metrics["totalReturn"], 10.0)
        self.assertIsNone(metrics["volatility"])
        self.assertIsNotNone(metrics["cagr"])

    def test_a_portfolio_that_never_leaves_cash_is_flat_not_broken(self):
        closes = frame({"OLD": [100.0, 100.0]}, ["2020-01-02", "2020-02-03"])

        with patch("services.portfolio.resolve_ticker",
                   return_value={"symbol": "NEW", "name": "New Co", "tracked": False, "firstDate": "2021-01-04"}):
            metrics = run(closes, [{"ticker": "OLD", "weight": 50},
                                   {"ticker": "NEW", "weight": 50}])["metrics"]

        self.assertEqual(metrics["totalReturn"], 0.0)
        self.assertEqual(metrics["finalValue"], 1000.0)
        self.assertEqual(metrics["maxDrawdown"]["value"], 0.0)


# ── Metric reasons (issue #99) ────────────────────────────────────────────────

class MetricReasonTests(unittest.TestCase):
    """`metrics["reasons"]` is the same optional sidecar a measurement
    column's `per_ticker_reason` is, scoped to the portfolio's own named
    metrics instead of one per ticker."""

    def test_a_healthy_multi_row_run_carries_no_reasons_key_at_all(self):
        """Nothing is null, so there is nothing to explain - the key is
        absent, not present-and-empty, the same convention
        per_ticker_reason follows for a measurement with no nulls."""
        closes = frame({"A": [100.0, 110.0, 105.0]},
                       ["2020-01-02", "2020-01-03", "2020-01-06"])

        metrics = run(closes, one())["metrics"]

        self.assertNotIn("reasons", metrics)

    def test_a_single_row_window_explains_cagr_and_money_weighted_return(self):
        """No elapsed time is the one cause behind both nulls - see
        test_a_single_row_window_has_no_growth_rate_and_no_volatility for
        the values themselves."""
        closes = frame({"A": [100.0]}, ["2020-01-02"])

        metrics = run(closes, one())["metrics"]

        self.assertIn("cagr", metrics["reasons"])
        self.assertIn("moneyWeightedReturn", metrics["reasons"])
        self.assertIn("volatility", metrics["reasons"])

    def test_a_two_row_window_explains_volatility_and_may_explain_irr_too(self):
        """CAGR has real elapsed time to work with here and is never
        null - only volatility, which needs a second return to compare
        against, is guaranteed null. The money-weighted return can go
        either way: a one-day, 10%-return window is short enough that no
        annual rate, however large, discounts it back to the opening
        value within the bracket search's reach, so it is null too here -
        but that is a property of *this* fixture's return, not of every
        two-row window, so only volatility is asserted unconditionally."""
        closes = frame({"A": [100.0, 110.0]}, ["2020-01-02", "2020-01-03"])

        metrics = run(closes, one())["metrics"]

        self.assertIn("volatility", metrics["reasons"])
        self.assertIsNotNone(metrics["cagr"])
        self.assertNotIn("cagr", metrics["reasons"])

    def test_reason_strings_are_plain_literals_not_built_from_the_run(self):
        """Invariant 6, extended to this sidecar: a reason must not
        interpolate anything computed from the request or the price
        read - the row count is the one exception, and it is a plain
        int the module already had in hand, not fetched or user text."""
        closes = frame({"A": [100.0]}, ["2020-01-02"])

        metrics = run(closes, one())["metrics"]

        self.assertIsInstance(metrics["reasons"]["cagr"], str)
        self.assertNotIn("A", metrics["reasons"]["cagr"])


# ── Through the endpoint ─────────────────────────────────────────────────────

class MetricsRouteTests(unittest.TestCase):
    class _Client:
        rows = [
            {"ticker": "AAPL", "date": "2020-01-02", "close": 100.0},
            {"ticker": "MSFT", "date": "2020-01-02", "close": 50.0},
            {"ticker": "AAPL", "date": "2020-06-01", "close": 200.0},
            {"ticker": "MSFT", "date": "2020-06-01", "close": 50.0},
        ]

        def table(self, name):
            return self

        def select(self, *a, **k):
            return self

        def order(self, *a, **k):
            return self

        def in_(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def gte(self, *a, **k):
            return self

        def lte(self, *a, **k):
            return self

        def range(self, *a, **k):
            return self

        def execute(self):
            from types import SimpleNamespace
            return SimpleNamespace(data=self.rows)

    def test_the_response_carries_metrics_beside_the_series(self):
        body = {
            "holdings": [{"ticker": "AAPL", "weight": 60}, {"ticker": "MSFT", "weight": 40}],
            "value": 10_000,
            "start": "2020-01-01",
            "end": "2020-12-31",
        }
        with patch("services.market_data.get_client_optional", return_value=self._Client()):
            resp = client.post("/api/portfolio/simulate", json=body)

        self.assertEqual(resp.status_code, 200)
        metrics = resp.json()["metrics"]
        # 6000 in AAPL doubles, 4000 in MSFT is flat: 16000, up 60%.
        self.assertEqual(metrics["finalValue"], 16_000.0)
        self.assertEqual(metrics["totalReturn"], 60.0)
        self.assertEqual(set(metrics), {
            "startValue", "finalValue", "totalReturn", "cagr", "volatility", "maxDrawdown",
            # The account, as opposed to the portfolio (issue #67). Present
            # on every run, so a caller reads the same shape whether or not
            # anything was ever paid in.
            "contributed", "totalInvested", "gain", "moneyWeightedReturn",
            # What was paid out rather than what the price did (issue #68),
            # likewise present whether or not anything pays.
            "dividendIncome", "dividendYield", "incomeUnknownFor",
            # This fixture is only two rows, which is enough for a real
            # CAGR but not for volatility (issue #99) - `reasons` names
            # why, and is present here for exactly that reason rather than
            # by coincidence.
            "reasons",
        })
        self.assertIsNone(metrics["volatility"])
        self.assertIn("volatility", metrics["reasons"])
        self.assertNotIn("cagr", metrics["reasons"])
        # Nothing was paid in beyond the opening amount, so the two
        # families of number agree.
        self.assertEqual(metrics["contributed"], 0.0)
        self.assertEqual(metrics["totalInvested"], 10_000.0)
        self.assertEqual(metrics["gain"], 6_000.0)
        aapl = next(h for h in resp.json()["holdings"] if h["ticker"] == "AAPL")
        self.assertEqual(aapl["contribution"], 6_000.0)
        self.assertEqual(aapl["return"], 100.0)


if __name__ == "__main__":
    unittest.main()
