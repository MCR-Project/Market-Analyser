"""
Tests for the Weighted Correlation measurement (issue #185) and the
`weightedAverages` field it adds beside `averages` on GET /api/correlation.

The arithmetic itself is covered by test_stats.py's WeightedPeerCorrelationTests;
this file pins down what only makes sense above it:

  - the plugin reads the same matrix the plain column does and answers the
    issue's hand-checkable case through `run()`;
  - a null is a dash with a reason, for each of the ways one can arise;
  - the route's field is the plugin's column, over the same holdings - and,
    for a deep-filled fund, over the whole basket both read;
  - `correlation`'s manifest row did not move.

No test here touches Supabase or yfinance: `get_etf_holdings` and the
correlation matrix are patched at the binding each caller resolves them by.

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
from rate_limit import FixedWindowLimiter
import services.stats as stats
from measurements import ALL_MEASUREMENTS
from measurements.docs import load_doc
from measurements.examples import build_example
from measurements.registry import _column_manifest_entries

client = TestClient(app, raise_server_exceptions=False)

_limiter_patches = []


def setUpModule():
    # Every TestClient shares one address, so the /api calls made here would spend the
    # real per-minute bucket the rest of the suite relies on (backend/CLAUDE.md, "Tests").
    for name in ("rate_limit.general_limiter", "rate_limit.simulate_limiter"):
        patcher = patch(name, FixedWindowLimiter(limit=100_000))
        patcher.start()
        _limiter_patches.append(patcher)


def tearDownModule():
    for patcher in _limiter_patches:
        patcher.stop()
    _limiter_patches.clear()


BY_ID = {m.id: m for m in ALL_MEASUREMENTS}
WEIGHTED = BY_ID["weighted_correlation"]

# The issue's case: C correlates 0.8 with A (weight 50) and 0.2 with B (weight 10).
HOLDINGS = [["A", 50.0], ["B", 10.0], ["C", 5.0]]
MATRIX = {
    "A": {"A": 1.0, "B": 0.5, "C": 0.8},
    "B": {"A": 0.5, "B": 1.0, "C": 0.2},
    "C": {"A": 0.8, "B": 0.2, "C": 1.0},
}


def _result(matrix):
    return {
        "matrix": matrix,
        "tickers": list(matrix),
        "averages": {},
        "strongest": None,
        "weakest": None,
        "hub": None,
        "clusters": [],
    }


@contextmanager
def _patched(holdings=HOLDINGS, matrix=MATRIX):
    result = _result(matrix)
    with (
        patch("measurements.inputs.holdings.get_etf_holdings", return_value=(holdings, False)),
        patch(
            "measurements.official_measurements.weighted_correlation.get_correlation_matrix",
            return_value=result,
        ),
        patch("measurements.inputs.correlation_matrix.get_correlation_matrix", return_value=result),
        patch("api.routes.get_etf_holdings", return_value=(holdings, False)),
        patch("api.routes.compute_correlation_matrix", return_value=result),
    ):
        yield


class PluginTests(unittest.TestCase):
    def test_the_hand_checkable_case_scores_point_seven(self):
        """(50*0.8 + 10*0.2) / 60 = 0.70; the plain average would give 0.50."""
        with _patched():
            result = WEIGHTED.run(etf_id="ETF")

        self.assertEqual(result["per_ticker"]["C"], 0.7)

    def test_a_holdings_own_weight_does_not_change_its_own_score(self):
        with _patched(holdings=[["A", 50.0], ["B", 10.0], ["C", 5.0]]):
            small = WEIGHTED.run(etf_id="ETF")["per_ticker"]
        with _patched(holdings=[["A", 50.0], ["B", 10.0], ["C", 40.0]]):
            large = WEIGHTED.run(etf_id="ETF")["per_ticker"]

        self.assertEqual(small["C"], large["C"])
        self.assertNotEqual(small["A"], large["A"])

    def test_a_pair_with_no_computed_rho_leaves_the_denominator(self):
        matrix = {
            "A": {"A": 1.0, "B": 0.5, "C": 0.8},
            "B": {"A": 0.5, "B": 1.0, "C": None},
            "C": {"A": 0.8, "B": None, "C": 1.0},
        }
        with _patched(matrix=matrix):
            result = WEIGHTED.run(etf_id="ETF")

        self.assertEqual(result["per_ticker"]["C"], 0.8)

    def test_a_holding_with_no_computed_pair_is_null_with_a_reason(self):
        matrix = {
            "A": {"A": 1.0, "B": 0.5, "C": None},
            "B": {"A": 0.5, "B": 1.0, "C": None},
            "C": {"A": None, "B": None, "C": 1.0},
        }
        with _patched(matrix=matrix):
            result = WEIGHTED.run(etf_id="ETF")

        self.assertIsNone(result["per_ticker"]["C"])
        self.assertIn("overlapping", result["per_ticker_reason"]["C"])
        self.assertEqual(result["per_ticker_mdx"]["C"], "—")
        self.assertNotIn("A", result["per_ticker_reason"])

    def test_a_holding_the_matrix_dropped_is_null_with_a_reason(self):
        """No price history at all: the matrix leaves it out, but the table
        still gets a row for it, with a dash and the reason."""
        matrix = {"A": {"A": 1.0, "B": 0.5}, "B": {"A": 0.5, "B": 1.0}}
        with _patched(matrix=matrix):
            result = WEIGHTED.run(etf_id="ETF")

        self.assertIsNone(result["per_ticker"]["C"])
        self.assertIn("price history", result["per_ticker_reason"]["C"])
        self.assertEqual(result["per_ticker"]["A"], 0.5)

    def test_an_empty_or_one_ticker_matrix_says_there_is_nobody_to_correlate_with(self):
        """Not "no price history": the one holding that has some is told that too
        if the matrix could not be built around it."""
        for matrix in ({}, {"A": {"A": 1.0}}):
            with _patched(matrix=matrix):
                result = WEIGHTED.run(etf_id="ETF")

            self.assertEqual(set(result["per_ticker_reason"]), {"A", "B", "C"})
            for reason in result["per_ticker_reason"].values():
                self.assertIn("fewer than two", reason)

    def test_the_overlap_reason_names_the_threshold_the_matrix_uses(self):
        from config import MIN_OVERLAPPING_RETURNS
        matrix = {
            "A": {"A": 1.0, "B": 0.5, "C": None},
            "B": {"A": 0.5, "B": 1.0, "C": None},
            "C": {"A": None, "B": None, "C": 1.0},
        }
        with _patched(matrix=matrix):
            result = WEIGHTED.run(etf_id="ETF")

        self.assertIn(str(MIN_OVERLAPPING_RETURNS), result["per_ticker_reason"]["C"])

    def test_peers_with_no_weight_are_told_apart_from_no_overlap(self):
        holdings = [["A", 50.0], ["B", 0.0], ["C", 0.0]]
        with _patched(holdings=holdings):
            result = WEIGHTED.run(etf_id="ETF")

        self.assertIsNone(result["per_ticker"]["A"])
        self.assertIn("weight", result["per_ticker_reason"]["A"])

    def test_no_holdings_is_an_empty_answer(self):
        with _patched(holdings=[], matrix={}):
            result = WEIGHTED.run(etf_id="ETF")

        self.assertEqual(result["per_ticker"], {})

    def test_the_cell_is_the_same_bar_the_plain_column_draws(self):
        plain = BY_ID["correlation"]

        for value in (0.7, 0.05, 0.999, -0.2, None):
            self.assertEqual(
                WEIGHTED.render_cell("C", value, "weighted_corr"),
                plain.render_cell("C", value, "avg_corr"),
            )


class ManifestTests(unittest.TestCase):
    def test_it_is_listed_off_by_default_with_the_plain_columns_range(self):
        (entry,) = _column_manifest_entries(WEIGHTED)
        (plain,) = _column_manifest_entries(BY_ID["correlation"])

        self.assertEqual(entry["id"], "weighted_correlation")
        self.assertEqual(entry["name"], "Weighted Correlation")
        self.assertEqual(entry["column_key"], "weighted_corr")
        self.assertEqual(entry["column_label"], "WEIGHTED ρ")
        self.assertEqual(entry["uses_inputs"], ["holdings", "correlation_matrix"])
        self.assertFalse(entry["default_enabled"])
        self.assertEqual(entry["window_options"], [])
        self.assertTrue(entry["has_doc"])
        for field in ("filter_type", "filter_min", "filter_max", "filter_step", "sort_type", "column_width"):
            self.assertEqual(entry[field], plain[field], field)

    def test_correlations_own_row_is_unchanged(self):
        (entry,) = _column_manifest_entries(BY_ID["correlation"])

        self.assertEqual(entry["id"], "correlation")
        self.assertEqual(entry["measurement_id"], "correlation")
        self.assertEqual(entry["name"], "Correlation to Fund")
        self.assertEqual(entry["route"], "/measurements/correlation/{etf_id}")
        self.assertEqual(entry["column_key"], "avg_corr")
        self.assertEqual(entry["column_label"], "CORRELATION")
        self.assertEqual(entry["column_width"], 350)
        self.assertTrue(entry["default_enabled"])
        self.assertEqual(entry["filter_min"], 0)
        self.assertEqual(entry["filter_max"], 0.9)
        self.assertEqual(entry["filter_step"], 0.05)
        self.assertEqual(entry["uses_inputs"], ["holdings", "correlation_matrix"])
        self.assertEqual(
            entry["output_schema"]["per_ticker"]["description"], "Ticker → average ρ to all peers"
        )

    def test_the_live_manifest_lists_both_columns(self):
        rows = {row["id"]: row for row in client.get("/api/measurements").json()}

        self.assertIn("weighted_correlation", rows)
        self.assertEqual(rows["weighted_correlation"]["column_key"], "weighted_corr")
        self.assertEqual(rows["correlation"]["column_key"], "avg_corr")

    def test_its_route_answers_with_the_column(self):
        with _patched():
            resp = client.get("/api/measurements/weighted-correlation/ETF")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["per_ticker"]["C"], 0.7)


class DocTests(unittest.TestCase):
    def test_the_doc_loads_with_its_sections_and_places_the_worked_example(self):
        doc = load_doc(WEIGHTED)

        self.assertEqual(doc["frontmatter"]["title"], "Weighted Correlation")
        for section in ("What it measures", "Where the numbers come from", "How it is computed",
                        "How it reads", "Caveats"):
            self.assertIn(section, doc["mdx"])
        self.assertIn("<WorkedExample />", doc["mdx"])

    def test_the_hand_worked_figures_in_the_doc_are_the_ones_the_code_gives(self):
        """The doc states 50*0.8 + 10*0.2 over 60 = 0.70, and 0.50 plain. If
        the arithmetic ever moves, the doc must fail rather than go stale."""
        body = load_doc(WEIGHTED)["mdx"]
        for fragment in (r"50 \cdot 0.8 + 10 \cdot 0.2", "= 0.70", "0.50"):
            self.assertIn(fragment, body)

        scores = stats.weighted_peer_correlation(MATRIX, {"A": 50.0, "B": 10.0})
        self.assertEqual(scores["C"], 0.7)
        self.assertEqual((0.8 + 0.2) / 2, 0.5)

    def test_the_worked_example_renders_real_values_for_the_sample(self):
        with _patched():
            example = build_example(WEIGHTED, load_doc(WEIGHTED)["frontmatter"])

        self.assertEqual(example["per_ticker"]["C"], 0.7)
        self.assertEqual(example["per_ticker_mdx"]["C"], WEIGHTED.render_cell("C", 0.7, "weighted_corr"))
        self.assertEqual([entry["name"] for entry in example["inputs"]], ["holdings", "correlation_matrix"])

    def test_the_doc_endpoint_serves_it(self):
        resp = client.get("/api/measurement-docs/weighted_correlation")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["has_doc"])


class RouteTests(unittest.TestCase):
    def test_weighted_averages_sit_beside_averages(self):
        with _patched():
            body = client.get("/api/correlation/ETF").json()

        self.assertEqual(body["weightedAverages"]["C"], 0.7)
        self.assertEqual(set(body["weightedAverages"]), set(MATRIX))

    def test_the_route_figure_equals_the_table_column_for_the_same_fund(self):
        """The Network tab's card and the table column are one number."""
        with _patched():
            route = client.get("/api/correlation/ETF").json()["weightedAverages"]
            column = WEIGHTED.run(etf_id="ETF")["per_ticker"]

        self.assertEqual(route, column)

    def test_a_null_stays_null_in_the_api(self):
        matrix = {
            "A": {"A": 1.0, "B": 0.5, "C": None},
            "B": {"A": 0.5, "B": 1.0, "C": None},
            "C": {"A": None, "B": None, "C": 1.0},
        }
        with _patched(matrix=matrix):
            body = client.get("/api/correlation/ETF").json()

        self.assertIsNone(body["weightedAverages"]["C"])

    def test_an_empty_matrix_answers_an_empty_field(self):
        with _patched(matrix={}):
            body = client.get("/api/correlation/ETF").json()

        self.assertEqual(body["weightedAverages"], {})

    def test_the_whole_basket_is_weighted_while_the_fund_is_deep_filled(self):
        """The route and the column read `get_etf_holdings` - which lays a
        deep-filled fund's Untracked tail over the tracked list - so a tail
        peer's weight counts in both."""
        holdings = HOLDINGS + [["T", 30.0]]
        matrix = {
            "A": {"A": 1.0, "B": 0.5, "C": 0.8, "T": 0.0},
            "B": {"A": 0.5, "B": 1.0, "C": 0.2, "T": 0.0},
            "C": {"A": 0.8, "B": 0.2, "C": 1.0, "T": 1.0},
            "T": {"A": 0.0, "B": 0.0, "C": 1.0, "T": 1.0},
        }
        with _patched(holdings=holdings, matrix=matrix):
            route = client.get("/api/correlation/ETF").json()["weightedAverages"]
            column = WEIGHTED.run(etf_id="ETF")["per_ticker"]

        # (50*0.8 + 10*0.2 + 30*1.0) / 90
        self.assertEqual(route["C"], 0.8)
        self.assertEqual(route, column)


if __name__ == "__main__":
    unittest.main()
