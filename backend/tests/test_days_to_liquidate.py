"""
Tests for the Days to Liquidate measurement (issue #111): value held
divided by a holding's own average daily dollar volume.

services/stats.py's own bucket-correction arithmetic (average_bucketed_
daily_value) is covered by test_stats.py's AverageBucketedDailyValueTests;
this file pins down the acceptance criteria that only make sense at the
measurement level:

  - For a tracked holding the value matches a hand-computed value held /
    average daily dollar volume.
  - A window of monthly buckets and one of daily rows report comparable
    figures for the same holding.
  - ETF and live-resolved rows are dashes with reasons.

...plus the shared registry contract: manifest registration, a doc page,
and a real worked example.

No test here touches Supabase or yfinance: measurements.inputs.holdings.
get_etf_holdings, measurements.official_measurements.days_to_liquidate.
get_etf_info and ...get_price_frame are patched with synthetic data
throughout - each at the plugin's own imported binding (or, for
get_etf_holdings, the one module get_holdings itself is defined in - see
test_price_history_measurements.py's own _patched for the full reasoning
behind patching each getter at the point its own call resolves).

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


def _volume_frame(entries: dict[str, list[dict] | None], closes: dict[str, list[tuple[str, float]]]) -> dict:
    """The measurements.inputs.price_frame.get_price_frame(include_volume=True)
    shape: {ticker: {"closes": [[date, close], ...], "volume": [...] | None}}."""
    return {
        t: {"closes": [list(pair) for pair in closes[t]], "volume": entries[t]}
        for t in entries
    }


@contextmanager
def _patched(holdings, aum, frame):
    with (
        patch("measurements.inputs.holdings.get_etf_holdings", return_value=(holdings, False)),
        patch("measurements.official_measurements.days_to_liquidate.get_etf_info", return_value={"aum": aum}),
        patch("measurements.official_measurements.days_to_liquidate.get_price_frame", return_value=frame),
    ):
        yield


def _by_id():
    return {m.id: m for m in ALL_MEASUREMENTS}


def _plugin():
    return _by_id()["days_to_liquidate"]


class HandComputedFixtureTests(unittest.TestCase):
    def test_matches_a_hand_computed_value_held_over_average_daily_dollar_volume(self):
        # value held = $1.0B AUM * 50% = $500,000,000.
        # Daily rows (gaps of 1-3 days, all trading_days == 1): the first
        # row is dropped (no prior gap), leaving $10*2,000,000=$20,000,000
        # and $10*3,000,000=$30,000,000 -> average $25,000,000/day.
        # days = 500,000,000 / 25,000,000 = 20.0 exactly.
        holdings = [["AAA", 50.0]]
        closes = {"AAA": [("2020-01-02", 10.0), ("2020-01-03", 10.0), ("2020-01-06", 10.0)]}
        volume = {
            "AAA": [
                {"date": "2020-01-02", "volume": 1_000_000, "granularity": "D"},
                {"date": "2020-01-03", "volume": 2_000_000, "granularity": "D"},
                {"date": "2020-01-06", "volume": 3_000_000, "granularity": "D"},
            ]
        }
        frame = _volume_frame(volume, closes)

        with _patched(holdings, aum=1.0, frame=frame):
            result = _plugin().run(etf_id="TESTFUND1")

        self.assertAlmostEqual(result["per_ticker"]["AAA"], 20.0, places=6)
        self.assertIn("20.0d", result["per_ticker_mdx"]["AAA"])


class MonthlyAndDailyWindowsAgreeTests(unittest.TestCase):
    def test_a_monthly_bucketed_window_reads_close_to_a_daily_one(self):
        """The same steady $100/share, 1,000,000-share-a-day holding,
        answered once as 30 individual daily rows and once as a single
        monthly bucket summing the same 30 days of volume, must report
        comparable days-to-liquidate figures - not one about twenty times
        the other, which an uncorrected bucket average would give."""
        holdings = [["AAA", 100.0]]
        aum = 1.0  # $1B, so value held == $1,000,000,000 for both runs.

        daily_dates = [f"2020-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(31)]
        daily_closes = {"AAA": [(d, 100.0) for d in daily_dates]}
        daily_volume = {
            "AAA": [{"date": d, "volume": 1_000_000, "granularity": "D"} for d in daily_dates]
        }

        monthly_closes = {"AAA": [("2019-12-01", 100.0), ("2020-01-01", 100.0)]}
        monthly_volume = {
            "AAA": [
                {"date": "2019-12-01", "volume": 21_000_000, "granularity": "M"},
                {"date": "2020-01-01", "volume": 21_000_000, "granularity": "M"},
            ]
        }

        with _patched(holdings, aum, _volume_frame(daily_volume, daily_closes)):
            daily_result = _plugin().run(etf_id="TESTFUND2")
        with _patched(holdings, aum, _volume_frame(monthly_volume, monthly_closes)):
            monthly_result = _plugin().run(etf_id="TESTFUND2")

        daily_days = daily_result["per_ticker"]["AAA"]
        monthly_days = monthly_result["per_ticker"]["AAA"]
        self.assertIsNotNone(daily_days)
        self.assertIsNotNone(monthly_days)
        # Comparable, not off by anything near the ~21x an uncorrected
        # bucket-sum average would produce.
        self.assertAlmostEqual(monthly_days / daily_days, 1.0, delta=0.15)


class NullWithReasonTests(unittest.TestCase):
    def test_an_etf_type_or_live_resolved_holding_is_null_with_a_reason(self):
        holdings = [["ETFHOLDING", 100.0]]
        closes = {"ETFHOLDING": [("2020-01-02", 100.0), ("2020-01-03", 101.0)]}
        volume = {"ETFHOLDING": None}  # price_frame's own convention: no prices rows at all.
        frame = _volume_frame(volume, closes)

        with _patched(holdings, aum=1.0, frame=frame):
            result = _plugin().run(etf_id="TESTFUND3")

        self.assertIsNone(result["per_ticker"]["ETFHOLDING"])
        self.assertIn("ETFHOLDING", result["per_ticker_reason"])
        self.assertEqual(result["per_ticker_mdx"]["ETFHOLDING"], "—")

    def test_a_single_priced_date_has_no_bucket_width_to_measure_and_is_null(self):
        holdings = [["NEW", 100.0]]
        closes = {"NEW": [("2021-01-01", 50.0)]}
        volume = {"NEW": [{"date": "2021-01-01", "volume": 500_000, "granularity": "D"}]}
        frame = _volume_frame(volume, closes)

        with _patched(holdings, aum=1.0, frame=frame):
            result = _plugin().run(etf_id="TESTFUND4")

        self.assertIsNone(result["per_ticker"]["NEW"])
        self.assertIn("NEW", result["per_ticker_reason"])


class ManifestAndDocEndpointTests(unittest.TestCase):
    def test_registered_in_the_manifest(self):
        resp = client.get("/api/measurements")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("days_to_liquidate", {e["measurement_id"] for e in resp.json()})

    def test_has_a_written_doc(self):
        resp = client.get("/api/measurement-docs/days_to_liquidate")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["has_doc"])

    def test_worked_example_runs_end_to_end(self):
        holdings = [["AAA", 50.0], ["BBB", 50.0]]
        closes = {
            "AAA": [("2020-01-02", 10.0), ("2020-01-03", 10.0), ("2020-01-06", 10.0)],
            "BBB": [("2020-01-02", 20.0), ("2020-01-03", 20.0), ("2020-01-06", 20.0)],
        }
        volume = {
            "AAA": [
                {"date": "2020-01-02", "volume": 1_000_000, "granularity": "D"},
                {"date": "2020-01-03", "volume": 2_000_000, "granularity": "D"},
                {"date": "2020-01-06", "volume": 3_000_000, "granularity": "D"},
            ],
            "BBB": [
                {"date": "2020-01-02", "volume": 500_000, "granularity": "D"},
                {"date": "2020-01-03", "volume": 600_000, "granularity": "D"},
                {"date": "2020-01-06", "volume": 700_000, "granularity": "D"},
            ],
        }
        frame = _volume_frame(volume, closes)

        with _patched(holdings, aum=1.0, frame=frame):
            resp = client.get("/api/measurement-docs/days_to_liquidate/example")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("AAA", body["per_ticker"])
        self.assertIn("AAA", body["per_ticker_mdx"])


if __name__ == "__main__":
    unittest.main()
