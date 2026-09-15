"""
Tests for the "computed from a holding's own price history" measurements
(issue #108): Volatility, Max Drawdown, and 1Y Return & Momentum.

services/stats.py's own arithmetic (total_return, momentum, and the
existing volatility/max_drawdown) is covered by test_stats.py; this file
pins down the acceptance criteria that only make sense at the measurement
level:

  - Volatility for a given series equals what the portfolio simulator
    reports for the same series.
  - 1Y return equals last close over first close minus one on the
    adjusted series.
  - Momentum differs from the return column by exactly the skipped
    month.
  - Max drawdown is never positive.
  - A short-history holding reports null with a reason, across all
    three plugins.

...plus the shared registry contract every measurement here follows:
window awareness, a doc page, and a real worked example - including
return_momentum's own multi-column one (issue #107 taught examples.py
and WorkedExample.jsx to support this shape; this is simply its second
real user).

No test here touches Supabase or yfinance: measurements.inputs.holdings.
get_etf_holdings and measurements.inputs.price_frame.get_price_frame are
patched with synthetic data throughout.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from fastapi.testclient import TestClient

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS
from main import app
from measurements import ALL_MEASUREMENTS
from services.portfolio import simulate_portfolio

client = TestClient(app, raise_server_exceptions=False)

PLUGIN_IDS = ["volatility", "max_drawdown", "return_momentum"]


def _closes(values_by_ticker: dict[str, list[float]], dates: list[str]) -> dict:
    """The measurements.inputs.price_frame.get_price_frame shape:
    {ticker: {"closes": [[date, value], ...]}}."""
    return {
        t: {"closes": [[d, v] for d, v in zip(dates, values)]}
        for t, values in values_by_ticker.items()
    }


def _pd_frame(values_by_ticker: dict[str, list[float]], dates: list[str]) -> pd.DataFrame:
    """The services.portfolio.get_closes shape: a wide date x ticker frame."""
    return pd.DataFrame(values_by_ticker, index=pd.to_datetime(dates))


@contextmanager
def _patched(holdings, closes_by_ticker):
    """Patch every seam a plugin under test might reach `get_holdings`/
    `get_price_frame` through.

    `get_holdings` is safe to patch once, at `measurements.inputs.
    holdings.get_etf_holdings` - `get_holdings` is defined in that module,
    so its own bare-name lookup of `get_etf_holdings` always resolves
    there regardless of which other module imported `get_holdings` itself
    (see test_fund_relation_measurements.py's own `_patched` for the full
    reasoning). `get_price_frame` has no such single point here: each of
    this file's plugins does `from measurements.inputs.price_frame import
    get_price_frame` directly into its own module namespace, a distinct
    binding unittest.mock can't reach by patching the origin - so every
    consuming module's own copy is patched individually instead.
    """
    with (
        patch("measurements.inputs.holdings.get_etf_holdings", return_value=(holdings, False)),
        patch("measurements.official_measurements.volatility.get_price_frame", return_value=closes_by_ticker),
        patch("measurements.official_measurements.max_drawdown.get_price_frame", return_value=closes_by_ticker),
        patch("measurements.official_measurements.return_momentum.get_price_frame", return_value=closes_by_ticker),
    ):
        yield


def _by_id():
    return {m.id: m for m in ALL_MEASUREMENTS}


# ── Volatility matches the simulator ────────────────────────────────────────

class VolatilityMatchesSimulatorTests(unittest.TestCase):
    def test_volatility_equals_the_simulators_own_figure_for_the_same_series(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        values = [100.0, 105.0, 98.0, 110.0, 102.0]
        holdings = [["AAA", 100.0]]

        with _patched(holdings, _closes({"AAA": values}, dates)):
            measurement_result = _by_id()["volatility"].run(etf_id="TESTFUND1", window="1y")

        # A single-holding, 100%-weighted, no-rebalance, no-contribution
        # portfolio over the exact same series: its own totals ARE that
        # series (unit_values is the identity with no contributions), so
        # the simulator's own volatility metric must read the same number.
        with (
            patch("services.portfolio.get_closes", return_value=_pd_frame({"AAA": values}, dates)),
            patch("services.portfolio.get_dividends", return_value={}),
            patch("services.portfolio.tracked_tickers", return_value=set()),
        ):
            run = simulate_portfolio(
                holdings=[{"ticker": "AAA", "weight": 100}],
                value=10_000.0, start=dates[0], end=dates[-1],
            )

        self.assertIsNotNone(measurement_result["per_ticker"]["AAA"])
        self.assertAlmostEqual(
            measurement_result["per_ticker"]["AAA"], run["metrics"]["volatility"], places=4
        )


# ── Max drawdown is never positive ──────────────────────────────────────────

class MaxDrawdownNeverPositiveTests(unittest.TestCase):
    def test_max_drawdown_is_never_positive_across_varied_paths(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09"]
        closes = {
            "RISING": [100.0, 105.0, 110.0, 115.0, 120.0, 125.0],   # never falls -> 0
            "FALLING": [100.0, 90.0, 80.0, 70.0, 60.0, 50.0],       # steady fall -> negative
            "VOLATILE": [100.0, 130.0, 70.0, 140.0, 60.0, 110.0],   # choppy -> negative
            "FLAT": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],     # flat -> 0
        }
        holdings = [[t, 25.0] for t in closes]

        with _patched(holdings, _closes(closes, dates)):
            result = _by_id()["max_drawdown"].run(etf_id="TESTFUND2", window="1y")

        for ticker, value in result["per_ticker"].items():
            with self.subTest(ticker=ticker):
                self.assertIsNotNone(value)
                self.assertLessEqual(value, 0.0)

        self.assertEqual(result["per_ticker"]["RISING"], 0.0)
        self.assertEqual(result["per_ticker"]["FLAT"], 0.0)
        self.assertLess(result["per_ticker"]["FALLING"], 0.0)
        self.assertLess(result["per_ticker"]["VOLATILE"], 0.0)


# ── Momentum ignores the final month ────────────────────────────────────────

class MomentumIgnoresFinalMonthTests(unittest.TestCase):
    def test_momentum_is_unaffected_by_a_move_confined_to_the_final_month(self):
        """A holding rises steadily, then spikes hard in the final two
        weeks. Momentum (cut off one month before the window's end) must
        not move with that spike; Return must."""
        dates = [
            "2020-01-01", "2020-06-01", "2020-12-01",  # steady rise
            "2020-12-20", "2021-01-01",                # the spike, inside the final month
        ]
        values = [100.0, 110.0, 150.0, 151.0, 400.0]
        holdings = [["AAA", 100.0]]

        with _patched(holdings, _closes({"AAA": values}, dates)):
            result = _by_id()["return_momentum"].run(etf_id="TESTFUND3", window="1y")

        ret = result["per_ticker"]["total_return"]["AAA"]
        mom = result["per_ticker"]["momentum"]["AAA"]

        self.assertAlmostEqual(ret, 300.0, places=2)   # 400/100 - 1
        self.assertAlmostEqual(mom, 50.0, places=2)    # 150/100 - 1, at 2020-12-01
        self.assertNotAlmostEqual(mom, ret, places=0)


# ── Short-history holdings are null with a reason, across all three ────────

class ShortHistoryNullWithReasonTests(unittest.TestCase):
    def test_a_two_day_old_listing_is_null_with_a_reason_everywhere(self):
        holdings = [["NEW", 100.0]]
        closes = _closes({"NEW": [100.0]}, ["2021-01-01"])  # a single priced date

        for plugin_id in PLUGIN_IDS:
            with self.subTest(plugin=plugin_id):
                with _patched(holdings, closes):
                    result = _by_id()[plugin_id].run(etf_id="TESTFUND4", window="1y")

                if plugin_id == "return_momentum":
                    self.assertIsNone(result["per_ticker"]["total_return"]["NEW"])
                    self.assertIsNone(result["per_ticker"]["momentum"]["NEW"])
                    self.assertIn("NEW", result["per_ticker_reason"]["total_return"])
                    self.assertIn("NEW", result["per_ticker_reason"]["momentum"])
                else:
                    self.assertIsNone(result["per_ticker"]["NEW"])
                    self.assertIn("NEW", result["per_ticker_reason"])


# ── Window awareness ─────────────────────────────────────────────────────────

class WindowAwarenessTests(unittest.TestCase):
    def test_every_new_plugin_shares_the_measurement_window_vocabulary(self):
        by_id = _by_id()
        for plugin_id in PLUGIN_IDS:
            with self.subTest(id=plugin_id):
                m = by_id[plugin_id]
                self.assertEqual(m.window_options, MEASUREMENT_WINDOW_OPTIONS)
                self.assertEqual(m.window_default, MEASUREMENT_WINDOW_DEFAULT)


# ── Manifest, docs, and worked examples ─────────────────────────────────────

class ManifestAndDocEndpointTests(unittest.TestCase):
    def test_every_plugin_is_registered_in_the_manifest(self):
        resp = client.get("/api/measurements")
        self.assertEqual(resp.status_code, 200)
        measurement_ids = {e["measurement_id"] for e in resp.json()}
        for plugin_id in PLUGIN_IDS:
            self.assertIn(plugin_id, measurement_ids)

        entries = resp.json()
        return_momentum_entries = [e for e in entries if e["measurement_id"] == "return_momentum"]
        self.assertEqual(
            sorted(e["id"] for e in return_momentum_entries),
            ["return_momentum.momentum", "return_momentum.total_return"],
        )

    def test_every_plugin_has_a_written_doc(self):
        for plugin_id in PLUGIN_IDS:
            with self.subTest(id=plugin_id):
                resp = client.get(f"/api/measurement-docs/{plugin_id}")
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json()["has_doc"])

    def test_single_column_worked_examples_run_end_to_end(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        closes = {
            "AAA": [100.0, 102.0, 104.04, 101.9592, 99.920016],
            "BBB": [100.0, 102.0, 99.96, 101.9592, 99.920016],
        }
        holdings = [["AAA", 50.0], ["BBB", 50.0]]

        for plugin_id in ("volatility", "max_drawdown"):
            with self.subTest(plugin=plugin_id):
                with _patched(holdings, _closes(closes, dates)):
                    resp = client.get(f"/api/measurement-docs/{plugin_id}/example")

                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertIn("AAA", body["per_ticker"])
                self.assertIn("AAA", body["per_ticker_mdx"])
                self.assertEqual(body["window"], MEASUREMENT_WINDOW_DEFAULT)

    def test_multi_column_worked_example_nests_by_column_and_lists_them(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        closes = {
            "AAA": [100.0, 102.0, 104.04, 101.9592, 99.920016],
            "BBB": [100.0, 102.0, 99.96, 101.9592, 99.920016],
        }
        holdings = [["AAA", 50.0], ["BBB", 50.0]]

        with _patched(holdings, _closes(closes, dates)):
            resp = client.get("/api/measurement-docs/return_momentum/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(
            sorted(c["key"] for c in body["columns"]), ["momentum", "total_return"]
        )
        for key in ("total_return", "momentum"):
            self.assertIn(key, body["per_ticker"])
            self.assertIn("AAA", body["per_ticker"][key])
        self.assertIsNotNone(body["per_ticker"]["total_return"]["AAA"])


if __name__ == "__main__":
    unittest.main()
