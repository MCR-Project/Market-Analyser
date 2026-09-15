"""
Tests for fund-level metrics (issue #105): the diversification ratio,
the variance share of the fund's five largest risk contributors, and how
much of the fund its tracked (>=1% weight) holdings actually cover.

services/stats.py's own arithmetic (diversification_ratio,
risk_contribution) is covered by test_stats.py; this file pins down:
  - services/fund_metrics.py's compute_fund_metrics(): which holdings and
    price data it reads, and how it turns that into the three figures -
    including the two "not enough to compute this" cases (fewer than two
    holdings with a complete price history; no measurable variance).
  - The registry's fund-scoped endpoint, GET /api/portfolio-metrics/{etf_id}.
  - The doc/worked-example endpoints for the three new metrics, the same
    three-outcome contract every doc endpoint in this app follows.

compute_fund_metrics is cached by etf_id (see its own module docstring),
so every test here that patches get_etf_holdings/get_closes also resets
services.fund_metrics.cache first - otherwise a test reusing the same
fake ticker (or the fixed DOCS_EXAMPLE_ETF a worked example always uses)
could silently read another test's cached result instead of its own
mocked data.

No test here touches Supabase or yfinance: get_etf_holdings and
get_closes are patched with synthetic data throughout.
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
from services import stats
from services.cache import TTLCache
from services.fund_metrics import compute_fund_metrics

client = TestClient(app, raise_server_exceptions=False)

FUND_METRIC_IDS = ["diversificationRatio", "top5VarianceShare", "trackedWeightCoverage"]


def _closes(columns, dates):
    return pd.DataFrame(columns, index=pd.to_datetime(dates))


def _holdings(pairs):
    """[[ticker, weight], ...] plus the `stale` flag get_etf_holdings
    itself returns as a tuple - never true here, since no test in this
    file cares about the live-fallback path."""
    return [[ticker, weight] for ticker, weight in pairs], False


class _FreshCacheTestCase(unittest.TestCase):
    """Resets services.fund_metrics.cache before every test method, so
    tests reusing a ticker (deliberately, or via the fixed
    DOCS_EXAMPLE_ETF a worked example always resolves to) never read a
    stale result cached by an earlier one."""

    def setUp(self):
        patcher = patch("services.fund_metrics.cache", TTLCache())
        patcher.start()
        self.addCleanup(patcher.stop)


# ── compute_fund_metrics ─────────────────────────────────────────────────────

class ComputeFundMetricsTests(_FreshCacheTestCase):
    def test_coverage_is_the_sum_of_tracked_weights(self):
        with (
            patch("services.fund_metrics.get_etf_holdings",
                  return_value=_holdings([("AAA", 40.0), ("BBB", 35.0)])),
            patch("services.fund_metrics.get_closes", return_value=None),
        ):
            result = compute_fund_metrics("COVFUND1")

        self.assertEqual(result["trackedWeightCoverage"], 75.0)

    def test_no_holdings_is_zero_coverage_not_null(self):
        with patch("services.fund_metrics.get_etf_holdings", return_value=([], False)):
            result = compute_fund_metrics("COVFUND2")

        self.assertEqual(result["trackedWeightCoverage"], 0)
        self.assertIsNone(result["diversificationRatio"])
        self.assertIsNone(result["top5VarianceShare"])
        self.assertIn("diversificationRatio", result["reasons"])
        self.assertIn("top5VarianceShare", result["reasons"])

    def test_two_uncorrelated_equal_variance_holdings_give_a_real_ratio(self):
        """Same construction test_stats.py's own risk_contribution/
        diversification_ratio tests use: A and B have equal variance and
        exactly zero sample covariance, so the ratio has a known closed
        form (sqrt(2)) and risk splits exactly in half."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        closes = _closes(
            {
                "AAA": [100.0, 102.0, 104.04, 101.9592, 99.920016],
                "BBB": [100.0, 102.0, 99.96, 101.9592, 99.920016],
            },
            dates,
        )
        with (
            patch("services.fund_metrics.get_etf_holdings",
                  return_value=_holdings([("AAA", 50.0), ("BBB", 50.0)])),
            patch("services.fund_metrics.get_closes", return_value=closes),
        ):
            result = compute_fund_metrics("DIVFUND1")

        self.assertAlmostEqual(result["diversificationRatio"], 2 ** 0.5, places=3)
        self.assertAlmostEqual(result["top5VarianceShare"], 100.0, places=2)
        self.assertEqual(result["trackedWeightCoverage"], 100.0)
        self.assertEqual(result["reasons"], {})

    def test_top5_variance_share_picks_the_five_largest_contributors(self):
        """Six holdings, so top5VarianceShare must be a strict slice, not
        the whole basket's 100%. Checked against services.stats.
        risk_contribution called directly over the same synthetic data -
        this is testing compute_fund_metrics' own orchestration (does it
        read the right holdings/prices and pick the right five), not
        re-deriving the arithmetic stats.py's own tests already cover."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        movers = {f"T{i}": [100.0, 102.0 + i, 104.0 - i, 101.0 + i, 100.0] for i in range(5)}
        values = {**movers, "FLAT": [100.0] * 5}
        closes = _closes(values, dates)
        holdings = [(t, 15.0) for t in movers] + [("FLAT", 10.0)]
        weights = dict(holdings)

        with (
            patch("services.fund_metrics.get_etf_holdings", return_value=_holdings(holdings)),
            patch("services.fund_metrics.get_closes", return_value=closes),
        ):
            result = compute_fund_metrics("DIVFUND2")

        expected = stats.risk_contribution(values, dates, weights)
        expected_top5 = round(
            sum(sorted((v for v in expected.values() if v is not None), reverse=True)[:5]), 2
        )
        self.assertEqual(result["top5VarianceShare"], expected_top5)

    def test_a_holding_with_a_gap_is_excluded_but_still_counts_toward_coverage(self):
        """A holding that hasn't priced for the fund's whole window
        cannot safely join the joint covariance matrix (see
        compute_fund_metrics' own docstring for why this differs from
        the pairwise correlation matrix) - it is left out of
        diversificationRatio/top5VarianceShare, but its weight still
        counts toward trackedWeightCoverage, which needs no shared
        window at all."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06"]
        closes = _closes(
            {
                "AAA": [100.0, 101.0, 102.0],
                "BBB": [100.0, 99.0, 101.0],
                "NEW": [float("nan"), float("nan"), 50.0],
            },
            dates,
        )
        holdings = [("AAA", 40.0), ("BBB", 40.0), ("NEW", 5.0)]
        with (
            patch("services.fund_metrics.get_etf_holdings", return_value=_holdings(holdings)),
            patch("services.fund_metrics.get_closes", return_value=closes),
        ):
            result = compute_fund_metrics("DIVFUND3")

        self.assertEqual(result["trackedWeightCoverage"], 85.0)
        self.assertIsNotNone(result["diversificationRatio"])

    def test_fewer_than_two_complete_holdings_is_null_with_a_reason(self):
        dates = ["2020-01-02", "2020-01-03"]
        closes = _closes({"AAA": [100.0, 101.0], "NEW": [float("nan"), 50.0]}, dates)
        holdings = [("AAA", 60.0), ("NEW", 10.0)]
        with (
            patch("services.fund_metrics.get_etf_holdings", return_value=_holdings(holdings)),
            patch("services.fund_metrics.get_closes", return_value=closes),
        ):
            result = compute_fund_metrics("DIVFUND4")

        self.assertIsNone(result["diversificationRatio"])
        self.assertIsNone(result["top5VarianceShare"])
        self.assertIn("diversificationRatio", result["reasons"])
        self.assertIn("top5VarianceShare", result["reasons"])
        self.assertEqual(result["trackedWeightCoverage"], 70.0)

    def test_a_flat_fund_has_no_variance_to_apportion(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06"]
        closes = _closes({"AAA": [100.0] * 3, "BBB": [100.0] * 3}, dates)
        with (
            patch("services.fund_metrics.get_etf_holdings",
                  return_value=_holdings([("AAA", 50.0), ("BBB", 50.0)])),
            patch("services.fund_metrics.get_closes", return_value=closes),
        ):
            result = compute_fund_metrics("DIVFUND5")

        self.assertIsNone(result["diversificationRatio"])
        self.assertIn("diversificationRatio", result["reasons"])

    def test_results_are_cached_case_insensitively_by_etf_id(self):
        with (
            patch("services.fund_metrics.get_etf_holdings",
                  return_value=_holdings([("AAA", 50.0), ("BBB", 50.0)])) as mock_holdings,
            patch("services.fund_metrics.get_closes", return_value=None),
        ):
            compute_fund_metrics("CACHEFUND")
            compute_fund_metrics("cachefund")

        self.assertEqual(mock_holdings.call_count, 1)


# ── Registry endpoint ────────────────────────────────────────────────────────

class FundMetricsEndpointTests(_FreshCacheTestCase):
    def test_every_fund_metric_is_registered_with_the_right_shape(self):
        by_id = {m.id: m for m in ALL_METRICS}
        for metric_id in FUND_METRIC_IDS:
            with self.subTest(id=metric_id):
                self.assertIn(metric_id, by_id)
                manifest = by_id[metric_id].manifest()
                self.assertEqual(manifest["computed_from"], "etf_id")
                self.assertIn(manifest["family"], ("diversification", "coverage"))

    def test_the_endpoint_returns_real_values_for_a_fund(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        closes = _closes(
            {
                "AAA": [100.0, 102.0, 104.04, 101.9592, 99.920016],
                "BBB": [100.0, 102.0, 99.96, 101.9592, 99.920016],
            },
            dates,
        )
        with (
            patch("services.fund_metrics.get_etf_holdings",
                  return_value=_holdings([("AAA", 50.0), ("BBB", 50.0)])),
            patch("services.fund_metrics.get_closes", return_value=closes),
        ):
            resp = client.get("/api/portfolio-metrics/ENDPOINTFUND1")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["etfId"], "ENDPOINTFUND1")
        for metric_id in FUND_METRIC_IDS:
            self.assertIn(metric_id, body["values"])
        self.assertAlmostEqual(body["values"]["diversificationRatio"], 2 ** 0.5, places=3)
        self.assertEqual(body["values"]["trackedWeightCoverage"], 100.0)
        self.assertEqual(body["reasons"], {})

    def test_a_null_value_carries_its_reason_and_coverage_never_does(self):
        with patch("services.fund_metrics.get_etf_holdings", return_value=([], False)):
            resp = client.get("/api/portfolio-metrics/ENDPOINTFUND2")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsNone(body["values"]["diversificationRatio"])
        self.assertIn("diversificationRatio", body["reasons"])
        self.assertNotIn("trackedWeightCoverage", body["reasons"])


# ── Doc + worked example endpoints ──────────────────────────────────────────

class FundMetricDocTests(_FreshCacheTestCase):
    def test_every_fund_metric_has_a_written_doc(self):
        for metric_id in FUND_METRIC_IDS:
            with self.subTest(id=metric_id):
                resp = client.get(f"/api/portfolio-metric-docs/{metric_id}")
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json()["has_doc"], f"{metric_id} ships no .mdx")

    def test_the_worked_example_runs_against_a_real_fund(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        closes = _closes(
            {
                "AAA": [100.0, 102.0, 104.04, 101.9592, 99.920016],
                "BBB": [100.0, 102.0, 99.96, 101.9592, 99.920016],
            },
            dates,
        )
        with (
            patch("services.fund_metrics.get_etf_holdings",
                  return_value=_holdings([("AAA", 50.0), ("BBB", 50.0)])),
            patch("services.fund_metrics.get_closes", return_value=closes),
        ):
            resp = client.get("/api/portfolio-metric-docs/diversificationRatio/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["etf_id"], "SPY")  # config.DOCS_EXAMPLE_ETF's default
        self.assertAlmostEqual(body["value"], 2 ** 0.5, places=3)
        self.assertNotIn("reason", body)

    def test_a_null_worked_example_carries_its_reason(self):
        with patch("services.fund_metrics.get_etf_holdings", return_value=([], False)):
            resp = client.get("/api/portfolio-metric-docs/diversificationRatio/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsNone(body["value"])
        self.assertIn("reason", body)

    def test_coverage_worked_example_never_carries_a_reason(self):
        with patch("services.fund_metrics.get_etf_holdings", return_value=([], False)):
            resp = client.get("/api/portfolio-metric-docs/trackedWeightCoverage/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["value"], 0)
        self.assertNotIn("reason", body)


if __name__ == "__main__":
    unittest.main()
