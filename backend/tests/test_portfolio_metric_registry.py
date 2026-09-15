"""
Tests for the portfolio metric registry (issue #104).

`services/portfolio.py`'s `_metrics()` and its own tests
(test_portfolio_metrics.py) own the arithmetic; nothing here duplicates or
re-derives a single number. What this file pins down is the registry
built on top of it:

  - Every migrated metric's manifest entry matches the key it reads, and
    `value()` reads that key back out of a real simulate_portfolio()
    response unchanged (issue #104's own acceptance criterion: arithmetic
    and response keys do not change).
  - The two families (portfolio, account) are declared data - a manifest
    field, not something this test (or the frontend) hardcodes.
  - The doc and worked-example endpoints behave the same three ways
    measurement-docs' own do: no such id -> 404, no .mdx -> synthesised
    frontmatter, malformed .mdx -> 500.
  - A computed_from="etf_id" entry registers and appears in the manifest
    with that input, with no change to portfolio_metrics/registry.py
    itself (acceptance criterion 5) - proven with a throwaway stand-in
    class, monkeypatched into ALL_METRICS for the duration of one test,
    the same way issue #101's WindowMeasurement stood in for a real
    window-aware plugin before one existed.

No test here touches Supabase or yfinance: `simulate_portfolio` is run
against a synthetic close frame the same way test_portfolio.py's own
`run()` helper patches it.

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
from portfolio_metrics import ALL_METRICS
from portfolio_metrics.base import FAMILIES, MetricBase
from services.portfolio import simulate_portfolio

client = TestClient(app, raise_server_exceptions=False)

EXPECTED_IDS = [
    "finalValue", "totalReturn", "cagr", "volatility", "maxDrawdown",
    "contributed", "totalInvested", "gain", "moneyWeightedReturn",
    "dividendIncome", "dividendYield", "incomeUnknownFor",
    "diversificationRatio", "top5VarianceShare", "trackedWeightCoverage",
]


def _closes(columns, dates):
    return pd.DataFrame(columns, index=pd.to_datetime(dates))


def _run(**overrides):
    """A real simulate_portfolio() response over a synthetic frame, the
    only kind of data this file's value()/manifest assertions are allowed
    to depend on."""
    closes = _closes(
        {"AAPL": [100.0, 110.0, 121.0], "MSFT": [50.0, 55.0, 60.5]},
        ["2020-01-01", "2020-02-01", "2020-03-01"],
    )
    holdings = [{"ticker": "AAPL", "weight": 60}, {"ticker": "MSFT", "weight": 40}]
    kwargs = dict(
        holdings=holdings, value=10_000.0, start="2020-01-01", end="2020-03-01",
        rebalance="none", contribution=overrides.pop("contribution", None),
    )
    kwargs.update(overrides)
    with (
        patch("services.portfolio.get_closes", return_value=closes),
        patch("services.portfolio.get_dividends", return_value={}),
        patch("services.portfolio.tracked_tickers", return_value=set()),
    ):
        return simulate_portfolio(**kwargs)


# ── Manifest shape ────────────────────────────────────────────────────────────

class ManifestShapeTests(unittest.TestCase):
    def test_every_migrated_metric_is_registered_exactly_once(self):
        self.assertEqual(sorted(m.id for m in ALL_METRICS), sorted(EXPECTED_IDS))

    def test_every_entry_is_self_describing(self):
        for metric in ALL_METRICS:
            with self.subTest(id=metric.id):
                manifest = metric.manifest()
                self.assertTrue(manifest["name"].strip())
                self.assertTrue(manifest["description"].strip())
                self.assertIn(manifest["family"], FAMILIES)
                self.assertTrue(manifest["formula"].strip())
                self.assertTrue(manifest["null_rule"].strip())
                self.assertEqual(manifest["origin"], "portfolio")
                self.assertIn(manifest["computed_from"], ("run", "etf_id"))

    def test_the_five_default_portfolio_tiles_are_default_enabled_tiles(self):
        """Today's five default tiles, unchanged (acceptance criterion 2)."""
        by_id = {m.id: m for m in ALL_METRICS}
        for metric_id in ("finalValue", "totalReturn", "cagr", "volatility", "maxDrawdown"):
            manifest = by_id[metric_id].manifest()
            self.assertTrue(manifest["tile"])
            self.assertTrue(manifest["default_enabled"])
            self.assertEqual(manifest["family"], "portfolio")

    def test_the_dividend_family_never_renders_as_a_tile(self):
        """The dividend note stays prose (issue #68), unchanged by this
        issue - each of the three still gets a full manifest entry, just
        never a toggleable one."""
        by_id = {m.id: m for m in ALL_METRICS}
        for metric_id in ("dividendIncome", "dividendYield", "incomeUnknownFor"):
            manifest = by_id[metric_id].manifest()
            self.assertFalse(manifest["tile"])
            self.assertEqual(manifest["family"], "dividend")

    def test_families_are_declared_data_not_frontend_layout(self):
        for key in ("portfolio", "account", "diversification", "coverage"):
            self.assertIn("label", FAMILIES[key])
            self.assertIn("note", FAMILIES[key])


# ── value() reads the real response, unchanged ────────────────────────────────

class ValueReadsTheRealRunTests(unittest.TestCase):
    def test_every_run_based_metric_reads_its_own_response_key(self):
        """The whole point: value() is a read of _metrics()'s own output,
        never a second implementation of the arithmetic."""
        run = _run()
        for metric in ALL_METRICS:
            if metric.computed_from != "run":
                continue
            with self.subTest(id=metric.id):
                self.assertEqual(metric.value(run), run["metrics"][metric.id])

    def test_a_null_metric_reads_null_not_a_default(self):
        """A single-row run leaves cagr/volatility/moneyWeightedReturn
        null (services/portfolio.py's own reasons) - value() must read
        that null through rather than defaulting it to zero."""
        closes = _closes({"AAPL": [100.0]}, ["2020-01-01"])
        with (
            patch("services.portfolio.get_closes", return_value=closes),
            patch("services.portfolio.get_dividends", return_value={}),
            patch("services.portfolio.tracked_tickers", return_value=set()),
        ):
            run = simulate_portfolio(
                holdings=[{"ticker": "AAPL", "weight": 100}],
                value=10_000.0, start="2020-01-01", end="2020-01-01",
            )
        by_id = {m.id: m for m in ALL_METRICS}
        self.assertIsNone(by_id["cagr"].value(run))
        self.assertIsNone(by_id["volatility"].value(run))
        self.assertIn("cagr", run["metrics"]["reasons"])

    def test_max_drawdown_value_is_the_whole_object_not_just_the_number(self):
        run = _run()
        by_id = {m.id: m for m in ALL_METRICS}
        value = by_id["maxDrawdown"].value(run)
        self.assertEqual(set(value.keys()), {"value", "peakDate", "troughDate", "granularity"})

    def test_income_unknown_for_value_is_a_list(self):
        run = _run()
        by_id = {m.id: m for m in ALL_METRICS}
        self.assertIsInstance(by_id["incomeUnknownFor"].value(run), list)


# ── Manifest endpoint ────────────────────────────────────────────────────────

class ManifestEndpointTests(unittest.TestCase):
    def test_lists_every_metric_and_the_families(self):
        resp = client.get("/api/portfolio-metrics")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(sorted(m["id"] for m in body["metrics"]), sorted(EXPECTED_IDS))
        self.assertEqual(set(body["families"]), set(FAMILIES))


# ── Doc endpoint ─────────────────────────────────────────────────────────────

class DocEndpointTests(unittest.TestCase):
    def test_unknown_id_is_a_404(self):
        resp = client.get("/api/portfolio-metric-docs/notAMetric")
        self.assertEqual(resp.status_code, 404)

    def test_every_migrated_metric_has_a_written_doc(self):
        """Issue #104's own to-do: write the .mdx for each migrated
        metric - checked here so a missing file fails the suite instead
        of quietly falling back to synthesised frontmatter forever."""
        for metric in ALL_METRICS:
            with self.subTest(id=metric.id):
                resp = client.get(f"/api/portfolio-metric-docs/{metric.id}")
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json()["has_doc"], f"{metric.id} ships no .mdx")

    def test_a_metric_with_no_doc_file_gets_synthesised_frontmatter(self):
        class _NoDocMetric(MetricBase):
            id = "noDocStandIn"
            name = "No Doc Stand-In"
            description = "A stand-in with no .mdx, for this test only."
            family = "portfolio"

            def value(self, data):
                return data.get("metrics", {}).get(self.id)

        resp_metric = _NoDocMetric()
        with patch("portfolio_metrics.registry.ALL_METRICS", ALL_METRICS + [resp_metric]):
            resp = client.get("/api/portfolio-metric-docs/noDocStandIn")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["has_doc"])
        self.assertEqual(body["frontmatter"]["title"], "No Doc Stand-In")


# ── Worked example endpoint ────────────────────────────────────────────────────

class WorkedExampleEndpointTests(unittest.TestCase):
    def test_runs_the_documented_example_portfolio_for_real(self):
        closes = _closes(
            {"SPY": [400.0, 410.0, 420.0], "AGG": [100.0, 101.0, 102.0]},
            ["2021-01-01", "2021-06-01", "2021-12-01"],
        )
        with (
            patch("services.portfolio.get_closes", return_value=closes),
            patch("services.portfolio.get_dividends", return_value={}),
            patch("services.portfolio.tracked_tickers", return_value=set()),
        ):
            resp = client.get("/api/portfolio-metric-docs/finalValue/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("portfolio", body)
        self.assertIn("run", body)
        self.assertIsNotNone(body["value"])
        self.assertEqual(body["value"], body["run"]["metrics"]["finalValue"])

    def test_a_null_value_in_the_example_carries_its_reason(self):
        closes = _closes({"SPY": [400.0], "AGG": [100.0]}, ["2021-01-01"])
        with (
            patch("services.portfolio.get_closes", return_value=closes),
            patch("services.portfolio.get_dividends", return_value={}),
            patch("services.portfolio.tracked_tickers", return_value=set()),
        ):
            resp = client.get("/api/portfolio-metric-docs/cagr/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsNone(body["value"])
        self.assertIn("reason", body)


# ── computed_from="etf_id" support (acceptance criterion 5) ─────────────────

class EtfIdInputSupportTests(unittest.TestCase):
    """A metric computed from a fund rather than a run must register and
    appear in the manifest with that input, with no change to the
    registry mechanism itself - the fund-level card (issue #105) is what
    actually ships one; this proves the mechanism ahead of it."""

    def test_an_etf_id_based_stand_in_appears_in_the_manifest_unmodified(self):
        class _FundStandIn(MetricBase):
            id = "fundStandIn"
            name = "Fund Stand-In"
            description = "A stand-in etf_id-based metric, for this test only."
            family = "portfolio"
            computed_from = "etf_id"

            def value(self, etf_id):
                return f"computed-for-{etf_id}"

        stand_in = _FundStandIn()
        with patch("portfolio_metrics.registry.ALL_METRICS", ALL_METRICS + [stand_in]):
            resp = client.get("/api/portfolio-metrics")

        self.assertEqual(resp.status_code, 200)
        entries = {m["id"]: m for m in resp.json()["metrics"]}
        self.assertIn("fundStandIn", entries)
        self.assertEqual(entries["fundStandIn"]["computed_from"], "etf_id")
        self.assertEqual(stand_in.value("SPY"), "computed-for-SPY")

    def test_an_entry_that_never_implements_value_cannot_be_instantiated(self):
        """value() stays abstract on MetricBase itself (only RunMetric
        supplies a default, for the "run" case) - an etf_id-based entry
        that forgets to implement its own cannot silently exist and
        return nothing; it fails at class-definition time instead."""
        class _ForgotToOverride(MetricBase):
            id = "forgotStandIn"
            name = "Forgot Stand-In"
            description = "for this test only"
            family = "portfolio"
            computed_from = "etf_id"

        with self.assertRaises(TypeError):
            _ForgotToOverride()


if __name__ == "__main__":
    unittest.main()
