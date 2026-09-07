"""
Tests for services/portfolio.py — the portfolio simulation (issue #56).

Every case here runs against synthetic prices rather than the market, so
the expected numbers are arithmetic anyone can check by hand rather than
whatever AAPL happened to do. What is being pinned down:

  - A portfolio of one ticker is that ticker. If a 100% NVDA portfolio
    does not track NVDA's own return exactly, nothing built on top of the
    simulation can be trusted either.
  - Buy and hold drifts and a rebalance does not. These are the two
    models the feature offers, and the difference between them is the
    whole reason the stacked chart is worth drawing.
  - An allocation waits in cash until its holding lists, and converts at
    that day's close - so the portfolio's total does not jump on the day
    a late-listing holding buys in.
  - Weights are ratios. 30/30/30 and 33.33/33.33/33.33 are the same
    portfolio and must produce byte-identical runs.
  - Nothing is stored. The portfolio arrives in the request and leaves in
    the response, and the write-hostile fake client here fails loudly if
    that ever stops being true.

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
from services.market_data import SymbolNotFound
from services.portfolio import MAX_HOLDINGS, simulate_portfolio

client = TestClient(app, raise_server_exceptions=False)


def frame(columns: dict, dates: list[str]) -> pd.DataFrame:
    """A wide date x ticker close frame, shaped like get_closes returns."""
    return pd.DataFrame(columns, index=pd.to_datetime(dates))


def run(closes, holdings, value=1000.0, rebalance="none", **kwargs):
    with patch("services.portfolio.get_closes", return_value=closes):
        return simulate_portfolio(
            holdings, value=value, start="2020-01-01", end="2020-12-31",
            rebalance=rebalance, **kwargs
        )


def holding(result, ticker):
    return next(h for h in result["holdings"] if h["ticker"] == ticker)


# ── The model ────────────────────────────────────────────────────────────────

class SingleHoldingTests(unittest.TestCase):
    def test_a_portfolio_of_one_ticker_is_that_ticker(self):
        """The simplest possible sanity check, and the one everything else
        rests on: with 100% in NVDA the portfolio's curve is NVDA's own
        close series, scaled."""
        closes = frame({"NVDA": [100.0, 110.0, 90.0, 120.0]},
                       ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])

        result = run(closes, [{"ticker": "NVDA", "weight": 100}])

        self.assertEqual(result["total"], [1000.0, 1100.0, 900.0, 1200.0])
        self.assertEqual(result["cash"], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(holding(result, "NVDA")["values"], result["total"])
        self.assertEqual(holding(result, "NVDA")["weight"], 100.0)
        self.assertEqual(holding(result, "NVDA")["firstDate"], "2020-01-02")
        self.assertEqual((result["start"], result["end"]), ("2020-01-02", "2020-01-07"))


class BuyAndHoldTests(unittest.TestCase):
    def test_a_winner_takes_over_the_portfolio(self):
        """Nothing is sold, so the holding that doubled is now two thirds
        of the portfolio. This drift is what the stacked chart shows, and
        what a continuously rebalanced model would hide."""
        closes = frame({"UP": [100.0, 200.0], "FLAT": [100.0, 100.0]},
                       ["2020-01-02", "2020-06-01"])

        result = run(closes, [{"ticker": "UP", "weight": 50}, {"ticker": "FLAT", "weight": 50}])

        self.assertEqual(result["total"], [1000.0, 1500.0])
        self.assertEqual(holding(result, "UP")["values"], [500.0, 1000.0])
        self.assertEqual(holding(result, "FLAT")["values"], [500.0, 500.0])

    def test_weights_are_ratios_not_percentages(self):
        """30/30/30 and 33.33/33.33/33.33 describe the same basket - the
        simulation normalises, so the two runs must be identical rather
        than merely close."""
        closes = frame(
            {"A": [10.0, 12.0], "B": [20.0, 19.0], "C": [5.0, 8.0]},
            ["2020-01-02", "2020-02-03"],
        )
        thirds = [{"ticker": t, "weight": 30} for t in ("A", "B", "C")]
        percents = [{"ticker": t, "weight": 33.33} for t in ("A", "B", "C")]

        self.assertEqual(run(closes, thirds), run(closes, percents))

    def test_bands_sum_to_the_total_on_every_date(self):
        """The chart draws the holdings stacked under the total line; if
        the rounded parts did not add up to the rounded whole, the top of
        the stack would not meet it."""
        closes = frame(
            {"A": [33.33, 41.11], "B": [7.77, 7.01], "C": [101.5, 99.25]},
            ["2020-01-02", "2020-03-02"],
        )

        result = run(closes, [{"ticker": "A", "weight": 1}, {"ticker": "B", "weight": 2},
                              {"ticker": "C", "weight": 7}], value=9_999.99)

        for i, total in enumerate(result["total"]):
            banded = sum(h["values"][i] for h in result["holdings"]) + result["cash"][i]
            self.assertAlmostEqual(banded, total, places=2)


class RebalanceTests(unittest.TestCase):
    def _closes(self):
        # Two dates inside January, one in February: the rebalance must
        # happen on the February row and not on the second January one.
        return frame({"UP": [100.0, 200.0, 200.0], "FLAT": [100.0, 100.0, 100.0]},
                     ["2020-01-02", "2020-01-15", "2020-02-03"])

    def _basket(self):
        return [{"ticker": "UP", "weight": 50}, {"ticker": "FLAT", "weight": 50}]

    def test_monthly_rebalance_restores_the_targets_on_the_first_row_of_a_month(self):
        result = run(self._closes(), self._basket(), rebalance="monthly")

        # Mid-January: drifted, because the month has not turned yet.
        self.assertEqual(holding(result, "UP")["values"][1], 1000.0)
        self.assertEqual(holding(result, "FLAT")["values"][1], 500.0)
        # February: half each of the 1500 the portfolio is now worth.
        self.assertEqual(holding(result, "UP")["values"][2], 750.0)
        self.assertEqual(holding(result, "FLAT")["values"][2], 750.0)
        self.assertEqual(result["total"], [1000.0, 1500.0, 1500.0])

    def test_buy_and_hold_is_the_default_and_does_not_rebalance(self):
        result = run(self._closes(), self._basket())

        self.assertEqual(result["rebalance"], "none")
        self.assertEqual(holding(result, "UP")["values"][2], 1000.0)
        self.assertEqual(holding(result, "FLAT")["values"][2], 500.0)

    def test_quarterly_and_yearly_ignore_a_boundary_they_do_not_share(self):
        """A new month is not a new quarter. The February row rebalances
        monthly and nothing else."""
        monthly = run(self._closes(), self._basket(), rebalance="monthly")
        quarterly = run(self._closes(), self._basket(), rebalance="quarterly")
        yearly = run(self._closes(), self._basket(), rebalance="yearly")
        held = run(self._closes(), self._basket())

        self.assertEqual(quarterly["holdings"], held["holdings"])
        self.assertEqual(yearly["holdings"], held["holdings"])
        self.assertNotEqual(monthly["holdings"], held["holdings"])

    def test_a_quarter_boundary_rebalances(self):
        closes = frame({"UP": [100.0, 200.0], "FLAT": [100.0, 100.0]},
                       ["2020-03-02", "2020-04-01"])

        result = run(closes, self._basket(), rebalance="quarterly")

        self.assertEqual(holding(result, "UP")["values"][1], 750.0)
        self.assertEqual(holding(result, "FLAT")["values"][1], 750.0)


class LateListingTests(unittest.TestCase):
    def _closes(self):
        return frame(
            {"OLD": [100.0, 100.0, 100.0, 100.0],
             "NEW": [float("nan"), float("nan"), 50.0, 100.0]},
            ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"],
        )

    def _basket(self):
        return [{"ticker": "OLD", "weight": 50}, {"ticker": "NEW", "weight": 50}]

    def test_an_allocation_waits_in_cash_and_buys_in_without_a_jump(self):
        """The allocation is held, not spent elsewhere and not invented at
        a price that did not exist. It converts at the first close the
        holding has, so the total is unmoved on the day it happens - the
        portfolio only starts tracking NEW from that day forward."""
        result = run(self._closes(), self._basket())

        self.assertEqual(result["cash"], [500.0, 500.0, 0.0, 0.0])
        self.assertEqual(holding(result, "NEW")["values"], [0.0, 0.0, 500.0, 1000.0])
        # Unmoved across the buy-in (index 1 -> 2), then tracking NEW.
        self.assertEqual(result["total"], [1000.0, 1000.0, 1000.0, 1500.0])
        self.assertEqual(holding(result, "NEW")["firstDate"], "2020-01-06")

    def test_a_rebalance_resizes_the_waiting_cash_rather_than_spending_it(self):
        """Rebalancing while a holding is still unlisted must not quietly
        buy more of the others with its money: the cash bucket is resized
        to its share of the new total and keeps waiting."""
        closes = frame(
            {"UP": [100.0, 200.0], "NEW": [float("nan"), float("nan")]},
            ["2020-01-02", "2020-02-03"],
        )

        result = run(closes, [{"ticker": "UP", "weight": 50}, {"ticker": "NEW", "weight": 50}],
                     rebalance="monthly")

        # 1000 -> UP doubled its 500, so the portfolio is 1500 and each
        # side's target is 750: UP sells down to it, NEW's cash grows to it.
        self.assertEqual(holding(result, "UP")["values"], [500.0, 750.0])
        self.assertEqual(result["cash"], [500.0, 750.0])
        self.assertEqual(result["total"], [1000.0, 1500.0])

    def test_a_holding_that_never_lists_stays_cash_for_the_whole_window(self):
        """No column at all, but the symbol is real - it listed after the
        window, or has no rows yet. Its allocation is cash throughout, and
        firstDate says so."""
        closes = frame({"OLD": [100.0, 120.0]}, ["2020-01-02", "2020-02-03"])

        with patch("services.portfolio.get_price_series", return_value=[{"date": "2021-01-04", "close": 10.0}]):
            result = run(closes, [{"ticker": "OLD", "weight": 50},
                                  {"ticker": "NEW", "weight": 50}])

        self.assertEqual(result["cash"], [500.0, 500.0])
        self.assertEqual(holding(result, "NEW")["values"], [0.0, 0.0])
        self.assertIsNone(holding(result, "NEW")["firstDate"])
        self.assertEqual(result["total"], [1000.0, 1100.0])

    def test_an_unknown_ticker_is_a_symbol_not_found_naming_it(self):
        """The same absent column as above, but upstream has never heard
        of the symbol - a typo must not be simulated as a pile of cash."""
        closes = frame({"OLD": [100.0, 120.0]}, ["2020-01-02", "2020-02-03"])

        with patch("services.portfolio.get_price_series", return_value=[]):
            with self.assertRaises(SymbolNotFound) as ctx:
                run(closes, [{"ticker": "OLD", "weight": 50}, {"ticker": "ZZZZ", "weight": 50}])

        self.assertIn("ZZZZ", str(ctx.exception))


class CalendarTests(unittest.TestCase):
    def test_a_gap_in_one_holding_does_not_delete_the_date_for_the_others(self):
        """The calendar is the union of the dates, not the intersection:
        a holding that did not trade keeps its last close (forward-filled)
        rather than removing that day from everyone else's history."""
        closes = frame(
            {"A": [100.0, float("nan"), 120.0], "B": [50.0, 60.0, 70.0]},
            ["2020-01-02", "2020-01-03", "2020-01-06"],
        )

        result = run(closes, [{"ticker": "A", "weight": 50}, {"ticker": "B", "weight": 50}])

        self.assertEqual(len(result["dates"]), 3)
        # A holds its 100 through the gap: 5 shares x 100.
        self.assertEqual(holding(result, "A")["values"], [500.0, 500.0, 600.0])
        self.assertEqual(holding(result, "B")["values"], [500.0, 600.0, 700.0])


# ── Validation ───────────────────────────────────────────────────────────────

class ValidationTests(unittest.TestCase):
    def _closes(self):
        return frame({"A": [100.0, 110.0]}, ["2020-01-02", "2020-02-03"])

    def _assert_rejected(self, expected, **kwargs):
        with self.assertRaises(ValueError) as ctx:
            run(self._closes(), kwargs.pop("holdings"), **kwargs)
        self.assertIn(expected, str(ctx.exception))

    def test_an_empty_basket_is_rejected(self):
        self._assert_rejected("non-empty", holdings=[])

    def test_a_duplicated_ticker_is_rejected(self):
        """Two lines for the same ticker are ambiguous - one holding with
        the summed weight, or a mistake - so the request is refused rather
        than guessed at."""
        self._assert_rejected(
            "twice",
            holdings=[{"ticker": "A", "weight": 50}, {"ticker": "a", "weight": 50}],
        )

    def test_a_negative_weight_is_rejected(self):
        self._assert_rejected(
            "negative", holdings=[{"ticker": "A", "weight": -10}]
        )

    def test_all_zero_weights_are_rejected(self):
        self._assert_rejected(
            "all zero",
            holdings=[{"ticker": "A", "weight": 0}, {"ticker": "B", "weight": 0}],
        )

    def test_a_weight_that_is_not_a_number_is_rejected(self):
        self._assert_rejected(
            "not a number", holdings=[{"ticker": "A", "weight": "half"}]
        )

    def test_too_many_holdings_are_rejected(self):
        self._assert_rejected(
            f"{MAX_HOLDINGS} allowed",
            holdings=[{"ticker": f"T{i}", "weight": 1} for i in range(MAX_HOLDINGS + 1)],
        )

    def test_a_non_positive_value_is_rejected(self):
        self._assert_rejected(
            "greater than zero", holdings=[{"ticker": "A", "weight": 1}], value=0
        )

    def test_an_unknown_rebalance_frequency_is_rejected(self):
        self._assert_rejected(
            "rebalance",
            holdings=[{"ticker": "A", "weight": 1}],
            rebalance="fortnightly",
        )

    def test_a_window_with_no_price_rows_is_rejected(self):
        """No trading days in the window (or no data at all for the
        basket) is a fact about the request, not a portfolio worth zero."""
        with self.assertRaises(ValueError) as ctx:
            run(None, [{"ticker": "A", "weight": 1}])
        self.assertIn("no price data", str(ctx.exception))


# ── POST /api/portfolio/simulate ─────────────────────────────────────────────

class _WriteHostileQuery:
    """Reads are fine; any write fails the test that provoked it."""

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
        raise AssertionError("simulating a portfolio must not write to Supabase")

    insert = update = upsert = delete = _refuse


class _WriteHostileClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        return _WriteHostileQuery(self._rows)


class SimulateRouteTests(unittest.TestCase):
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
            {"ticker": "AAPL", "date": "2020-06-01", "close": 200.0},
            {"ticker": "MSFT", "date": "2020-06-01", "close": 50.0},
        ]

    def test_a_portfolio_is_simulated_and_nothing_is_written(self):
        db = _WriteHostileClient(self._rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            resp = client.post("/api/portfolio/simulate", json=self._body())

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["dates"], ["2020-01-02", "2020-06-01"])
        self.assertEqual(body["total"], [10_000.0, 16_000.0])
        self.assertEqual([h["ticker"] for h in body["holdings"]], ["AAPL", "MSFT"])
        self.assertEqual([h["weight"] for h in body["holdings"]], [60.0, 40.0])

    def test_an_unusable_request_is_a_400_naming_the_problem(self):
        cases = [
            (self._body(holdings=[]), "non-empty"),
            (self._body(holdings=[{"ticker": "AAPL", "weight": -1}]), "negative"),
            (self._body(value=0), "greater than zero"),
            (self._body(rebalance="hourly"), "rebalance"),
            (self._body(start="2020-12-31", end="2020-01-01"), "before"),
        ]
        for body, expected in cases:
            with self.subTest(expected=expected):
                resp = client.post("/api/portfolio/simulate", json=body)
                self.assertEqual(resp.status_code, 400)
                self.assertIn(expected, resp.json()["detail"])

    def test_an_unknown_holding_is_a_404_naming_the_ticker(self):
        db = _WriteHostileClient(self._rows())
        with patch("services.market_data.get_client_optional", return_value=db), \
             patch("services.portfolio.get_price_series", return_value=[]):
            resp = client.post(
                "/api/portfolio/simulate",
                json=self._body(holdings=[{"ticker": "AAPL", "weight": 50},
                                          {"ticker": "ZZZZ", "weight": 50}]),
            )

        self.assertEqual(resp.status_code, 404)
        self.assertIn("ZZZZ", resp.json()["detail"])

    def test_the_browser_is_allowed_to_post(self):
        """CORS lists the methods explicitly, so a POST endpoint added
        without widening it works from curl and fails only in a browser -
        the preflight is the cheapest place to catch that."""
        resp = client.options(
            "/api/portfolio/simulate",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["access-control-allow-origin"], "http://localhost:5173")
        self.assertIn("POST", resp.headers["access-control-allow-methods"])


if __name__ == "__main__":
    unittest.main()
