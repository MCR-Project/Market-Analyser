"""
Tests for `services.stats.cluster_correlation` (issue #143) - the grouping
the correlation matrix tab reorders and labels itself by.

Every matrix here is small enough to read the answer off by eye: the
expected groups come from the blocks each test builds, not from running the
function's own arithmetic a second time.

Two seams, both public: the function itself, and the `/api/correlation`
response's `clusters` field (`ResponseShapeTests`, which goes through
`_correlation_summary` so the DB path and the live path are covered by the
same key).

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

import services.stats as stats
from main import app
from services.cache import TTLCache
from services.market_data import _correlation_summary

client = TestClient(app, raise_server_exceptions=False)


def _matrix(tickers, pairs, default=None):
    """A symmetric ticker->ticker->ρ dict shaped like the API's `matrix`.
    `pairs` maps a frozenset-able (a, b) to a value; anything unlisted is
    `default` (None = "not enough shared history to compute"), the diagonal
    is always 1.0."""
    out = {a: {} for a in tickers}
    for a in tickers:
        for b in tickers:
            if a == b:
                out[a][b] = 1.0
            elif (a, b) in pairs:
                out[a][b] = pairs[(a, b)]
            elif (b, a) in pairs:
                out[a][b] = pairs[(b, a)]
            else:
                out[a][b] = default
    return out


class TwoBlockTests(unittest.TestCase):
    def test_two_clean_blocks_come_out_as_those_two_groups(self):
        tickers = ["A", "B", "C", "D", "E"]
        pairs = {
            ("A", "B"): 0.9, ("A", "C"): 0.9, ("B", "C"): 0.9,  # block one
            ("D", "E"): 0.8,                                     # block two
        }
        matrix = _matrix(tickers, pairs, default=0.1)           # between blocks

        groups = stats.cluster_correlation(matrix, tickers, 0.5)

        self.assertEqual(groups, [["A", "B", "C"], ["D", "E"]])


class NullPairTests(unittest.TestCase):
    """A pair with too little shared history is `None` (issue #97) - not a
    correlation of zero - and clustering must not turn it into one."""

    def test_a_null_pair_is_skipped_when_averaging_not_counted_as_zero(self):
        # A-B is the tightest pair, so they merge first. C is then compared
        # with the {A, B} group over the pairs that exist: A-C = 0.6, and
        # B-C is unknown. Skipping the unknown pair gives an average of
        # 0.6 (joins at 0.5); counting it as 0 would give 0.3 (would not).
        tickers = ["A", "B", "C"]
        matrix = _matrix(tickers, {("A", "B"): 0.9, ("A", "C"): 0.6})

        self.assertEqual(stats.cluster_correlation(matrix, tickers, 0.5), [["A", "B", "C"]])

    def test_groups_with_no_computed_pair_between_them_never_merge(self):
        # Nothing is known about how {A, B} and {C, D} relate, so no
        # threshold - not even the loosest a caller could pass - may join
        # them: "no evidence" is not "on average correlated enough".
        tickers = ["A", "B", "C", "D"]
        matrix = _matrix(tickers, {("A", "B"): 0.9, ("C", "D"): 0.9})

        self.assertEqual(
            stats.cluster_correlation(matrix, tickers, -1.0),
            [["A", "B"], ["C", "D"]],
        )

    def test_a_ticker_with_no_computed_pair_at_all_is_in_no_group(self):
        tickers = ["A", "B", "NEW"]
        matrix = _matrix(tickers, {("A", "B"): 0.9})

        self.assertEqual(stats.cluster_correlation(matrix, tickers, 0.5), [["A", "B"]])


class MethodTests(unittest.TestCase):
    def test_average_linkage_does_not_chain_through_a_bridge(self):
        # A-B and B-C are both tight, A-C is not. Single linkage would
        # follow the chain A-B-C into one group; average linkage weighs C
        # against A *and* B together: (0.2 + 0.9) / 2 = 0.55, below 0.6.
        tickers = ["A", "B", "C"]
        matrix = _matrix(tickers, {("A", "B"): 0.9, ("B", "C"): 0.9, ("A", "C"): 0.2})

        self.assertEqual(stats.cluster_correlation(matrix, tickers, 0.6), [["A", "B"]])

    def test_a_pair_exactly_at_the_threshold_joins_and_just_below_does_not(self):
        tickers = ["A", "B"]
        matrix = _matrix(tickers, {("A", "B"): 0.5})

        self.assertEqual(stats.cluster_correlation(matrix, tickers, 0.5), [["A", "B"]])
        self.assertEqual(stats.cluster_correlation(matrix, tickers, 0.5001), [])

    def test_a_tie_is_broken_by_position_in_the_ticker_list(self):
        # A-B and B-C tie at 0.9; the earlier pair joins first, and C then
        # averages only 0.5 against {A, B}. Same input, same answer, every
        # time - a tie must never depend on hash order or float noise.
        tickers = ["A", "B", "C"]
        matrix = _matrix(tickers, {("A", "B"): 0.9, ("B", "C"): 0.9, ("A", "C"): 0.1})

        first = stats.cluster_correlation(matrix, tickers, 0.6)
        self.assertEqual(first, [["A", "B"]])
        self.assertEqual(stats.cluster_correlation(matrix, tickers, 0.6), first)

    def test_members_and_groups_follow_the_order_of_the_ticker_list(self):
        # The caller passes holdings in weight order; a group keeps it.
        tickers = ["Z", "A", "M", "B"]
        matrix = _matrix(tickers, {("Z", "M"): 0.9, ("A", "B"): 0.8}, default=0.0)

        self.assertEqual(stats.cluster_correlation(matrix, tickers, 0.5), [["Z", "M"], ["A", "B"]])

    def test_negatively_correlated_names_are_not_grouped(self):
        tickers = ["A", "B"]
        matrix = _matrix(tickers, {("A", "B"): -0.6})

        self.assertEqual(stats.cluster_correlation(matrix, tickers, 0.0), [])

    def test_fewer_than_two_tickers_is_no_groups(self):
        self.assertEqual(stats.cluster_correlation({}, [], 0.5), [])
        self.assertEqual(stats.cluster_correlation({"A": {"A": 1.0}}, ["A"], 0.5), [])


def _two_factor_returns(tickers=("CLA", "CLB", "CLC", "CLD", "CLE"), rows=80):
    """Daily returns where CLA/CLB share one driver, CLC/CLD another, and
    CLE follows neither - so the groups the response should carry are
    known before anything is computed. Seeded, so it is the same frame on
    every run."""
    rng = np.random.default_rng(7)
    f1, f2 = rng.normal(0, 0.01, rows), rng.normal(0, 0.01, rows)
    noise = lambda: rng.normal(0, 0.002, rows)
    columns = {
        tickers[0]: f1 + noise(), tickers[1]: f1 + noise(),
        tickers[2]: f2 + noise(), tickers[3]: f2 + noise(),
        tickers[4]: rng.normal(0, 0.01, rows),
    }
    return pd.DataFrame(columns, index=pd.bdate_range("2025-01-01", periods=rows))


class ResponseShapeTests(unittest.TestCase):
    """`clusters` rides on the correlation response, computed where the DB
    path and the live path already meet (`_correlation_summary`), so one
    field covers both."""

    def test_summary_carries_the_groups_of_two_or_more(self):
        returns = _two_factor_returns()

        result = _correlation_summary(returns, ["CLA", "CLB", "CLC", "CLD", "CLE"])

        # CLE follows neither driver: in no group, but not dropped from the
        # matrix - the caller tells "alone" from "no history" by `averages`.
        self.assertEqual(result["clusters"], [["CLA", "CLB"], ["CLC", "CLD"]])
        self.assertIn("CLE", result["matrix"])

    def test_summary_with_nothing_to_correlate_has_no_groups(self):
        returns = pd.DataFrame(index=pd.to_datetime(["2024-06-06", "2024-06-07"]))

        self.assertEqual(_correlation_summary(returns, ["AAPL", "MSFT"])["clusters"], [])

    def test_the_endpoint_returns_clusters(self):
        returns = _two_factor_returns()
        closes = (1 + returns).cumprod() * 100
        holdings = [[t, 10.0] for t in closes.columns]
        with patch("api.routes.get_etf_holdings", return_value=(holdings, False)), \
             patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._price_frame_bundle", return_value={"close": closes}):
            resp = client.get("/api/correlation/CLTEST")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["clusters"], [["CLA", "CLB"], ["CLC", "CLD"]])

    def test_the_endpoint_returns_no_clusters_when_there_is_no_matrix(self):
        holdings = [["CLA", 10.0], ["CLB", 10.0]]
        with patch("api.routes.get_etf_holdings", return_value=(holdings, False)), \
             patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._price_frame_bundle", return_value={"close": None}):
            resp = client.get("/api/correlation/CLTEST")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["matrix"], {})
        self.assertEqual(resp.json()["clusters"], [])


if __name__ == "__main__":
    unittest.main()
