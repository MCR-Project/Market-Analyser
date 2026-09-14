"""
Tests for the optional per_ticker_reason sidecar (issue #99).

`MeasurementBase.run()` and the worked-example builder both treat a
reason as trustworthy only when it lines up with an actual null - a
measurement author naming a reason for a ticker that also has a real
value is a mistake, and the frontend is entitled to read "there is a
reason" as proof "there is no value" without re-checking per_ticker
itself. That trust is what these tests protect, along with the
byte-for-byte guarantee that a measurement which never sets a reason - all
three official ones, today - gets back exactly the response it always
has.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from main import app
from measurements import ALL_MEASUREMENTS
from measurements.base import MeasurementBase
from measurements.examples import build_example

client = TestClient(app, raise_server_exceptions=False)


class ReasonMeasurement(MeasurementBase):
    """A stand-in plugin exercising per_ticker_reason directly, so these
    tests don't depend on any official measurement ever having a real
    null to show."""

    id = "reason_fake"
    name = "Reason Fake"
    description = "A stand-in used by the tests."
    route = "/measurements/reason-fake/{etf_id}"
    origin = "official"
    uses_inputs = ["holdings"]

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        return {}

    def compute(self, inputs: dict) -> dict:
        return {
            "per_ticker": {"NEW": None, "OLD": 1.0},
            # NEW is genuinely null - the reason belongs there. OLD is a
            # measurement author's mistake: a real value with a reason
            # attached anyway, which run() must not ship.
            "per_ticker_reason": {
                "NEW": "computed over 40 days of history - fewer than the "
                       "252 this measurement needs",
                "OLD": "should never reach the response",
            },
        }

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        return "—" if value is None else f'<Stat text="{value}" />'


class NoReasonMeasurement(MeasurementBase):
    """A stand-in that never mentions per_ticker_reason at all - the
    shape every official measurement has today."""

    id = "no_reason_fake"
    name = "No Reason Fake"
    description = "A stand-in used by the tests."
    route = "/measurements/no-reason-fake/{etf_id}"
    origin = "official"

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        return {}

    def compute(self, inputs: dict) -> dict:
        return {"per_ticker": {"AAPL": 1.0, "MISSING": None}}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        return "—" if value is None else f'<Stat text="{value}" />'


class RunReasonTests(unittest.TestCase):
    def test_a_null_value_surfaces_its_reason(self):
        result = ReasonMeasurement().run(etf_id="SPY")

        self.assertEqual(
            result["per_ticker_reason"]["NEW"],
            "computed over 40 days of history - fewer than the 252 this "
            "measurement needs",
        )

    def test_a_present_value_carries_no_reason_even_if_one_was_returned(self):
        """OLD has a real value (1.0); the reason the measurement mistakenly
        attached to it must not reach the response."""
        result = ReasonMeasurement().run(etf_id="SPY")

        self.assertNotIn("OLD", result["per_ticker_reason"])

    def test_a_measurement_that_never_sets_a_reason_gets_no_key_at_all(self):
        """The existing-plugins-untouched guarantee, at the unit level: a
        measurement whose compute() never mentions per_ticker_reason must
        not have run() invent the key."""
        result = NoReasonMeasurement().run(etf_id="SPY")

        self.assertNotIn("per_ticker_reason", result)


class OfficialMeasurementsUntouchedTests(unittest.TestCase):
    """The three shipped measurements must produce exactly the response
    they did before this issue - no per_ticker_reason key, present or
    empty."""

    def test_correlation_etf_weight_value_held_never_mention_a_reason(self):
        """A source-level guarantee: none of the three was touched to
        start naming its own nulls - out of scope for this issue, and
        exactly what would break "byte-identical responses to before"."""
        by_id = {m.id: m for m in ALL_MEASUREMENTS}
        for measurement_id in ("correlation", "etf_weight", "value_held"):
            source = inspect.getsource(type(by_id[measurement_id]))
            self.assertNotIn(
                "per_ticker_reason", source,
                f"{measurement_id}.py now mentions per_ticker_reason",
            )

    def test_etf_weight_route_response_has_no_reason_key(self):
        """A behavioural check alongside the source one: the live route,
        exercised end to end, must not carry the key at all."""
        holdings = [["AAPL", 60.0], ["MSFT", 40.0]]
        with patch("measurements.official_measurements.etf_weight.get_holdings",
                   return_value=holdings):
            resp = client.get("/api/measurements/etf-weight/SPY")

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("per_ticker_reason", resp.json())


class BuildExampleReasonTests(unittest.TestCase):
    FAKE_HOLDINGS = [["NEW", 5.0], ["OLD", 4.0]]
    FAKE_TICKERS = ["NEW", "OLD"]

    def _build(self):
        measurement = ReasonMeasurement()
        with patch("measurements.examples.get_holdings", return_value=self.FAKE_HOLDINGS), \
             patch("measurements.inputs.holdings.get_holdings", return_value=self.FAKE_HOLDINGS):
            return build_example(measurement, {})

    def test_a_null_with_a_reason_is_not_dropped_from_the_sample(self):
        """Before issue #99, a ticker with no computed value was always
        excluded from the worked example - "a row of blanks illustrates
        nothing". A null the measurement can explain is exactly what a
        doc page should be able to show instead of hiding."""
        payload = self._build()

        self.assertIn("NEW", payload["tickers"])

    def test_the_sampled_reason_matches_the_live_one(self):
        payload = self._build()

        self.assertEqual(
            payload["per_ticker_reason"]["NEW"],
            "computed over 40 days of history - fewer than the 252 this "
            "measurement needs",
        )

    def test_a_measurement_with_no_reasons_omits_the_key(self):
        measurement = NoReasonMeasurement()
        holdings = [["AAPL", 5.0], ["MISSING", 4.0]]
        with patch("measurements.examples.get_holdings", return_value=holdings), \
             patch("measurements.inputs.holdings.get_holdings", return_value=holdings):
            payload = build_example(measurement, {})

        self.assertNotIn("per_ticker_reason", payload)


if __name__ == "__main__":
    unittest.main()
