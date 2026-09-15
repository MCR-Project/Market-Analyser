"""
Tests for the "metadata and income" measurements (issue #109): Market Cap,
Cap-Weight Tilt, and Dividend Yield & Income Share.

This file pins down the acceptance criteria that only make sense at the
measurement level:

  - An ETF-type (untracked) holding shows null with a reason for yield and
    income share, never 0.00.
  - Cap-weight tilts sum to approximately zero across a fund's tracked
    holdings.
  - Market cap renders with the same $/B/T formatting as Value Held.
  - Yield matches a hand-computed sum over fixtures, and income share is
    consistent with it (same trailing-dividends figure feeds both).

...plus the shared registry contract every measurement here follows: a doc
page and a real worked example, including dividend_income's own
multi-column one.

No test here touches Supabase or yfinance: measurements.inputs.holdings.
get_etf_holdings, measurements.inputs.stock_info.get_stock_info and
measurements.inputs.dividend_events.get_dividend_events are patched with
synthetic data throughout - each at the plugin module that imported it
directly, the same reasoning test_price_history_measurements.py's own
_patched documents (a `from x import y` binding is not reached by
patching `x.y`, only by patching the importing module's own copy).

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

client = TestClient(app, raise_server_exceptions=False)

PLUGIN_IDS = ["market_cap", "cap_weight_tilt", "dividend_income"]


def _stock_info(caps: dict[str, float | None]) -> dict:
    """The measurements.inputs.stock_info.get_stock_info shape, with every
    field but marketCap left out - none of these plugins read the rest."""
    return {ticker: {"marketCap": cap} for ticker, cap in caps.items()}


def _closes(values_by_ticker: dict[str, list[float]], dates: list[str]) -> dict:
    """The measurements.inputs.price_frame.get_price_frame shape."""
    return {
        t: {"closes": [[d, v] for d, v in zip(dates, values)]}
        for t, values in values_by_ticker.items()
    }


def _dividend_events(
    events_by_ticker: dict[str, list[tuple[str, float]]], tracked: set[str]
) -> dict:
    """The measurements.inputs.dividend_events.get_dividend_events shape."""
    tickers = set(events_by_ticker) | tracked
    return {
        t: {"events": [list(pair) for pair in events_by_ticker.get(t, [])], "tracked": t in tracked}
        for t in tickers
    }


@contextmanager
def _patched(holdings, caps=None, closes_by_ticker=None, events=None):
    """Patch every seam a plugin under test might reach `get_holdings`/
    `get_stock_info`/`get_price_frame`/`get_dividend_events` through - see
    this file's own module docstring for why each is patched individually
    rather than at its origin module."""
    with (
        patch("measurements.inputs.holdings.get_etf_holdings", return_value=(holdings, False)),
        patch("measurements.official_measurements.market_cap.get_stock_info", return_value=caps or {}),
        patch("measurements.official_measurements.cap_weight_tilt.get_stock_info", return_value=caps or {}),
        patch("measurements.official_measurements.dividend_income.get_price_frame", return_value=closes_by_ticker or {}),
        patch("measurements.official_measurements.dividend_income.get_dividend_events", return_value=events or {}),
    ):
        yield


def _by_id():
    return {m.id: m for m in ALL_MEASUREMENTS}


# ── Market Cap ───────────────────────────────────────────────────────────────

class MarketCapFormattingTests(unittest.TestCase):
    def test_market_cap_matches_value_helds_own_dollar_thresholds(self):
        holdings = [["MEGA", 40.0], ["MID", 30.0], ["SMALL", 30.0]]
        caps = _stock_info({
            "MEGA": 3_500_000_000_000.0,   # $3.5T
            "MID": 61_800_000_000.0,       # $61.8B
            "SMALL": 500_000_000.0,        # $500M
        })

        with _patched(holdings, caps=caps):
            result = _by_id()["market_cap"].run(etf_id="TESTFUND1")

        self.assertAlmostEqual(result["per_ticker"]["MEGA"], 3500.0, places=2)
        self.assertAlmostEqual(result["per_ticker"]["MID"], 61.8, places=2)
        self.assertAlmostEqual(result["per_ticker"]["SMALL"], 0.5, places=2)

        self.assertIn("$3.50T", result["per_ticker_mdx"]["MEGA"])
        self.assertIn("$61.8B", result["per_ticker_mdx"]["MID"])
        self.assertIn("$500M", result["per_ticker_mdx"]["SMALL"])

    def test_a_holding_with_no_market_cap_on_record_is_null_with_a_reason(self):
        holdings = [["ETFHOLDING", 100.0]]
        caps = _stock_info({"ETFHOLDING": None})

        with _patched(holdings, caps=caps):
            result = _by_id()["market_cap"].run(etf_id="TESTFUND1")

        self.assertIsNone(result["per_ticker"]["ETFHOLDING"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"])
        self.assertEqual(result["per_ticker_mdx"]["ETFHOLDING"], "—")


# ── Cap-Weight Tilt ──────────────────────────────────────────────────────────

class CapWeightTiltSumsToZeroTests(unittest.TestCase):
    def test_tilts_sum_to_approximately_zero_when_weights_sum_to_100(self):
        holdings = [["AAA", 50.0], ["BBB", 30.0], ["CCC", 20.0]]
        # Market caps deliberately not proportional to weight, so this is
        # a real check of the summing property rather than a trivial
        # all-zero case.
        caps = _stock_info({"AAA": 200.0, "BBB": 500.0, "CCC": 100.0})

        with _patched(holdings, caps=caps):
            result = _by_id()["cap_weight_tilt"].run(etf_id="TESTFUND2")

        total = sum(result["per_ticker"].values())
        self.assertAlmostEqual(total, 0.0, places=3)
        # And a genuine spread, not every holding landing on zero by luck.
        self.assertTrue(any(v != 0.0 for v in result["per_ticker"].values()))

    def test_a_holding_with_no_market_cap_is_excluded_from_the_denominator_and_null(self):
        holdings = [["AAA", 60.0], ["NOCAP", 40.0]]
        caps = _stock_info({"AAA": 100.0, "NOCAP": None})

        with _patched(holdings, caps=caps):
            result = _by_id()["cap_weight_tilt"].run(etf_id="TESTFUND2")

        self.assertIsNone(result["per_ticker"]["NOCAP"])
        self.assertIn("NOCAP", result["per_ticker_reason"])
        # AAA is the only capped holding, so it is 100% of the (smaller)
        # denominator - its own tilt is its weight less 100.
        self.assertAlmostEqual(result["per_ticker"]["AAA"], 60.0 - 100.0, places=3)


# ── Dividend Yield & Income Share ───────────────────────────────────────────

class DividendIncomeUntrackedIsNullTests(unittest.TestCase):
    def test_an_etf_type_holding_is_null_with_a_reason_never_zero(self):
        """An untracked holding (every ETF, per dividend_events' own
        contract) must never render 0.00 - that would claim it pays no
        dividend rather than that this app has no record of one."""
        holdings = [["ETFHOLDING", 100.0]]
        dates = ["2020-01-02", "2020-06-01", "2021-01-01"]
        closes = _closes({"ETFHOLDING": [100.0, 105.0, 110.0]}, dates)
        events = _dividend_events({}, tracked=set())  # not on record at all

        with _patched(holdings, closes_by_ticker=closes, events=events):
            result = _by_id()["dividend_income"].run(etf_id="TESTFUND3")

        self.assertIsNone(result["per_ticker"]["dividend_yield"]["ETFHOLDING"])
        self.assertIsNone(result["per_ticker"]["income_share"]["ETFHOLDING"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"]["dividend_yield"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"]["income_share"])
        self.assertEqual(result["per_ticker_mdx"]["dividend_yield"]["ETFHOLDING"], "—")
        self.assertEqual(result["per_ticker_mdx"]["income_share"]["ETFHOLDING"], "—")


class DividendYieldAndIncomeShareMatchHandComputationTests(unittest.TestCase):
    def test_yield_and_income_share_match_a_hand_computed_fixture(self):
        holdings = [["AAA", 100.0]]
        dates = ["2020-01-02", "2020-06-01", "2021-01-01"]
        closes = _closes({"AAA": [100.0, 105.0, 110.0]}, dates)
        # $1 + $1.50 = $2.50 declared over the window, both inside it.
        events = _dividend_events(
            {"AAA": [("2020-06-01", 1.0), ("2020-12-01", 1.5)]}, tracked={"AAA"}
        )

        with _patched(holdings, closes_by_ticker=closes, events=events):
            result = _by_id()["dividend_income"].run(etf_id="TESTFUND4")

        expected_yield = 2.5 / 110.0 * 100          # ~2.2727%
        expected_income_share = 2.5 / (10.0 + 2.5) * 100  # dividends / (price change + dividends)

        self.assertAlmostEqual(result["per_ticker"]["dividend_yield"]["AAA"], expected_yield, places=4)
        self.assertAlmostEqual(result["per_ticker"]["income_share"]["AAA"], expected_income_share, places=4)

        # Both read from the same trailing-dividends figure, so scaling
        # the payouts must move both together in the same direction.
        richer_events = _dividend_events(
            {"AAA": [("2020-06-01", 2.0), ("2020-12-01", 3.0)]}, tracked={"AAA"}
        )
        with _patched(holdings, closes_by_ticker=closes, events=richer_events):
            richer = _by_id()["dividend_income"].run(etf_id="TESTFUND4")

        self.assertGreater(richer["per_ticker"]["dividend_yield"]["AAA"], expected_yield)
        self.assertGreater(richer["per_ticker"]["income_share"]["AAA"], expected_income_share)

    def test_a_dividend_paid_outside_the_priced_window_is_excluded(self):
        holdings = [["AAA", 100.0]]
        dates = ["2020-01-02", "2021-01-01"]
        closes = _closes({"AAA": [100.0, 110.0]}, dates)
        events = _dividend_events(
            {"AAA": [("2019-01-01", 5.0), ("2020-06-01", 1.0)]}, tracked={"AAA"}
        )

        with _patched(holdings, closes_by_ticker=closes, events=events):
            result = _by_id()["dividend_income"].run(etf_id="TESTFUND4")

        # Only the $1 paid inside [2020-01-02, 2021-01-01] counts.
        self.assertAlmostEqual(result["per_ticker"]["dividend_yield"]["AAA"], 1.0 / 110.0 * 100, places=4)

    def test_no_net_return_over_the_window_is_null_income_share(self):
        holdings = [["AAA", 100.0]]
        dates = ["2020-01-02", "2021-01-01"]
        closes = _closes({"AAA": [100.0, 99.0]}, dates)  # price fell $1
        events = _dividend_events({"AAA": [("2020-06-01", 1.0)]}, tracked={"AAA"})  # paid $1

        with _patched(holdings, closes_by_ticker=closes, events=events):
            result = _by_id()["dividend_income"].run(etf_id="TESTFUND4")

        self.assertIsNotNone(result["per_ticker"]["dividend_yield"]["AAA"])
        self.assertIsNone(result["per_ticker"]["income_share"]["AAA"])
        self.assertIn("AAA", result["per_ticker_reason"]["income_share"])


# ── Manifest, docs, and worked examples ─────────────────────────────────────

class ManifestAndDocEndpointTests(unittest.TestCase):
    def test_every_plugin_is_registered_in_the_manifest(self):
        resp = client.get("/api/measurements")
        self.assertEqual(resp.status_code, 200)
        measurement_ids = {e["measurement_id"] for e in resp.json()}
        for plugin_id in PLUGIN_IDS:
            self.assertIn(plugin_id, measurement_ids)

        entries = resp.json()
        dividend_income_entries = [e for e in entries if e["measurement_id"] == "dividend_income"]
        self.assertEqual(
            sorted(e["id"] for e in dividend_income_entries),
            ["dividend_income.dividend_yield", "dividend_income.income_share"],
        )

    def test_every_plugin_has_a_written_doc(self):
        for plugin_id in PLUGIN_IDS:
            with self.subTest(id=plugin_id):
                resp = client.get(f"/api/measurement-docs/{plugin_id}")
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json()["has_doc"])

    def test_single_column_worked_examples_run_end_to_end(self):
        holdings = [["AAA", 50.0], ["BBB", 50.0]]
        caps = _stock_info({"AAA": 100.0, "BBB": 200.0})

        for plugin_id in ("market_cap", "cap_weight_tilt"):
            with self.subTest(plugin=plugin_id):
                with _patched(holdings, caps=caps):
                    resp = client.get(f"/api/measurement-docs/{plugin_id}/example")

                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertIn("AAA", body["per_ticker"])
                self.assertIn("AAA", body["per_ticker_mdx"])

    def test_multi_column_worked_example_nests_by_column_and_lists_them(self):
        holdings = [["AAA", 50.0], ["BBB", 50.0]]
        dates = ["2020-01-02", "2021-01-01"]
        closes = _closes({"AAA": [100.0, 110.0], "BBB": [100.0, 90.0]}, dates)
        events = _dividend_events({"AAA": [("2020-06-01", 1.0)]}, tracked={"AAA", "BBB"})

        with _patched(holdings, closes_by_ticker=closes, events=events):
            resp = client.get("/api/measurement-docs/dividend_income/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(
            sorted(c["key"] for c in body["columns"]), ["dividend_yield", "income_share"]
        )
        for key in ("dividend_yield", "income_share"):
            self.assertIn(key, body["per_ticker"])
            self.assertIn("AAA", body["per_ticker"][key])


if __name__ == "__main__":
    unittest.main()
