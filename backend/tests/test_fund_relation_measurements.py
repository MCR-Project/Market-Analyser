"""
Tests for the "how a holding relates to its fund" measurements (issue
#107): risk contribution, beta/R²/idiosyncratic volatility, tail
correlation, and the upside/downside capture ratios.

services/stats.py's own arithmetic (weighted_index, tail_correlation, the
r_squared_result reuse) is covered by test_stats.py; this file pins down
the four acceptance criteria that only make sense at the measurement
level, where holdings, weights and a real window come together:

  - Risk contributions across a fund sum to 100% within rounding.
  - A fund priced against itself reports beta 1 and R² 1.
  - Idiosyncratic volatility never exceeds a holding's own total
    volatility.
  - Capture ratios are computed only over the fund's own up/down
    periods.

...plus the registry-level contract every measurement here shares: window
awareness, a doc page, and null-with-a-reason rather than zero where a
column cannot compute - including, for the two multi-column plugins
(fund_relation, capture_ratio), the worked-example endpoint actually
exercising issue #107's own fix to examples.py's multi-column support
(never exercised by a real official measurement before this issue).

No test here touches Supabase or yfinance: measurements.inputs.holdings.
get_holdings and measurements.inputs.price_frame.get_price_frame are
patched with synthetic data throughout.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS
from main import app
from measurements import ALL_MEASUREMENTS
from services import stats

client = TestClient(app, raise_server_exceptions=False)

PLUGIN_IDS = ["risk_contribution", "fund_relation", "tail_correlation", "capture_ratio"]


def _closes(values_by_ticker: dict[str, list[float]], dates: list[str]) -> dict:
    """The measurements.inputs.price_frame.get_price_frame shape:
    {ticker: {"closes": [[date, value], ...]}}."""
    return {
        t: {"closes": [[d, v] for d, v in zip(dates, values)]}
        for t, values in values_by_ticker.items()
    }


def _patched(holdings, closes_by_ticker):
    """Patch at the one place each getter's own call resolves regardless
    of which module imported it by name: `get_holdings` (imported
    separately by examples.py and every plugin file) always looks up
    `get_etf_holdings` inside measurements.inputs.holdings's own module
    globals, since that is where `get_holdings` itself is defined -
    patching the outer `get_holdings` name would only affect callers
    that access it as `holdings.get_holdings(...)`, not the `from
    measurements.inputs.holdings import get_holdings` every plugin uses.
    Same reasoning for price_frame.get_price_frame, which every caller
    here reaches only through get_aligned_closes/_sample - both defined
    in that same module."""
    return (
        patch("measurements.inputs.holdings.get_etf_holdings", return_value=(holdings, False)),
        patch("measurements.inputs.price_frame.get_price_frame", return_value=closes_by_ticker),
    )


def _by_id():
    return {m.id: m for m in ALL_MEASUREMENTS}


# ── Risk contribution sums to 100% ──────────────────────────────────────────

class RiskContributionSumsTo100Tests(unittest.TestCase):
    def test_contributions_across_the_fund_sum_to_100_within_rounding(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        closes = {
            "AAA": [100.0, 102.0, 104.04, 101.9592, 99.920016],
            "BBB": [100.0, 102.0, 99.96, 101.9592, 99.920016],
            "CCC": [100.0, 98.0, 101.0, 103.0, 100.5],
        }
        holdings = [["AAA", 40.0], ["BBB", 35.0], ["CCC", 25.0]]

        p1, p2 = _patched(holdings, _closes(closes, dates))
        with p1, p2:
            result = _by_id()["risk_contribution"].run(etf_id="TESTFUND1", window="1y")

        values = [v for v in result["per_ticker"].values() if v is not None]
        self.assertEqual(len(values), 3)
        self.assertAlmostEqual(sum(values), 100.0, places=1)

    def test_a_single_holding_fund_is_null_with_a_reason_not_zero(self):
        holdings = [["AAA", 100.0]]
        p1, p2 = _patched(holdings, _closes({"AAA": [100.0, 101.0, 99.0]}, ["2020-01-02", "2020-01-03", "2020-01-06"]))
        with p1, p2:
            result = _by_id()["risk_contribution"].run(etf_id="TESTFUND1B", window="1y")

        self.assertIsNone(result["per_ticker"]["AAA"])
        self.assertIn("AAA", result["per_ticker_reason"])

    def test_a_single_holding_fund_is_null_with_a_reason_not_zero(self):
        """Same rule as risk_contribution's own null case: fund_index
        itself needs at least two complete holdings to build a benchmark
        at all, so a single-holding fund reports every one of beta/R²/
        idio_vol null with a reason - never a fabricated 0."""
        holdings = [["AAA", 100.0]]
        p1, p2 = _patched(holdings, _closes({"AAA": [100.0, 101.0, 99.0]}, ["2020-01-02", "2020-01-03", "2020-01-06"]))
        with p1, p2:
            result = _by_id()["fund_relation"].run(etf_id="TESTFUND2B", window="1y")

        for key in ("beta", "r_squared", "idio_vol"):
            self.assertIsNone(result["per_ticker"][key]["AAA"])
            self.assertIn("AAA", result["per_ticker_reason"][key])


# ── A fund priced against itself: beta 1, R² 1 ──────────────────────────────

class FundRelationSelfIdentityTests(unittest.TestCase):
    def test_two_identical_holdings_report_beta_1_r_squared_1_idio_vol_0(self):
        """AAA and BBB share the exact same price path at equal weight:
        the fund's own weighted index is then that same path (rebased),
        so measuring either holding against its fund is "a fund priced
        against itself" - the acceptance criterion's own wording - and
        both must report beta 1, R² 1, idiosyncratic volatility 0.

        (fund_index requires at least two holdings with a complete
        history to build one at all - the same rule issue #105's
        fund_metrics.py states - so two identical series stand in for a
        literal single-holding fund without relaxing that rule.)"""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        values = [100.0, 103.0, 101.0, 105.0, 102.0]
        holdings = [["AAA", 50.0], ["BBB", 50.0]]

        p1, p2 = _patched(holdings, _closes({"AAA": values, "BBB": list(values)}, dates))
        with p1, p2:
            result = _by_id()["fund_relation"].run(etf_id="TESTFUND2", window="1y")

        for ticker in ("AAA", "BBB"):
            with self.subTest(ticker=ticker):
                self.assertAlmostEqual(result["per_ticker"]["beta"][ticker], 1.0, places=3)
                self.assertAlmostEqual(result["per_ticker"]["r_squared"][ticker], 1.0, places=3)
                self.assertAlmostEqual(result["per_ticker"]["idio_vol"][ticker], 0.0, places=2)


# ── Idiosyncratic volatility never exceeds total volatility ────────────────

class IdiosyncraticVolatilityBoundTests(unittest.TestCase):
    def test_idio_vol_never_exceeds_the_holdings_own_total_volatility(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09"]
        closes = {
            "AAA": [100.0, 105.0, 98.0, 110.0, 90.0, 115.0],   # noisy, low R²
            "BBB": [100.0, 102.0, 101.0, 103.0, 102.0, 104.0],  # calm
            "CCC": [100.0, 98.0, 103.0, 95.0, 108.0, 92.0],     # noisy, opposite
        }
        holdings = [["AAA", 34.0], ["BBB", 33.0], ["CCC", 33.0]]

        p1, p2 = _patched(holdings, _closes(closes, dates))
        with p1, p2:
            result = _by_id()["fund_relation"].run(etf_id="TESTFUND3", window="1y")

        for ticker, values in closes.items():
            idio = result["per_ticker"]["idio_vol"][ticker]
            if idio is None:
                continue
            total = stats.volatility(values, dates)["value"]
            self.assertIsNotNone(total)
            self.assertLessEqual(idio, total + 1e-6)


# ── Capture ratios only reflect the fund's own up/down periods ─────────────

class CaptureRatioTests(unittest.TestCase):
    def test_capture_ratios_match_the_up_and_down_period_formula_directly(self):
        """Cross-checked against services.stats.up_capture/down_capture
        called directly on the same fund index the measurement itself
        would build - proves the measurement's own orchestration (which
        holdings, which window) rather than re-deriving the arithmetic
        stats.py's own tests already cover."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
        fund_holding_values = [100.0, 110.0, 121.0, 108.9]   # +10%, +10%, -10%
        asset_values = [100.0, 115.0, 124.2, 117.99]          # +15%, +8%, -5%
        holdings = [["FUND", 50.0], ["AAA", 50.0]]
        closes = _closes({"FUND": fund_holding_values, "AAA": asset_values}, dates)

        # The fund index is the 50/50 weighted combination of both
        # holdings, not fund_holding_values alone - so cross-check against
        # stats.up_capture/down_capture using that same combined benchmark,
        # read back from the measurement's own fund_index input, all
        # inside the same patched context the measurement itself ran in.
        from measurements.inputs.fund_index import get_fund_index

        p1, p2 = _patched(holdings, closes)
        with p1, p2:
            result = _by_id()["capture_ratio"].run(etf_id="TESTFUND4", window="1y")
            weights = {"FUND": 50.0, "AAA": 50.0}
            fund = get_fund_index(["FUND", "AAA"], weights, period="1y")

        expected_up = stats.up_capture(asset_values, fund["fund_values"], dates)["value"]
        expected_down = stats.down_capture(asset_values, fund["fund_values"], dates)["value"]

        self.assertAlmostEqual(result["per_ticker"]["up_capture"]["AAA"], expected_up, places=3)
        self.assertAlmostEqual(result["per_ticker"]["down_capture"]["AAA"], expected_down, places=3)

    def test_null_with_a_reason_when_the_fund_has_no_down_period(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06"]
        # Fund only ever rises - no down period exists to capture a share of.
        holdings = [["FUND", 50.0], ["AAA", 50.0]]
        closes = _closes(
            {"FUND": [100.0, 105.0, 110.0], "AAA": [100.0, 108.0, 112.0]}, dates
        )

        p1, p2 = _patched(holdings, closes)
        with p1, p2:
            result = _by_id()["capture_ratio"].run(etf_id="TESTFUND5", window="1y")

        self.assertIsNone(result["per_ticker"]["down_capture"]["AAA"])
        self.assertIn("AAA", result["per_ticker_reason"]["down_capture"])


# ── Tail correlation ─────────────────────────────────────────────────────────

class TailCorrelationMeasurementTests(unittest.TestCase):
    def test_fewer_than_two_priced_holdings_is_null_with_a_reason(self):
        holdings = [["AAA", 100.0]]
        p1, p2 = _patched(holdings, _closes({"AAA": [100.0, 101.0]}, ["2020-01-02", "2020-01-03"]))
        with p1, p2:
            result = _by_id()["tail_correlation"].run(etf_id="TESTFUND6", window="1y")

        self.assertIsNone(result["per_ticker"]["AAA"])
        self.assertIn("AAA", result["per_ticker_reason"])


# ── Window awareness ─────────────────────────────────────────────────────────

class WindowAwarenessTests(unittest.TestCase):
    def test_every_new_plugin_shares_the_measurement_window_vocabulary(self):
        by_id = _by_id()
        for plugin_id in PLUGIN_IDS:
            with self.subTest(id=plugin_id):
                m = by_id[plugin_id]
                self.assertEqual(m.window_options, MEASUREMENT_WINDOW_OPTIONS)
                self.assertEqual(m.window_default, MEASUREMENT_WINDOW_DEFAULT)


# ── Manifest, docs, and worked examples (including the multi-column fix) ───

class ManifestAndDocEndpointTests(unittest.TestCase):
    def test_every_plugin_is_registered_and_window_aware_in_the_manifest(self):
        resp = client.get("/api/measurements")
        self.assertEqual(resp.status_code, 200)
        entries = resp.json()
        measurement_ids = {e["measurement_id"] for e in entries}
        for plugin_id in PLUGIN_IDS:
            self.assertIn(plugin_id, measurement_ids)

        fund_relation_entries = [e for e in entries if e["measurement_id"] == "fund_relation"]
        self.assertEqual(
            sorted(e["id"] for e in fund_relation_entries),
            ["fund_relation.beta", "fund_relation.idio_vol", "fund_relation.r_squared"],
        )
        capture_entries = [e for e in entries if e["measurement_id"] == "capture_ratio"]
        self.assertEqual(
            sorted(e["id"] for e in capture_entries),
            ["capture_ratio.down_capture", "capture_ratio.up_capture"],
        )

    def test_every_plugin_has_a_written_doc(self):
        for plugin_id in PLUGIN_IDS:
            with self.subTest(id=plugin_id):
                resp = client.get(f"/api/measurement-docs/{plugin_id}")
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json()["has_doc"])

    def test_single_column_worked_example_runs_end_to_end(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        closes = {
            "AAA": [100.0, 102.0, 104.04, 101.9592, 99.920016],
            "BBB": [100.0, 102.0, 99.96, 101.9592, 99.920016],
        }
        holdings = [["AAA", 50.0], ["BBB", 50.0]]

        p1, p2 = _patched(holdings, _closes(closes, dates))
        with p1, p2:
            resp = client.get("/api/measurement-docs/risk_contribution/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("AAA", body["per_ticker"])
        self.assertIn("AAA", body["per_ticker_mdx"])
        self.assertEqual(body["window"], MEASUREMENT_WINDOW_DEFAULT)

    def test_multi_column_worked_example_nests_by_column_and_lists_them(self):
        """The direct regression test for issue #107's fix to
        examples.py: before it, a multi-column plugin's worked example
        silently produced an empty/wrong per_ticker shape because the
        original build_example assumed a flat {ticker: value} dict."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        closes = {
            "AAA": [100.0, 102.0, 104.04, 101.9592, 99.920016],
            "BBB": [100.0, 102.0, 99.96, 101.9592, 99.920016],
        }
        holdings = [["AAA", 50.0], ["BBB", 50.0]]

        p1, p2 = _patched(holdings, _closes(closes, dates))
        with p1, p2:
            resp = client.get("/api/measurement-docs/fund_relation/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(
            sorted(c["key"] for c in body["columns"]), ["beta", "idio_vol", "r_squared"]
        )
        for key in ("beta", "r_squared", "idio_vol"):
            self.assertIn(key, body["per_ticker"])
            self.assertIn("AAA", body["per_ticker"][key])
            self.assertIn(key, body["per_ticker_mdx"])
        # Real values, not None, for a fund with two priced holdings.
        self.assertIsNotNone(body["per_ticker"]["beta"]["AAA"])

    def test_a_null_value_in_a_multi_column_example_carries_its_reason(self):
        holdings = [["AAA", 100.0]]
        p1, p2 = _patched(holdings, _closes({"AAA": [100.0, 101.0]}, ["2020-01-02", "2020-01-03"]))
        with p1, p2:
            resp = client.get("/api/measurement-docs/capture_ratio/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("per_ticker_reason", body)
        self.assertTrue(
            any("AAA" in (body["per_ticker_reason"].get(k) or {}) for k in ("up_capture", "down_capture"))
        )


if __name__ == "__main__":
    unittest.main()
