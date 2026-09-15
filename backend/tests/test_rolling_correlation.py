"""
Tests for the Rolling Correlation measurement (issue #110): a holding's
correlation to its fund as a path over the window, not a single average.

services/stats.py's own rolling_correlation arithmetic (series length,
block anchoring, the null rule) is covered by test_stats.py's
RollingCorrelationTests; this file pins down what only makes sense at the
measurement level:

  - A holding whose correlation rose shows a positive change and a
    rising, real <Spark> series - not the two-point fallback.
  - A window too short for two full blocks is null with a reason.
  - The column sorts by the change, not by the last block's own reading
    (per_ticker really is the change, confirmed against a case where the
    two would disagree).
  - The private "_rolling_series" compute() uses to hand render_cell the
    real path never leaks into the actual response.

...plus the shared registry contract: manifest registration, a doc page,
and a real worked example.

No test here touches Supabase or yfinance: measurements.inputs.holdings.
get_etf_holdings and measurements.inputs.price_frame.get_price_frame are
patched with synthetic data throughout - both at their own origin module,
which is the one place get_fund_index's call to get_aligned_closes (and
that function's own call to get_price_frame) always resolves regardless
of which plugin reached it (see test_fund_relation_measurements.py's own
_patched for the full reasoning; rolling_correlation.py reaches both
exclusively through measurements.inputs.fund_index, never directly).

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import random
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS
from main import app
from measurements import ALL_MEASUREMENTS
from measurements.official_measurements.rolling_correlation import ROLLING_PERIODS

client = TestClient(app, raise_server_exceptions=False)


def _to_values(returns, start=100.0):
    values = [start]
    for r in returns:
        values.append(values[-1] * (1 + r))
    return values


def _dated(n):
    return [f"2020-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]


def _closes(values_by_ticker: dict[str, list[float]], dates: list[str]) -> dict:
    """The measurements.inputs.price_frame.get_price_frame shape."""
    return {
        t: {"closes": [[d, v] for d, v in zip(dates, values)]}
        for t, values in values_by_ticker.items()
    }


@contextmanager
def _patched(holdings, closes_by_ticker):
    with (
        patch("measurements.inputs.holdings.get_etf_holdings", return_value=(holdings, False)),
        patch("measurements.inputs.price_frame.get_price_frame", return_value=closes_by_ticker),
    ):
        yield


def _by_id():
    return {m.id: m for m in ALL_MEASUREMENTS}


def _plugin():
    return _by_id()["rolling_correlation"]


class RisingCorrelationTests(unittest.TestCase):
    def test_a_holding_moving_toward_the_fund_shows_a_positive_change_and_a_real_series(self):
        # Three blocks, not two, so the real per-block series (asserted
        # below) is provably richer than the two-point [0, change]
        # fallback render_cell alone would produce - both would otherwise
        # happen to have the same length.
        rng = random.Random(11)
        bench_returns = [rng.uniform(-0.03, 0.03) for _ in range(3 * ROLLING_PERIODS)]
        early_asset = [rng.uniform(-0.03, 0.03) for _ in range(ROLLING_PERIODS)]
        middle_asset = [rng.uniform(-0.03, 0.03) for _ in range(ROLLING_PERIODS)]
        late_asset = bench_returns[2 * ROLLING_PERIODS:]  # exact copy in the last block -> rho = 1
        asset_returns = early_asset + middle_asset + late_asset

        dates = _dated(3 * ROLLING_PERIODS + 1)
        # A single holding IS the fund's own weighted index at 100%
        # weight, so the "benchmark" the plugin builds would be AAA's own
        # series with nothing to compare against unless a second ticker
        # gives the fund a shape of its own - FUND supplies that shape.
        holdings = [["AAA", 1.0], ["FUND", 99.0]]
        closes = _closes({"AAA": _to_values(asset_returns), "FUND": _to_values(bench_returns)}, dates)

        with _patched(holdings, closes):
            result = _plugin().run(etf_id="TESTFUND1", window="1y")

        self.assertIsNotNone(result["per_ticker"]["AAA"])
        self.assertGreater(result["per_ticker"]["AAA"], 0)

        mdx = result["per_ticker_mdx"]["AAA"]
        self.assertIn("<Spark", mdx)
        self.assertIn('color="var(--accent)"', mdx)
        # The real per-block series has more than the two-point fallback
        # render_cell alone would produce - proof the true path, not just
        # the scalar, reached the rendered cell.
        values_literal = mdx.split("values=")[1].split(" baseline")[0]
        points = [float(v) for v in values_literal.strip("{}[]").split(",")]
        self.assertEqual(len(points), 3)
        self.assertLess(points[0], points[-1])

    def test_a_holding_moving_away_from_the_fund_shows_a_negative_change(self):
        rng = random.Random(12)
        bench_returns = [rng.uniform(-0.03, 0.03) for _ in range(2 * ROLLING_PERIODS)]
        early_asset = bench_returns[:ROLLING_PERIODS]  # exact copy in the first block -> rho = 1
        late_asset = [rng.uniform(-0.03, 0.03) for _ in range(ROLLING_PERIODS)]
        asset_returns = early_asset + late_asset

        dates = _dated(2 * ROLLING_PERIODS + 1)
        holdings = [["AAA", 1.0], ["FUND", 99.0]]
        closes = _closes({"AAA": _to_values(asset_returns), "FUND": _to_values(bench_returns)}, dates)

        with _patched(holdings, closes):
            result = _plugin().run(etf_id="TESTFUND2", window="1y")

        self.assertLess(result["per_ticker"]["AAA"], 0)
        self.assertIn('color="var(--negative)"', result["per_ticker_mdx"]["AAA"])


class ShortWindowNullTests(unittest.TestCase):
    def test_fewer_than_two_full_blocks_is_null_with_a_reason(self):
        rng = random.Random(13)
        n = ROLLING_PERIODS + 10  # one full block, plus a partial leftover
        returns = [rng.uniform(-0.02, 0.02) for _ in range(n)]
        bench = [rng.uniform(-0.02, 0.02) for _ in range(n)]
        dates = _dated(n + 1)
        holdings = [["AAA", 1.0], ["FUND", 99.0]]
        closes = _closes({"AAA": _to_values(returns), "FUND": _to_values(bench)}, dates)

        with _patched(holdings, closes):
            result = _plugin().run(etf_id="TESTFUND3", window="1y")

        self.assertIsNone(result["per_ticker"]["AAA"])
        self.assertIn("AAA", result["per_ticker_reason"])
        self.assertEqual(result["per_ticker_mdx"]["AAA"], "—")

    def test_a_holding_missing_from_the_fund_index_is_null_with_its_own_reason(self):
        """A single-holding fund can't build a benchmark to compare
        against at all (fund_index needs >= 2 complete series)."""
        holdings = [["AAA", 100.0]]
        closes = _closes({"AAA": [100.0, 101.0, 102.0]}, ["2020-01-01", "2020-01-02", "2020-01-03"])

        with _patched(holdings, closes):
            result = _plugin().run(etf_id="TESTFUND4", window="1y")

        self.assertIsNone(result["per_ticker"]["AAA"])
        self.assertIn("AAA", result["per_ticker_reason"])


class SortsByChangeNotLastValueTests(unittest.TestCase):
    def test_per_ticker_is_the_change_not_the_final_blocks_own_reading(self):
        """AAA ends its window at a lower rolling rho than BBB, but AAA
        moved further *toward* the fund over the window than BBB did.
        If this column sorted by the last reading, BBB would rank above
        AAA; sorting by the change (as the issue requires) ranks AAA
        above BBB instead."""
        rng = random.Random(14)
        bench_returns = [rng.uniform(-0.03, 0.03) for _ in range(2 * ROLLING_PERIODS)]

        # AAA: uncorrelated early, moderately correlated late (rho ~ 0.5
        # scale mix) - a real but modest rise.
        aaa_late = [0.5 * b + rng.uniform(-0.01, 0.01) for b in bench_returns[ROLLING_PERIODS:]]
        aaa_returns = [rng.uniform(-0.03, 0.03) for _ in range(ROLLING_PERIODS)] + aaa_late

        # BBB: already strongly correlated early AND late, but very
        # slightly less so at the end than AAA's late reading - its own
        # last reading beats AAA's, even though its change is ~flat.
        bbb_early = list(bench_returns[:ROLLING_PERIODS])
        bbb_late = list(bench_returns[ROLLING_PERIODS:])
        bbb_returns = bbb_early + bbb_late

        dates = _dated(2 * ROLLING_PERIODS + 1)
        holdings = [["AAA", 1.0], ["BBB", 1.0], ["FUND", 98.0]]
        closes = _closes(
            {
                "AAA": _to_values(aaa_returns),
                "BBB": _to_values(bbb_returns),
                "FUND": _to_values(bench_returns),
            },
            dates,
        )

        with _patched(holdings, closes):
            result = _plugin().run(etf_id="TESTFUND5", window="1y")

        aaa_change, bbb_change = result["per_ticker"]["AAA"], result["per_ticker"]["BBB"]
        self.assertIsNotNone(aaa_change)
        self.assertIsNotNone(bbb_change)
        # BBB is correlated near 1.0 throughout (near-zero change); AAA's
        # own change is the larger, genuinely positive move.
        self.assertGreater(aaa_change, bbb_change)


class PrivateSeriesNeverLeaksTests(unittest.TestCase):
    def test_the_internal_rolling_series_is_not_part_of_the_response(self):
        rng = random.Random(15)
        bench_returns = [rng.uniform(-0.02, 0.02) for _ in range(2 * ROLLING_PERIODS)]
        asset_returns = list(bench_returns)
        dates = _dated(2 * ROLLING_PERIODS + 1)
        holdings = [["AAA", 1.0], ["FUND", 99.0]]
        closes = _closes({"AAA": _to_values(asset_returns), "FUND": _to_values(bench_returns)}, dates)

        with _patched(holdings, closes):
            result = _plugin().run(etf_id="TESTFUND6", window="1y")

        self.assertNotIn("_rolling_series", result)


class RenderCellFallbackTests(unittest.TestCase):
    """render_cell in isolation (no series) is the ABC-required, honest
    two-point fallback - exercised directly here since run() never calls
    it this way in the real flow (see rolling_correlation.py's own run()
    override)."""

    def test_none_is_a_dash(self):
        self.assertEqual(_plugin().render_cell("AAA", None, "rolling_correlation"), "—")

    def test_a_real_value_with_no_series_still_renders_a_two_point_spark(self):
        mdx = _plugin().render_cell("AAA", 0.42, "rolling_correlation")
        self.assertIn("<Spark", mdx)
        self.assertIn("values={[0, 0.42]}", mdx)


class WindowAwarenessTests(unittest.TestCase):
    def test_shares_the_measurement_window_vocabulary(self):
        m = _plugin()
        self.assertEqual(m.window_options, MEASUREMENT_WINDOW_OPTIONS)
        self.assertEqual(m.window_default, MEASUREMENT_WINDOW_DEFAULT)


class ManifestAndDocEndpointTests(unittest.TestCase):
    def test_registered_in_the_manifest(self):
        resp = client.get("/api/measurements")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("rolling_correlation", {e["measurement_id"] for e in resp.json()})

    def test_has_a_written_doc(self):
        resp = client.get("/api/measurement-docs/rolling_correlation")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["has_doc"])

    def test_worked_example_runs_end_to_end_with_a_real_series(self):
        rng = random.Random(16)
        bench_returns = [rng.uniform(-0.02, 0.02) for _ in range(2 * ROLLING_PERIODS)]
        asset_returns = list(bench_returns)
        dates = _dated(2 * ROLLING_PERIODS + 1)
        holdings = [["AAA", 1.0], ["BBB", 1.0], ["FUND", 98.0]]
        closes = _closes(
            {"AAA": _to_values(asset_returns), "BBB": _to_values(bench_returns), "FUND": _to_values(bench_returns)},
            dates,
        )

        with _patched(holdings, closes):
            resp = client.get("/api/measurement-docs/rolling_correlation/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("per_ticker", body)
        self.assertIn("per_ticker_mdx", body)
        self.assertEqual(body["window"], MEASUREMENT_WINDOW_DEFAULT)


if __name__ == "__main__":
    unittest.main()
