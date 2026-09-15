"""
Unit tests for services/stats.py (issue #98).

Every expected number here is worked out by hand in the test that asserts
it - the same discipline test_portfolio_metrics.py follows for the
simulator built on top of this module, and the reason that file's own
volatility/CAGR/drawdown tests are untouched by this move: they prove the
numbers did not change, and this file proves the arithmetic behind them
directly, independent of the simulator.

Two things get their own class:

  - **The trading-time scaling is the point.** A return that took a week
    to happen must not be read as a day's, however it is annualised
    afterwards - `DailyAndWeeklyAgreementTests` is the property issue #98
    asks this module to guarantee on its own: a genuine random walk,
    observed as daily rows or as its own weekly closes, annualises to
    close to the same volatility either way, not to two unrelated
    numbers.

  - **A figure a series cannot support is `None`, never zero** - too few
    rows, no variance to be sensitive to, or nothing to divide by all
    report `None`, checked for every function that can hit one of those
    edges.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import services.stats as stats


# ── Trading time and granularity ──────────────────────────────────────────────

class TradingDaysTests(unittest.TestCase):
    def test_a_gap_of_four_days_or_less_is_one_trading_day(self):
        """Friday to Monday is one day of market, not three - the same
        guard the simulator's own tests check at the portfolio level."""
        for gap in (1, 2, 3, 4):
            self.assertEqual(stats.trading_days(gap), 1.0)

    def test_a_wider_gap_scales_in_proportion(self):
        self.assertAlmostEqual(stats.trading_days(7), 7 * 252 / 365.25, places=6)
        self.assertAlmostEqual(stats.trading_days(30), 30 * 252 / 365.25, places=6)


class GranularityOfTests(unittest.TestCase):
    def test_a_single_row_is_daily(self):
        self.assertEqual(stats.granularity_of(["2020-01-02"]), "D")

    def test_consecutive_daily_gaps_are_daily(self):
        self.assertEqual(
            stats.granularity_of(["2020-01-02", "2020-01-03", "2020-01-06"]), "D"
        )

    def test_weekly_gaps_are_weekly(self):
        self.assertEqual(
            stats.granularity_of(["2020-01-01", "2020-01-08", "2020-01-15"]), "W"
        )

    def test_monthly_gaps_are_monthly(self):
        self.assertEqual(
            stats.granularity_of(["2020-01-01", "2020-02-01", "2020-03-01"]), "M"
        )

    def test_a_window_spanning_tiers_reports_its_coarsest_gap(self):
        """Two daily rows followed by a month-wide gap is only as fine as
        its coarsest stretch - the same reasoning that keeps
        `market_data.compute_correlation_matrix` from letting a fully-
        synced holding's own history be judged by a scarcer peer's."""
        self.assertEqual(
            stats.granularity_of(["2020-01-02", "2020-01-03", "2020-02-03"]), "M"
        )


# ── Returns, raw and scaled ───────────────────────────────────────────────────

class PeriodReturnsTests(unittest.TestCase):
    def test_simple_returns_between_consecutive_rows(self):
        returns = stats.period_returns(
            [100.0, 110.0, 99.0], ["2020-01-02", "2020-01-03", "2020-01-06"]
        )
        self.assertAlmostEqual(returns[0], 0.1, places=9)
        self.assertAlmostEqual(returns[1], -0.1, places=9)

    def test_a_non_positive_previous_value_contributes_no_return(self):
        returns = stats.period_returns(
            [0.0, 50.0, 100.0], ["2020-01-02", "2020-01-03", "2020-01-06"]
        )
        self.assertEqual(returns, [1.0])


class ScaledReturnsTests(unittest.TestCase):
    def test_a_daily_gap_is_unscaled(self):
        scaled = stats.scaled_returns([100.0, 110.0], ["2020-01-02", "2020-01-03"])
        self.assertAlmostEqual(scaled[0], 0.1, places=9)

    def test_a_weekly_gap_is_divided_by_root_trading_time(self):
        scaled = stats.scaled_returns([100.0, 110.0], ["2020-01-01", "2020-01-08"])
        expected = 0.1 / math.sqrt(7 * 252 / 365.25)
        self.assertAlmostEqual(scaled[0], expected, places=9)


# ── Volatility ───────────────────────────────────────────────────────────────

class VolatilityTests(unittest.TestCase):
    # Returns of +10%, -10%, +10%: mean 1/30, sample standard deviation
    # sqrt(0.0266.../2) = 0.11547 - the same fixture
    # test_portfolio_metrics.py's VolatilityTests uses, called here
    # directly against stats.volatility rather than through the simulator.
    SIGMA = 0.1154700538
    WEEK = 7 * 252 / 365.25

    def _value(self, dates):
        return stats.volatility([100.0, 110.0, 99.0, 108.9], dates)["value"]

    def test_daily_rows_are_the_textbook_daily_standard_deviation(self):
        self.assertAlmostEqual(
            self._value(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]),
            self.SIGMA * math.sqrt(252) * 100,
            places=2,
        )

    def test_weekly_buckets_are_scaled_by_the_trading_time_they_cover(self):
        self.assertAlmostEqual(
            self._value(["2018-01-01", "2018-01-08", "2018-01-15", "2018-01-22"]),
            self.SIGMA / math.sqrt(self.WEEK) * math.sqrt(252) * 100,
            places=2,
        )

    def test_a_flat_series_has_no_volatility(self):
        value = stats.volatility(
            [100.0, 100.0, 100.0], ["2020-01-02", "2020-01-03", "2020-01-06"]
        )["value"]
        self.assertEqual(value, 0.0)

    def test_a_single_row_is_null_not_zero(self):
        self.assertIsNone(stats.volatility([100.0], ["2020-01-02"])["value"])

    def test_two_rows_give_a_return_but_still_no_volatility(self):
        """One return has no dispersion to measure - null, not 0, matching
        issue #98's acceptance criterion directly at the stats.py level."""
        result = stats.volatility([100.0, 110.0], ["2020-01-02", "2020-01-03"])
        self.assertIsNone(result["value"])

    def test_volatility_reports_the_granularity_it_was_computed_on(self):
        daily = stats.volatility(
            [100.0, 110.0, 99.0], ["2020-01-02", "2020-01-03", "2020-01-06"]
        )
        weekly = stats.volatility(
            [100.0, 110.0, 99.0], ["2020-01-01", "2020-01-08", "2020-01-15"]
        )
        self.assertEqual(daily["granularity"], "D")
        self.assertEqual(weekly["granularity"], "W")


class DailyAndWeeklyAgreementTests(unittest.TestCase):
    def test_a_daily_random_walk_and_its_weekly_close_annualise_close_together(self):
        """The statistical property behind the trading-time scaling: for
        a return series with no serial correlation, variance scales
        linearly with elapsed time, so annualising daily returns by root
        252 and annualising the same walk's own weekly closes by root 52
        should agree up to sampling noise - not to two figures that read
        the same risk as though it happened at two different speeds.

        A fixed seed keeps this reproducible; 250 simulated trading days
        (about a year, the size of window this scaling actually has to
        serve) is enough samples that the two annualised figures land
        within a few points of each other without the test being able to
        flake. This is the "within rounding" acceptance criterion from
        issue #98, demonstrated statistically rather than by an identity
        that would only hold for a literally noiseless series.
        """
        rng = random.Random(20240601)
        prices = [100.0]
        for _ in range(250):
            prices.append(prices[-1] * (1 + rng.gauss(0, 0.01)))

        start = pd.Timestamp("2022-01-03")
        daily_dates = [(start + pd.Timedelta(days=i)).date().isoformat() for i in range(len(prices))]

        # The last close of every 5-trading-day block, at the same
        # ~7-calendar-day spacing a real ISO week covers - the same "last
        # close of the bucket, dated by its anchor" rule prices' own
        # weekly tier is built on (issue #10).
        weekly_prices = prices[4::5]
        weekly_dates = [
            (start + pd.Timedelta(days=7 * k)).date().isoformat() for k in range(len(weekly_prices))
        ]

        daily_vol = stats.volatility(prices, daily_dates)["value"]
        weekly_vol = stats.volatility(weekly_prices, weekly_dates)["value"]

        self.assertAlmostEqual(daily_vol, weekly_vol, delta=3.0)


# ── Downside deviation ─────────────────────────────────────────────────────────

class DownsideDeviationTests(unittest.TestCase):
    def test_only_the_shortfall_below_target_counts(self):
        """Returns of +10%, -10%, +10%: unlike volatility, which measures
        every return's distance from the *mean*, only the -10% return is
        a shortfall below the target (0 by default) - the sum of squared
        shortfalls is just 0.1**2, the other two contributing nothing."""
        result = stats.downside_deviation(
            [100.0, 110.0, 99.0, 108.9],
            ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"],
        )
        expected = math.sqrt((0.1 ** 2) / 3) * math.sqrt(252) * 100
        self.assertAlmostEqual(result["value"], expected, places=2)

    def test_a_series_that_never_falls_has_no_downside_deviation(self):
        result = stats.downside_deviation(
            [100.0, 110.0, 120.0, 130.0],
            ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"],
        )
        self.assertEqual(result["value"], 0.0)

    def test_fewer_than_two_returns_is_null(self):
        result = stats.downside_deviation([100.0, 110.0], ["2020-01-02", "2020-01-03"])
        self.assertIsNone(result["value"])


# ── CAGR ─────────────────────────────────────────────────────────────────────

class CagrTests(unittest.TestCase):
    def test_doubling_over_two_years_is_not_a_100_percent_annual_rate(self):
        """2020-01-01 to 2022-01-01 is 731 days, so the rate is
        2 ** (365.25/731) - 1 = 41.39% - the same fixture
        test_portfolio_metrics.py checks through the simulator."""
        value = stats.cagr([100.0, 200.0], ["2020-01-01", "2022-01-01"])
        self.assertAlmostEqual(value, 41.3876, places=3)

    def test_a_single_row_has_no_growth_rate(self):
        self.assertIsNone(stats.cagr([100.0], ["2020-01-02"]))

    def test_the_same_year_sampled_finely_or_coarsely_annualises_identically(self):
        monthly_values = [100.0 * (1.01 ** i) for i in range(13)]
        monthly_dates = [f"2021-{month:02d}-01" for month in range(1, 13)] + ["2022-01-01"]
        endpoint_values = [100.0, 100.0 * (1.01 ** 12)]
        endpoint_dates = ["2021-01-01", "2022-01-01"]

        self.assertAlmostEqual(
            stats.cagr(monthly_values, monthly_dates),
            stats.cagr(endpoint_values, endpoint_dates),
            places=6,
        )


# ── Max drawdown and underwater stretches ─────────────────────────────────────

class MaxDrawdownTests(unittest.TestCase):
    def test_the_deepest_fall_is_reported_with_both_dates(self):
        result = stats.max_drawdown(
            [100.0, 120.0, 90.0, 110.0],
            ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"],
        )
        self.assertAlmostEqual(result["value"], -25.0, places=4)
        self.assertEqual(result["peakDate"], "2020-01-03")
        self.assertEqual(result["troughDate"], "2020-01-06")

    def test_a_run_that_only_rises_has_no_drawdown_and_no_dates(self):
        result = stats.max_drawdown(
            [100.0, 110.0, 120.0], ["2020-01-02", "2020-01-03", "2020-01-06"]
        )
        self.assertEqual(result["value"], 0.0)
        self.assertIsNone(result["peakDate"])
        self.assertIsNone(result["troughDate"])


class UnderwaterStretchesTests(unittest.TestCase):
    def test_a_closed_stretch_and_a_still_open_one(self):
        """100 -> 90 (underwater starts) -> 95 (still underwater, same
        trough) -> 100 (recovers, stretch closes) -> 80 (a new, deeper
        stretch starts) -> 85 -> 90 (still below the 100 peak when the
        series ends, so this one stays open)."""
        values = [100.0, 90.0, 95.0, 100.0, 80.0, 85.0, 90.0]
        dates = [
            "2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07",
            "2020-01-08", "2020-01-09", "2020-01-10",
        ]

        stretches = stats.underwater_stretches(values, dates)["stretches"]

        self.assertEqual(len(stretches), 2)
        self.assertEqual(
            stretches[0],
            {"start": "2020-01-03", "trough": "2020-01-03", "end": "2020-01-07", "depth": -10.0},
        )
        self.assertEqual(
            stretches[1],
            {"start": "2020-01-08", "trough": "2020-01-08", "end": None, "depth": -20.0},
        )

    def test_a_series_that_only_rises_has_no_stretches(self):
        result = stats.underwater_stretches(
            [100.0, 110.0, 120.0], ["2020-01-02", "2020-01-03", "2020-01-06"]
        )
        self.assertEqual(result["stretches"], [])


class PainIndexTests(unittest.TestCase):
    def test_time_weighted_average_drawdown(self):
        """100 for one day (no drawdown), then 50 for the next day (50%
        drawdown persisting for one more day before the series ends):
        weighted = 0*1 + 0.5*1 = 0.5, over 2 total days = 25%."""
        result = stats.pain_index([100.0, 50.0, 50.0], ["2020-01-01", "2020-01-02", "2020-01-03"])
        self.assertAlmostEqual(result["value"], 25.0, places=4)

    def test_a_series_that_never_falls_has_no_pain(self):
        result = stats.pain_index(
            [100.0, 110.0, 120.0], ["2020-01-02", "2020-01-03", "2020-01-06"]
        )
        self.assertEqual(result["value"], 0.0)

    def test_a_single_row_is_null(self):
        self.assertIsNone(stats.pain_index([100.0], ["2020-01-02"])["value"])


# ── Unit values ──────────────────────────────────────────────────────────────

class UnitValuesTests(unittest.TestCase):
    def test_no_inflows_returns_the_same_object(self):
        values = [100.0, 110.0]
        self.assertIs(stats.unit_values(values, [0.0, 0.0]), values)

    def test_an_inflow_is_backed_out_before_the_next_steps_growth(self):
        """1000 grows organically to 1100, then a 100 contribution lands,
        for an observed total of 1200 - the unit value reads the day's
        organic growth alone: (1200 - 100) / 1000 = 1.1, i.e. 1100."""
        units = stats.unit_values([1000.0, 1200.0], [0.0, 100.0])
        self.assertAlmostEqual(units[1], 1100.0, places=6)


# ── Beta, R-squared, idiosyncratic volatility ─────────────────────────────────

class BetaRSquaredIdiosyncraticVolatilityTests(unittest.TestCase):
    # The asset's return is exactly twice the benchmark's at every step -
    # a perfect, noiseless linear relationship to check the three
    # functions against by hand.
    DATES = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
    BENCHMARK = [100.0, 110.0, 99.0, 108.9]
    ASSET = [100.0, 120.0, 96.0, 115.2]

    def test_beta_is_the_ratio_of_returns_when_they_move_in_lockstep(self):
        result = stats.beta(self.ASSET, self.BENCHMARK, self.DATES)
        self.assertAlmostEqual(result["value"], 2.0, places=4)

    def test_r_squared_is_one_for_a_perfect_linear_relationship(self):
        result = stats.r_squared(self.ASSET, self.BENCHMARK, self.DATES)
        self.assertAlmostEqual(result["value"], 1.0, places=4)

    def test_idiosyncratic_volatility_is_zero_when_r_squared_is_one(self):
        """Nothing is left over once a perfect single factor explains all
        of it."""
        result = stats.idiosyncratic_volatility(self.ASSET, self.BENCHMARK, self.DATES)
        self.assertAlmostEqual(result["value"], 0.0, places=2)

    def test_a_flat_benchmark_has_no_beta(self):
        """A flat benchmark has no variance to be sensitive to - any beta
        would be dividing by zero."""
        result = stats.beta(self.ASSET, [100.0, 100.0, 100.0, 100.0], self.DATES)
        self.assertIsNone(result["value"])

    def test_fewer_than_two_paired_returns_is_null(self):
        result = stats.beta([100.0, 110.0], [100.0, 105.0], ["2020-01-02", "2020-01-03"])
        self.assertIsNone(result["value"])


# ── Capture ratios ───────────────────────────────────────────────────────────

class CaptureTests(unittest.TestCase):
    # Benchmark rises 10%, rises 10%, then falls 10%. The asset rises 15%
    # and 8% over the same two up periods, and falls 5% over the down one.
    DATES = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
    BENCHMARK = [100.0, 110.0, 121.0, 108.9]
    ASSET = [100.0, 115.0, 124.2, 117.99]

    def test_up_capture(self):
        # asset: 1.15 * 1.08 = 1.242; benchmark: 1.1 * 1.1 = 1.21.
        # (1.242 - 1) / (1.21 - 1) * 100.
        result = stats.up_capture(self.ASSET, self.BENCHMARK, self.DATES)
        self.assertAlmostEqual(result["value"], (0.242 / 0.21) * 100, places=3)

    def test_down_capture(self):
        # asset: 0.95; benchmark: 0.9. (0.95 - 1) / (0.9 - 1) * 100 = 50.
        result = stats.down_capture(self.ASSET, self.BENCHMARK, self.DATES)
        self.assertAlmostEqual(result["value"], 50.0, places=4)

    def test_no_up_periods_is_null(self):
        result = stats.up_capture(
            [100.0, 95.0], [100.0, 90.0], ["2020-01-02", "2020-01-03"]
        )
        self.assertIsNone(result["value"])


# ── Concentration ────────────────────────────────────────────────────────────

class HerfindahlEffectiveNTests(unittest.TestCase):
    def test_equal_weights(self):
        weights = [25.0, 25.0, 25.0, 25.0]
        self.assertAlmostEqual(stats.herfindahl(weights), 0.25, places=6)
        self.assertAlmostEqual(stats.effective_n(weights), 4.0, places=6)

    def test_a_concentrated_portfolio_has_a_low_effective_n(self):
        weights = [90.0, 5.0, 5.0]
        self.assertAlmostEqual(stats.herfindahl(weights), 0.9 ** 2 + 0.05 ** 2 + 0.05 ** 2, places=6)
        self.assertLess(stats.effective_n(weights), 1.5)

    def test_an_empty_portfolio_has_no_concentration(self):
        self.assertIsNone(stats.herfindahl([]))
        self.assertIsNone(stats.effective_n([]))


# ── Risk contribution ────────────────────────────────────────────────────────

class RiskContributionTests(unittest.TestCase):
    def test_equal_variance_uncorrelated_holdings_split_risk_evenly(self):
        """A and B: +2%/+2%/-2%/-2% and +2%/-2%/+2%/-2% - equal variance
        by construction, and the products of the two return sequences
        sum to exactly zero, so their sample covariance is exactly zero
        too. Equally weighted and equally variable with nothing shared
        between them, they must split the portfolio's risk exactly in
        half."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        a_values = [100.0, 102.0, 104.04, 101.9592, 99.920016]
        b_values = [100.0, 102.0, 99.96, 101.9592, 99.920016]

        result = stats.risk_contribution({"A": a_values, "B": b_values}, dates, {"A": 0.5, "B": 0.5})

        self.assertAlmostEqual(result["A"], 50.0, places=2)
        self.assertAlmostEqual(result["B"], 50.0, places=2)
        self.assertAlmostEqual(result["A"] + result["B"], 100.0, places=4)

    def test_a_flat_portfolio_has_no_risk_to_apportion(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06"]
        flat = [100.0, 100.0, 100.0]

        result = stats.risk_contribution({"A": flat, "B": flat}, dates, {"A": 0.5, "B": 0.5})

        self.assertIsNone(result["A"])
        self.assertIsNone(result["B"])


# ── Diversification ratio (issue #105) ─────────────────────────────────────────

class DiversificationRatioTests(unittest.TestCase):
    def test_equal_variance_uncorrelated_holdings_give_sqrt_2(self):
        """Same A/B construction as RiskContributionTests above: equal
        variance, exactly zero sample covariance. For two equally
        weighted, equal-variance, uncorrelated holdings the ratio has a
        closed form - portfolio variance is half of either holding's own
        variance, so sigma_fund = sigma / sqrt(2) while the weighted
        average of the two holdings' own sigma is just sigma itself,
        giving a ratio of exactly sqrt(2)."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        a_values = [100.0, 102.0, 104.04, 101.9592, 99.920016]
        b_values = [100.0, 102.0, 99.96, 101.9592, 99.920016]

        ratio = stats.diversification_ratio({"A": a_values, "B": b_values}, dates, {"A": 0.5, "B": 0.5})

        self.assertAlmostEqual(ratio, 2 ** 0.5, places=3)

    def test_identical_holdings_move_in_lockstep_and_never_diversify(self):
        """Two holdings with identical returns have identical variance
        and covariance, so the ratio collapses to exactly 1 regardless of
        weights - the Cauchy-Schwarz lower bound, met with equality."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
        values = [100.0, 103.0, 101.0, 105.0]

        ratio = stats.diversification_ratio(
            {"A": values, "B": list(values)}, dates, {"A": 0.5, "B": 0.5}
        )

        self.assertAlmostEqual(ratio, 1.0, places=6)

    def test_scaling_every_weight_by_the_same_factor_does_not_move_the_ratio(self):
        """Both the numerator and the denominator scale by the same
        factor under a uniform weight rescaling, so a basket whose
        tracked weights sum to less than 100 (issue #105's own coverage
        gap) reads the same ratio as if they had been renormalised to
        sum to 1 first."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        a_values = [100.0, 102.0, 104.04, 101.9592, 99.920016]
        b_values = [100.0, 102.0, 99.96, 101.9592, 99.920016]
        values_by_ticker = {"A": a_values, "B": b_values}

        normalised = stats.diversification_ratio(values_by_ticker, dates, {"A": 0.5, "B": 0.5})
        raw_weights = stats.diversification_ratio(values_by_ticker, dates, {"A": 35.0, "B": 35.0})

        self.assertAlmostEqual(normalised, raw_weights, places=6)

    def test_a_flat_basket_has_no_variance_to_divide_by(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06"]
        flat = [100.0, 100.0, 100.0]

        ratio = stats.diversification_ratio({"A": flat, "B": flat}, dates, {"A": 0.5, "B": 0.5})

        self.assertIsNone(ratio)

    def test_fewer_than_two_aligned_returns_is_null(self):
        ratio = stats.diversification_ratio(
            {"A": [100.0], "B": [100.0]}, ["2020-01-02"], {"A": 0.5, "B": 0.5}
        )
        self.assertIsNone(ratio)


if __name__ == "__main__":
    unittest.main()
