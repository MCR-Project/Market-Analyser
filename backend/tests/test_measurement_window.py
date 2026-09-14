"""
Tests for letting a measurement declare a window it is computed over
(issue #101).

`WindowMeasurement` is a stand-in plugin whose `fetch_inputs` keeps its
own tiny per-window cache, the same shape a real window-aware plugin's
`fetch_inputs` is expected to (folding `window` into whatever cache key
its own reads use) - the tests below use that cache both to prove the
validated window actually reaches `fetch_inputs`, and that two different
windows never share one cached answer.

`NoWindowMeasurement` stands in for every official measurement today:
declares no window at all, and must be completely unaffected - no query
parameter generated for its route, no "window" key in its response, no
change in behaviour whether or not a caller sends `?window=`.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS
from main import app
from measurements import ALL_MEASUREMENTS
from measurements.base import MeasurementBase
from measurements.examples import build_example
from measurements.registry import _column_manifest_entries

client = TestClient(app, raise_server_exceptions=False)


class WindowMeasurement(MeasurementBase):
    """A stand-in plugin whose value genuinely depends on the window -
    computed as len(window) purely so two different windows are
    observably different answers, and cached per window the way a real
    plugin's own price read would be."""

    id = "window_fake"
    name = "Window Fake"
    description = "A stand-in used by the tests."
    route = "/measurements/window-fake/{etf_id}"
    origin = "official"
    column_key = "value"
    column_label = "VALUE"
    window_options = MEASUREMENT_WINDOW_OPTIONS
    window_default = MEASUREMENT_WINDOW_DEFAULT

    def __init__(self):
        self.fetch_calls = []
        self._cache = {}

    def fetch_inputs(self, etf_id: str, window: str, **_) -> dict:
        self.fetch_calls.append(window)
        cache_key = (etf_id, window)
        if cache_key not in self._cache:
            self._cache[cache_key] = {"window": window, "computed": len(window)}
        return self._cache[cache_key]

    def compute(self, inputs: dict) -> dict:
        return {"per_ticker": {"AAPL": inputs["computed"]}}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        return "—" if value is None else f'<Stat text="{value}" />'


class NoWindowMeasurement(MeasurementBase):
    """Every official measurement's shape today: no window at all."""

    id = "no_window_fake"
    name = "No Window Fake"
    description = "A stand-in used by the tests."
    route = "/measurements/no-window-fake/{etf_id}"
    origin = "official"
    column_key = "value"
    column_label = "VALUE"

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        return {}

    def compute(self, inputs: dict) -> dict:
        return {"per_ticker": {"AAPL": 1.0}}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        return "—" if value is None else f'<Stat text="{value}" />'


class RunWindowResolutionTests(unittest.TestCase):
    def setUp(self):
        self.measurement = WindowMeasurement()

    def test_a_recognised_window_is_passed_through_unchanged(self):
        self.measurement.run(etf_id="SPY", window="5y")

        self.assertEqual(self.measurement.fetch_calls, ["5y"])

    def test_an_unrecognised_window_falls_back_to_the_default(self):
        self.measurement.run(etf_id="SPY", window="17y")

        self.assertEqual(self.measurement.fetch_calls, [MEASUREMENT_WINDOW_DEFAULT])

    def test_a_missing_window_falls_back_to_the_default(self):
        """The worked example calls run() with no window at all - the same
        path a plugin with no `window` kwarg at all must not crash on."""
        self.measurement.run(etf_id="SPY")

        self.assertEqual(self.measurement.fetch_calls, [MEASUREMENT_WINDOW_DEFAULT])

    def test_the_resolved_window_is_echoed_back(self):
        result = self.measurement.run(etf_id="SPY", window="3mo")

        self.assertEqual(result["window"], "3mo")

    def test_two_different_windows_produce_two_different_answers(self):
        """Proves fetch_inputs' own per-window cache actually keys on the
        window - a plugin that forgot to would answer both windows with
        whichever one it computed first."""
        result_3mo = self.measurement.run(etf_id="SPY", window="3mo")
        result_5y = self.measurement.run(etf_id="SPY", window="5y")

        self.assertNotEqual(result_3mo["per_ticker"]["AAPL"], result_5y["per_ticker"]["AAPL"])
        self.assertEqual(result_3mo["per_ticker"]["AAPL"], len("3mo"))
        self.assertEqual(result_5y["per_ticker"]["AAPL"], len("5y"))

    def test_a_plugin_with_no_window_options_gets_no_window_key(self):
        result = NoWindowMeasurement().run(etf_id="SPY")

        self.assertNotIn("window", result)


class ManifestWindowFieldsTests(unittest.TestCase):
    def test_a_window_aware_plugin_advertises_its_options_and_default(self):
        entries = _column_manifest_entries(WindowMeasurement())

        self.assertEqual(entries[0]["window_options"], MEASUREMENT_WINDOW_OPTIONS)
        self.assertEqual(entries[0]["window_default"], MEASUREMENT_WINDOW_DEFAULT)

    def test_a_non_window_plugin_advertises_no_options(self):
        entries = _column_manifest_entries(NoWindowMeasurement())

        self.assertEqual(entries[0]["window_options"], [])
        self.assertEqual(entries[0]["window_default"], "")


class WindowLabelTests(unittest.TestCase):
    def test_a_recognised_value_returns_its_label(self):
        self.assertEqual(WindowMeasurement().window_label("1y"), "1Y")

    def test_an_unrecognised_value_returns_itself(self):
        self.assertEqual(WindowMeasurement().window_label("17y"), "17y")


class RouteWindowParameterTests(unittest.TestCase):
    """Exercises the actual generated FastAPI route, not just run()
    directly - this is what proves registry._make_handler generates the
    query parameter for the right plugins and no others."""

    def setUp(self):
        from measurements.registry import _make_handler

        # registry.py's own routes are mounted under measurement_router's
        # "/api" prefix (see main.py), so a route added straight to
        # app.router without repeating that prefix would 404 - it does
        # not inherit one just by living on the same app.
        self.window_measurement = WindowMeasurement()
        self.no_window_measurement = NoWindowMeasurement()
        self.window_path = f"/api{self.window_measurement.route}"
        self.no_window_path = f"/api{self.no_window_measurement.route}"
        app.router.add_api_route(
            self.window_path, _make_handler(self.window_measurement),
            methods=["GET"],
        )
        app.router.add_api_route(
            self.no_window_path, _make_handler(self.no_window_measurement),
            methods=["GET"],
        )

    def tearDown(self):
        # FastAPI has no public "unregister a route" - drop the ones this
        # test added directly from the router's own list so they cannot
        # leak into any test that runs after this one.
        keep = [
            r for r in app.router.routes
            if getattr(r, "path", None) not in (self.window_path, self.no_window_path)
        ]
        app.router.routes[:] = keep

    def test_a_recognised_window_reaches_the_measurement(self):
        resp = client.get("/api/measurements/window-fake/SPY", params={"window": "5y"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["window"], "5y")

    def test_an_invalid_window_falls_back_rather_than_erroring(self):
        resp = client.get("/api/measurements/window-fake/SPY", params={"window": "nonsense"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["window"], MEASUREMENT_WINDOW_DEFAULT)

    def test_no_window_at_all_uses_the_default(self):
        resp = client.get("/api/measurements/window-fake/SPY")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["window"], MEASUREMENT_WINDOW_DEFAULT)

    def test_a_non_window_plugin_ignores_a_window_query_param(self):
        """The acceptance criterion, at the HTTP layer: a plugin that
        declares no window behaves exactly as it does today, even when a
        caller sends one anyway."""
        resp = client.get("/api/measurements/no-window-fake/SPY", params={"window": "5y"})

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("window", resp.json())


class BuildExampleWindowTests(unittest.TestCase):
    def test_the_worked_example_states_its_window(self):
        measurement = WindowMeasurement()
        holdings = [["AAPL", 5.0]]
        from unittest.mock import patch

        with patch("measurements.examples.get_holdings", return_value=holdings), \
             patch("measurements.inputs.holdings.get_holdings", return_value=holdings):
            payload = build_example(measurement, {})

        self.assertEqual(payload["window"], MEASUREMENT_WINDOW_DEFAULT)
        self.assertEqual(payload["window_label"], measurement.window_label(MEASUREMENT_WINDOW_DEFAULT))

    def test_a_non_window_plugin_omits_the_key(self):
        measurement = NoWindowMeasurement()
        holdings = [["AAPL", 5.0]]
        from unittest.mock import patch

        with patch("measurements.examples.get_holdings", return_value=holdings), \
             patch("measurements.inputs.holdings.get_holdings", return_value=holdings):
            payload = build_example(measurement, {})

        self.assertNotIn("window", payload)


class OfficialMeasurementsUnaffectedTests(unittest.TestCase):
    def test_the_three_official_measurements_declare_no_window(self):
        by_id = {m.id: m for m in ALL_MEASUREMENTS}
        for measurement_id in ("correlation", "etf_weight", "value_held"):
            measurement = by_id[measurement_id]
            self.assertEqual(measurement.window_options, [])
            self.assertEqual(measurement.window_default, "")

    def test_their_live_responses_carry_no_window_key(self):
        from unittest.mock import patch

        holdings = [["AAPL", 60.0], ["MSFT", 40.0]]
        with patch("measurements.official_measurements.etf_weight.get_holdings",
                   return_value=holdings):
            resp = client.get("/api/measurements/etf-weight/SPY", params={"window": "5y"})

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("window", resp.json())


if __name__ == "__main__":
    unittest.main()
