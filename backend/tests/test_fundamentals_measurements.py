"""
Tests for the valuation/ownership/growth "fundamentals" measurements (issue
#194): P/E Ratio, Ownership, Profit Margin, Earnings Quarterly Growth,
Total Debt and Revenue per Share.

Mirrors test_metadata_income_measurements.py's own structure and reasoning:

  - A holding with nothing on record for a field is null with a reason,
    never 0.00 - except Total Debt, where a holding Yahoo genuinely
    reports as debt-free is a real 0.00, and only an absent figure (None)
    is null (invariant 7's "resist the tidier-looking zero", the other
    way round from every other field here).
  - Values render with the documented formatting (P/E as "24.3x", debt
    with the same $/B/T thresholds Market Cap uses, the rest as percent).
  - The shared registry contract: every plugin is in the manifest, has a
    written doc, and its worked example runs end to end - including both
    multi-column plugins' own nesting.

No test here touches Supabase or yfinance: measurements.inputs.holdings.
get_etf_holdings and each plugin's own get_fundamentals import are patched
with synthetic data throughout - get_fundamentals individually per plugin
module, the same reasoning test_metadata_income_measurements.py's own
module docstring gives for stock_info (a `from x import y` binding is not
reached by patching `x.y`, only by patching the importing module's own
copy).

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from main import app
from measurements import ALL_MEASUREMENTS
from rate_limit import FixedWindowLimiter

client = TestClient(app, raise_server_exceptions=False)

PLUGIN_IDS = [
    "pe_ratio",
    "ownership",
    "profit_margin",
    "earnings_quarterly_growth",
    "total_debt",
    "revenue_per_share",
]

_MODULES = {
    "pe_ratio": "measurements.official_measurements.pe_ratio",
    "ownership": "measurements.official_measurements.ownership",
    "profit_margin": "measurements.official_measurements.profit_margin",
    "earnings_quarterly_growth": "measurements.official_measurements.earnings_quarterly_growth",
    "total_debt": "measurements.official_measurements.total_debt",
    "revenue_per_share": "measurements.official_measurements.revenue_per_share",
}


def _by_id():
    return {m.id: m for m in ALL_MEASUREMENTS}


@contextmanager
def _patched(holdings, fundamentals=None):
    """Patch every seam a plugin under test might reach `get_holdings`/
    `get_fundamentals` through - see this file's own module docstring for
    why `get_fundamentals` is patched individually, at every plugin module
    that imports it."""
    with (
        patch("measurements.inputs.holdings.get_etf_holdings", return_value=(holdings, False)),
        patch(f"{_MODULES['pe_ratio']}.get_fundamentals", return_value=fundamentals or {}),
        patch(f"{_MODULES['ownership']}.get_fundamentals", return_value=fundamentals or {}),
        patch(f"{_MODULES['profit_margin']}.get_fundamentals", return_value=fundamentals or {}),
        patch(f"{_MODULES['earnings_quarterly_growth']}.get_fundamentals", return_value=fundamentals or {}),
        patch(f"{_MODULES['total_debt']}.get_fundamentals", return_value=fundamentals or {}),
        patch(f"{_MODULES['revenue_per_share']}.get_fundamentals", return_value=fundamentals or {}),
    ):
        yield


def _fundamentals(**by_ticker) -> dict:
    """{"AAA": {"trailingPE": 24.3, ...}, ...} straight through - every
    field a caller doesn't name for a ticker is simply absent, the same
    shape get_stock_fundamentals' own live fallback returns."""
    return by_ticker


# ── P/E Ratio ────────────────────────────────────────────────────────────────

class PeRatioTests(unittest.TestCase):
    def test_trailing_and_forward_render_as_a_multiple(self):
        holdings = [["AAA", 100.0]]
        data = _fundamentals(AAA={"trailingPE": 24.315, "forwardPE": 21.05})

        with _patched(holdings, data):
            result = _by_id()["pe_ratio"].run(etf_id="TESTFUND")

        self.assertAlmostEqual(result["per_ticker"]["trailing_pe"]["AAA"], 24.32, places=2)
        self.assertAlmostEqual(result["per_ticker"]["forward_pe"]["AAA"], 21.05, places=2)
        self.assertIn("24.3x", result["per_ticker_mdx"]["trailing_pe"]["AAA"])
        self.assertIn("21.1x", result["per_ticker_mdx"]["forward_pe"]["AAA"])

    def test_a_holding_with_neither_pe_is_null_with_a_reason_in_each_column(self):
        holdings = [["ETFHOLDING", 100.0]]
        data = _fundamentals(ETFHOLDING={})

        with _patched(holdings, data):
            result = _by_id()["pe_ratio"].run(etf_id="TESTFUND")

        self.assertIsNone(result["per_ticker"]["trailing_pe"]["ETFHOLDING"])
        self.assertIsNone(result["per_ticker"]["forward_pe"]["ETFHOLDING"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"]["trailing_pe"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"]["forward_pe"])
        self.assertEqual(result["per_ticker_mdx"]["trailing_pe"]["ETFHOLDING"], "—")
        self.assertEqual(result["per_ticker_mdx"]["forward_pe"]["ETFHOLDING"], "—")


# ── Ownership ────────────────────────────────────────────────────────────────

class OwnershipTests(unittest.TestCase):
    def test_both_shares_render_as_a_percent(self):
        holdings = [["AAA", 100.0]]
        data = _fundamentals(AAA={"heldPercentInsiders": 0.041, "heldPercentInstitutions": 0.672})

        with _patched(holdings, data):
            result = _by_id()["ownership"].run(etf_id="TESTFUND")

        self.assertAlmostEqual(result["per_ticker"]["held_percent_insiders"]["AAA"], 4.1, places=2)
        self.assertAlmostEqual(result["per_ticker"]["held_percent_institutions"]["AAA"], 67.2, places=2)
        self.assertIn("4.1%", result["per_ticker_mdx"]["held_percent_insiders"]["AAA"])
        self.assertIn("67.2%", result["per_ticker_mdx"]["held_percent_institutions"]["AAA"])

    def test_a_holding_with_neither_share_is_null_with_a_reason(self):
        holdings = [["ETFHOLDING", 100.0]]
        data = _fundamentals(ETFHOLDING={})

        with _patched(holdings, data):
            result = _by_id()["ownership"].run(etf_id="TESTFUND")

        self.assertIsNone(result["per_ticker"]["held_percent_insiders"]["ETFHOLDING"])
        self.assertIsNone(result["per_ticker"]["held_percent_institutions"]["ETFHOLDING"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"]["held_percent_insiders"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"]["held_percent_institutions"])


# ── Profit Margin ────────────────────────────────────────────────────────────

class ProfitMarginTests(unittest.TestCase):
    def test_a_positive_margin_renders_signed_and_uncoloured(self):
        holdings = [["AAA", 100.0]]
        data = _fundamentals(AAA={"profitMargins": 0.1823})

        with _patched(holdings, data):
            result = _by_id()["profit_margin"].run(etf_id="TESTFUND")

        self.assertAlmostEqual(result["per_ticker"]["AAA"], 18.23, places=2)
        self.assertIn("+18.2%", result["per_ticker_mdx"]["AAA"])

    def test_a_negative_margin_renders_signed_and_coloured(self):
        holdings = [["AAA", 100.0]]
        data = _fundamentals(AAA={"profitMargins": -0.05})

        with _patched(holdings, data):
            result = _by_id()["profit_margin"].run(etf_id="TESTFUND")

        self.assertAlmostEqual(result["per_ticker"]["AAA"], -5.0, places=2)
        self.assertIn("−5.0%", result["per_ticker_mdx"]["AAA"])
        self.assertIn("var(--negative)", result["per_ticker_mdx"]["AAA"])

    def test_no_margin_on_record_is_null_with_a_reason(self):
        holdings = [["ETFHOLDING", 100.0]]
        data = _fundamentals(ETFHOLDING={})

        with _patched(holdings, data):
            result = _by_id()["profit_margin"].run(etf_id="TESTFUND")

        self.assertIsNone(result["per_ticker"]["ETFHOLDING"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"])
        self.assertEqual(result["per_ticker_mdx"]["ETFHOLDING"], "—")


# ── Earnings Quarterly Growth ────────────────────────────────────────────────

class EarningsQuarterlyGrowthTests(unittest.TestCase):
    def test_growth_renders_signed(self):
        holdings = [["AAA", 100.0]]
        data = _fundamentals(AAA={"earningsQuarterlyGrowth": 0.095})

        with _patched(holdings, data):
            result = _by_id()["earnings_quarterly_growth"].run(etf_id="TESTFUND")

        self.assertAlmostEqual(result["per_ticker"]["AAA"], 9.5, places=2)
        self.assertIn("+9.5%", result["per_ticker_mdx"]["AAA"])

    def test_no_growth_on_record_is_null_with_a_reason(self):
        holdings = [["ETFHOLDING", 100.0]]
        data = _fundamentals(ETFHOLDING={})

        with _patched(holdings, data):
            result = _by_id()["earnings_quarterly_growth"].run(etf_id="TESTFUND")

        self.assertIsNone(result["per_ticker"]["ETFHOLDING"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"])


# ── Total Debt ───────────────────────────────────────────────────────────────

class TotalDebtTests(unittest.TestCase):
    def test_matches_market_caps_own_dollar_thresholds(self):
        holdings = [["MEGA", 40.0], ["MID", 30.0], ["SMALL", 30.0]]
        data = _fundamentals(
            MEGA={"totalDebt": 1_200_000_000_000.0},   # $1.20T
            MID={"totalDebt": 61_800_000_000.0},        # $61.8B
            SMALL={"totalDebt": 500_000_000.0},         # $500M
        )

        with _patched(holdings, data):
            result = _by_id()["total_debt"].run(etf_id="TESTFUND")

        self.assertIn("$1.20T", result["per_ticker_mdx"]["MEGA"])
        self.assertIn("$61.8B", result["per_ticker_mdx"]["MID"])
        self.assertIn("$500M", result["per_ticker_mdx"]["SMALL"])

    def test_a_genuinely_debt_free_holding_is_zero_not_null(self):
        """Invariant 7, the other way round: a real 0 must not be flattened
        into a null just because 0 is falsy."""
        holdings = [["DEBTFREE", 100.0]]
        data = _fundamentals(DEBTFREE={"totalDebt": 0})

        with _patched(holdings, data):
            result = _by_id()["total_debt"].run(etf_id="TESTFUND")

        self.assertEqual(result["per_ticker"]["DEBTFREE"], 0.0)
        self.assertNotIn("DEBTFREE", result.get("per_ticker_reason", {}))
        self.assertIn("$0M", result["per_ticker_mdx"]["DEBTFREE"])

    def test_no_debt_on_record_is_null_with_a_reason(self):
        holdings = [["ETFHOLDING", 100.0]]
        data = _fundamentals(ETFHOLDING={})

        with _patched(holdings, data):
            result = _by_id()["total_debt"].run(etf_id="TESTFUND")

        self.assertIsNone(result["per_ticker"]["ETFHOLDING"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"])


# ── Revenue per Share ────────────────────────────────────────────────────────

class RevenuePerShareTests(unittest.TestCase):
    def test_renders_as_a_dollar_figure(self):
        holdings = [["AAA", 100.0]]
        data = _fundamentals(AAA={"revenuePerShare": 9.873})

        with _patched(holdings, data):
            result = _by_id()["revenue_per_share"].run(etf_id="TESTFUND")

        self.assertAlmostEqual(result["per_ticker"]["AAA"], 9.87, places=2)
        self.assertIn("$9.87", result["per_ticker_mdx"]["AAA"])

    def test_no_revenue_per_share_on_record_is_null_with_a_reason(self):
        holdings = [["ETFHOLDING", 100.0]]
        data = _fundamentals(ETFHOLDING={})

        with _patched(holdings, data):
            result = _by_id()["revenue_per_share"].run(etf_id="TESTFUND")

        self.assertIsNone(result["per_ticker"]["ETFHOLDING"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"])


# ── Manifest, docs, and worked examples ─────────────────────────────────────

class ManifestAndDocEndpointTests(unittest.TestCase):
    def setUp(self):
        # This class alone makes well over a dozen real /api/* calls - a
        # fresh, generous limiter per test rather than spending headroom
        # out of the shared rate_limit.general_limiter every other file in
        # this suite also calls against (backend/tests/CLAUDE.md's own
        # rule, the same one test_deep_fill.py and test_rate_limit.py
        # already follow).
        patcher = patch("rate_limit.general_limiter", FixedWindowLimiter(limit=1000, window_seconds=60))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_plugin_is_registered_in_the_manifest(self):
        resp = client.get("/api/measurements")
        self.assertEqual(resp.status_code, 200)
        measurement_ids = {e["measurement_id"] for e in resp.json()}
        for plugin_id in PLUGIN_IDS:
            self.assertIn(plugin_id, measurement_ids)

        entries = resp.json()
        pe_ratio_entries = [e for e in entries if e["measurement_id"] == "pe_ratio"]
        self.assertEqual(
            sorted(e["id"] for e in pe_ratio_entries),
            ["pe_ratio.forward_pe", "pe_ratio.trailing_pe"],
        )
        ownership_entries = [e for e in entries if e["measurement_id"] == "ownership"]
        self.assertEqual(
            sorted(e["id"] for e in ownership_entries),
            ["ownership.held_percent_insiders", "ownership.held_percent_institutions"],
        )

    def test_every_new_column_is_off_by_default(self):
        """Opt-in, not a change to the table's default view (the design
        round's own decision) - six new toggles must not appear active the
        moment the holdings table loads."""
        resp = client.get("/api/measurements")
        entries = [e for e in resp.json() if e["measurement_id"] in PLUGIN_IDS]
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(column=entry["id"]):
                self.assertFalse(entry["default_enabled"])

    def test_every_plugin_has_a_written_doc(self):
        for plugin_id in PLUGIN_IDS:
            with self.subTest(id=plugin_id):
                resp = client.get(f"/api/measurement-docs/{plugin_id}")
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json()["has_doc"])

    def test_single_column_worked_examples_run_end_to_end(self):
        holdings = [["AAA", 50.0], ["BBB", 50.0]]
        data = _fundamentals(
            AAA={"profitMargins": 0.1, "earningsQuarterlyGrowth": 0.05, "totalDebt": 1_000_000_000.0, "revenuePerShare": 5.0},
            BBB={"profitMargins": 0.2, "earningsQuarterlyGrowth": 0.1, "totalDebt": 2_000_000_000.0, "revenuePerShare": 6.0},
        )

        for plugin_id in ("profit_margin", "earnings_quarterly_growth", "total_debt", "revenue_per_share"):
            with self.subTest(plugin=plugin_id):
                with _patched(holdings, data):
                    resp = client.get(f"/api/measurement-docs/{plugin_id}/example")

                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertIn("AAA", body["per_ticker"])
                self.assertIn("AAA", body["per_ticker_mdx"])

    def test_multi_column_worked_examples_nest_by_column_and_list_them(self):
        holdings = [["AAA", 50.0], ["BBB", 50.0]]
        data = _fundamentals(
            AAA={"trailingPE": 20.0, "forwardPE": 18.0, "heldPercentInsiders": 0.05, "heldPercentInstitutions": 0.6},
            BBB={"trailingPE": 30.0, "forwardPE": 25.0, "heldPercentInsiders": 0.1, "heldPercentInstitutions": 0.7},
        )

        for plugin_id, expected_keys in (
            ("pe_ratio", ["forward_pe", "trailing_pe"]),
            ("ownership", ["held_percent_insiders", "held_percent_institutions"]),
        ):
            with self.subTest(plugin=plugin_id):
                with _patched(holdings, data):
                    resp = client.get(f"/api/measurement-docs/{plugin_id}/example")

                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertEqual(sorted(c["key"] for c in body["columns"]), expected_keys)
                for key in expected_keys:
                    self.assertIn(key, body["per_ticker"])
                    self.assertIn("AAA", body["per_ticker"][key])


if __name__ == "__main__":
    unittest.main()
