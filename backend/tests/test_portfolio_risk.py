"""
Tests for services/portfolio.py's compute_portfolio_risk (issue #113) and
POST /api/portfolio/risk.

Every case runs against synthetic prices, the same convention
test_portfolio.py follows, so the expected numbers are arithmetic anyone
can check by hand. What is being pinned down:

  - Per-holding risk shares sum to 100% within rounding.
  - Effective bets sits between 1 and the holding count, and is exactly 1
    for a basket of one - regardless of whether there is even enough
    price history to measure that one holding's own variance.
  - A basket that cannot support a joint covariance matrix (fewer than
    two holdings with a complete history, or no measurable variance at
    all) reports all three figures null with a reason, the same two
    conditions services.stats.risk_contribution/diversification_ratio
    themselves report None for.
  - Nothing is written, and the route is bounded by the same MAX_HOLDINGS
    simulate is.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from fastapi.testclient import TestClient

from main import app
from services.portfolio import MAX_HOLDINGS, compute_portfolio_risk

client = TestClient(app, raise_server_exceptions=False)


def frame(columns: dict, dates: list[str]) -> pd.DataFrame:
    """A wide date x ticker close frame, shaped like get_closes returns -
    the same small helper test_portfolio.py's own module defines,
    duplicated rather than imported so this file stays self-contained the
    way every other file in this suite is (no conftest.py here - see
    backend/CLAUDE.md)."""
    return pd.DataFrame(columns, index=pd.to_datetime(dates))


def run_risk(closes, holdings, **kwargs):
    with patch("services.portfolio.get_closes", return_value=closes):
        return compute_portfolio_risk(holdings, start="2020-01-01", end="2020-12-31", **kwargs)


class _WriteHostileQuery:
    """Reads are fine; any write fails the test that provoked it - the
    same double test_portfolio.py's own SimulateRouteTests uses."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def execute(self):
        from types import SimpleNamespace
        return SimpleNamespace(data=self._rows)

    def _refuse(self, *a, **k):
        raise AssertionError("computing a basket's risk must not write to Supabase")

    insert = update = upsert = delete = _refuse


class _WriteHostileClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        return _WriteHostileQuery(self._rows)


# ── The model ────────────────────────────────────────────────────────────────

class RiskShareTests(unittest.TestCase):
    def test_equal_variance_uncorrelated_holdings_split_risk_evenly(self):
        """Same A/B construction test_stats.py's own RiskContributionTests/
        AverageCorrelationTests use: equal variance, exactly zero sample
        covariance. Equally weighted, they must split the basket's risk
        exactly in half and correlate at exactly 0."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        closes = frame(
            {
                "A": [100.0, 102.0, 104.04, 101.9592, 99.920016],
                "B": [100.0, 102.0, 99.96, 101.9592, 99.920016],
            },
            dates,
        )

        result = run_risk(
            closes, [{"ticker": "A", "weight": 50}, {"ticker": "B", "weight": 50}]
        )

        self.assertAlmostEqual(result["riskShare"]["A"], 50.0, places=1)
        self.assertAlmostEqual(result["riskShare"]["B"], 50.0, places=1)
        self.assertAlmostEqual(sum(result["riskShare"].values()), 100.0, places=2)
        self.assertAlmostEqual(result["effectiveBets"], 2.0, places=2)
        self.assertAlmostEqual(result["averageCorrelation"], 0.0, places=2)
        self.assertEqual(result["reasons"], {})

    def test_a_concentrated_basket_has_fewer_effective_bets_than_holdings(self):
        """A and B move in lockstep (C is just A's own series again under
        a different name and a small weight): almost all of the basket's
        risk sits in the A/C pair, so effective bets must sit strictly
        between 1 (all the risk in one holding) and 3 (the holding
        count) - the acceptance criterion's own "between" case, not the
        equal-split boundary RiskShareTests' first test already covers."""
        dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        a_values = [100.0, 108.0, 96.0, 112.0, 90.0]
        b_values = [100.0, 100.5, 100.2, 100.8, 100.1]
        closes = frame({"A": a_values, "B": b_values, "C": list(a_values)}, dates)

        result = run_risk(
            closes,
            [
                {"ticker": "A", "weight": 45},
                {"ticker": "B", "weight": 10},
                {"ticker": "C", "weight": 45},
            ],
        )

        self.assertAlmostEqual(sum(result["riskShare"].values()), 100.0, places=1)
        self.assertGreater(result["effectiveBets"], 1.0)
        self.assertLess(result["effectiveBets"], 3.0)

    def test_a_negative_risk_share_still_keeps_effective_bets_in_bounds(self):
        """A holding whose own moves offset the rest of the basket's can
        carry a genuinely negative risk share - a real outcome of the
        Euler decomposition (issue #113's own reasoning), not noise. Two
        holdings that move perfectly opposite each other produce exactly
        that: AAPL's own share comes out above 100% and MSFT's below 0%,
        summing to 100% between them. effective_n is built for a
        non-negative set of weights, so effectiveBets must be computed
        from each share's magnitude - otherwise this exact basket would
        push the figure outside [1, 2], breaking the acceptance
        criterion's own guarantee rather than merely bending it."""
        dates = ["2020-01-02", "2020-06-01", "2020-11-01"]
        closes = frame({"AAPL": [100.0, 108.0, 96.0], "MSFT": [50.0, 47.0, 55.0]}, dates)

        result = run_risk(
            closes, [{"ticker": "AAPL", "weight": 60}, {"ticker": "MSFT", "weight": 40}]
        )

        self.assertLess(result["riskShare"]["MSFT"], 0.0)
        self.assertGreater(result["riskShare"]["AAPL"], 100.0)
        self.assertAlmostEqual(sum(result["riskShare"].values()), 100.0, places=1)
        self.assertGreaterEqual(result["effectiveBets"], 1.0)
        self.assertLessEqual(result["effectiveBets"], 2.0)

    def test_a_single_holding_basket_is_the_whole_of_its_own_risk(self):
        """One holding is trivially all of the basket's risk and the only
        bet in it - reported unconditionally, without needing enough
        price history to measure a variance from at all."""
        closes = frame({"NVDA": [100.0, 110.0]}, ["2020-01-02", "2020-01-03"])

        result = run_risk(closes, [{"ticker": "NVDA", "weight": 100}])

        self.assertEqual(result["riskShare"], {"NVDA": 100.0})
        self.assertEqual(result["effectiveBets"], 1.0)
        self.assertIsNone(result["averageCorrelation"])
        self.assertIn("no pair to correlate", result["reasons"]["averageCorrelation"])
        self.assertNotIn("effectiveBets", result["reasons"])
        self.assertNotIn("riskShare", result["reasons"])

    def test_incomplete_history_reports_all_three_null_with_a_reason(self):
        """A has a gap (a late-listing holding, say) - fewer than two
        holdings are left with a complete history, so there is no joint
        covariance matrix to build at all."""
        closes = frame(
            {"A": [100.0, float("nan"), 120.0], "B": [50.0, 60.0, 70.0]},
            ["2020-01-02", "2020-01-03", "2020-01-06"],
        )

        result = run_risk(
            closes, [{"ticker": "A", "weight": 50}, {"ticker": "B", "weight": 50}]
        )

        self.assertIsNone(result["averageCorrelation"])
        self.assertIsNone(result["effectiveBets"])
        self.assertIsNone(result["riskShare"])
        self.assertIn("complete price history", result["reasons"]["riskShare"])
        self.assertEqual(
            result["reasons"]["averageCorrelation"], result["reasons"]["effectiveBets"]
        )

    def test_a_flat_basket_has_no_variance_to_apportion(self):
        dates = ["2020-01-02", "2020-01-03", "2020-01-06"]
        flat = [100.0, 100.0, 100.0]
        closes = frame({"A": flat, "B": flat}, dates)

        result = run_risk(
            closes, [{"ticker": "A", "weight": 50}, {"ticker": "B", "weight": 50}]
        )

        self.assertIsNone(result["averageCorrelation"])
        self.assertIsNone(result["effectiveBets"])
        self.assertIsNone(result["riskShare"])
        self.assertIn("no measurable variance", result["reasons"]["riskShare"])

    def test_too_many_holdings_are_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            run_risk(
                None, [{"ticker": f"T{i}", "weight": 1} for i in range(MAX_HOLDINGS + 1)]
            )
        self.assertIn(f"{MAX_HOLDINGS} allowed", str(ctx.exception))

    def test_a_window_with_no_price_rows_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            run_risk(None, [{"ticker": "A", "weight": 1}])
        self.assertIn("no price data", str(ctx.exception))


# ── POST /api/portfolio/risk ─────────────────────────────────────────────────

class RiskRouteTests(unittest.TestCase):
    def _body(self, **overrides):
        body = {
            "holdings": [{"ticker": "AAPL", "weight": 60}, {"ticker": "MSFT", "weight": 40}],
            "value": 10_000,
            "start": "2020-01-01",
            "end": "2020-12-31",
        }
        body.update(overrides)
        return body

    def _rows(self):
        return [
            {"ticker": "AAPL", "date": "2020-01-02", "close": 100.0},
            {"ticker": "MSFT", "date": "2020-01-02", "close": 50.0},
            {"ticker": "AAPL", "date": "2020-06-01", "close": 108.0},
            {"ticker": "MSFT", "date": "2020-06-01", "close": 47.0},
            {"ticker": "AAPL", "date": "2020-11-01", "close": 96.0},
            {"ticker": "MSFT", "date": "2020-11-01", "close": 55.0},
        ]

    def test_a_baskets_risk_is_computed_and_nothing_is_written(self):
        db = _WriteHostileClient(self._rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            resp = client.post("/api/portfolio/risk", json=self._body())

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertAlmostEqual(sum(body["riskShare"].values()), 100.0, places=1)
        self.assertGreaterEqual(body["effectiveBets"], 1.0)
        self.assertLessEqual(body["effectiveBets"], 2.0001)

    def test_value_rebalance_and_contribution_are_accepted_but_unused(self):
        """Same body shape as simulate - value/rebalance/contribution/rate
        travel on the request for shape parity but change nothing about
        what this endpoint answers, since it is a question about the
        basket's price history rather than about a value simulated over
        it."""
        db = _WriteHostileClient(self._rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            plain = client.post("/api/portfolio/risk", json=self._body()).json()
            decorated = client.post(
                "/api/portfolio/risk",
                json=self._body(
                    value=99_000,
                    rebalance="monthly",
                    contribution={"amount": 500, "frequency": "monthly"},
                    rate=4.2,
                ),
            ).json()

        self.assertEqual(plain["riskShare"], decorated["riskShare"])
        self.assertEqual(plain["effectiveBets"], decorated["effectiveBets"])
        self.assertEqual(plain["averageCorrelation"], decorated["averageCorrelation"])

    def test_an_unusable_request_is_a_400_naming_the_problem(self):
        cases = [
            (self._body(holdings=[]), "non-empty"),
            (self._body(holdings=[{"ticker": "AAPL", "weight": -1}]), "negative"),
            (self._body(start="2020-12-31", end="2020-01-01"), "before"),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                resp = client.post("/api/portfolio/risk", json=body)
                self.assertEqual(resp.status_code, 400)
                self.assertIn(expected, resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
