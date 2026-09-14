"""
Tests for letting one measurement plugin declare several columns
(issue #100).

Two stand-in plugins carry the whole suite: `SingleColumnMeasurement`,
the `column_key` shorthand every measurement used before this issue, and
`TwoColumnMeasurement`, declaring `columns` directly. The point being
protected throughout is that the two declaration styles are
indistinguishable to `resolved_columns`, `run()` and the manifest builder
past the moment each one normalises them - and that the three real,
shipped measurements (all single-column) are unaffected by any of it.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from main import app
from measurements import ALL_MEASUREMENTS
from measurements.base import MeasurementBase
from measurements.registry import _column_manifest_entries

client = TestClient(app, raise_server_exceptions=False)


class SingleColumnMeasurement(MeasurementBase):
    """The `column_key` shorthand - what every measurement declared
    before issue #100, still fully supported."""

    id = "single_col_fake"
    name = "Single Column Fake"
    description = "A stand-in used by the tests."
    route = "/measurements/single-col-fake/{etf_id}"
    origin = "official"
    column_key = "value"
    column_label = "VALUE"
    column_width = 90
    default_enabled = True

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        return {}

    def compute(self, inputs: dict) -> dict:
        return {"per_ticker": {"AAPL": 1.0, "MSFT": None}}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        return "—" if value is None else f'<Stat text="{value}" />'


class TwoColumnMeasurement(MeasurementBase):
    """A single computation producing two columns - upside/downside
    capture is the motivating example in the issue itself."""

    id = "two_col_fake"
    name = "Two Column Fake"
    description = "A stand-in used by the tests."
    route = "/measurements/two-col-fake/{etf_id}"
    origin = "official"
    columns = [
        {
            "key": "up", "label": "UP CAPTURE", "width": 100,
            "default_enabled": True, "filterable": True, "filter_type": "range",
            "filter_options": [], "filter_min": 0, "filter_max": 2, "filter_step": 0.05,
            "sort_type": "numerical", "sort_order": [],
        },
        {
            "key": "down", "label": "DOWN CAPTURE", "width": 110,
            "default_enabled": False, "filterable": False, "filter_type": "none",
            "filter_options": [], "filter_min": 0, "filter_max": 2, "filter_step": 0.05,
            "sort_type": "numerical", "sort_order": [],
        },
    ]

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        # One fetch for both columns - the whole point of a plugin
        # declaring more than one (issue #100).
        return {"fetched": True}

    def compute(self, inputs: dict) -> dict:
        return {
            "per_ticker": {
                "up": {"AAPL": 1.1, "MSFT": None},
                "down": {"AAPL": 0.9, "MSFT": 0.8},
            },
            "per_ticker_reason": {
                "up": {"MSFT": "fewer than 30 overlapping daily returns (12 available)"},
            },
        }

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        return f'<Stat text="{column_key}:{value}" />'


class ResolvedColumnsTests(unittest.TestCase):
    def test_the_column_key_shorthand_normalises_to_a_list_of_one(self):
        columns = SingleColumnMeasurement().resolved_columns

        self.assertEqual(len(columns), 1)
        self.assertEqual(columns[0]["key"], "value")
        self.assertEqual(columns[0]["label"], "VALUE")
        self.assertEqual(columns[0]["width"], 90)
        self.assertTrue(columns[0]["default_enabled"])

    def test_a_declared_columns_list_is_returned_as_is(self):
        columns = TwoColumnMeasurement().resolved_columns

        self.assertEqual([c["key"] for c in columns], ["up", "down"])


class RunMultiColumnTests(unittest.TestCase):
    def setUp(self):
        self.measurement = TwoColumnMeasurement()

    def test_per_ticker_is_nested_by_column_key(self):
        result = self.measurement.run(etf_id="SPY")

        self.assertEqual(result["per_ticker"]["up"]["AAPL"], 1.1)
        self.assertEqual(result["per_ticker"]["down"]["AAPL"], 0.9)

    def test_render_cell_is_told_which_column_it_is_rendering(self):
        result = self.measurement.run(etf_id="SPY")

        self.assertIn("up:1.1", result["per_ticker_mdx"]["up"]["AAPL"])
        self.assertIn("down:0.9", result["per_ticker_mdx"]["down"]["AAPL"])

    def test_a_null_in_one_column_does_not_affect_its_sibling(self):
        result = self.measurement.run(etf_id="SPY")

        self.assertEqual(result["per_ticker_mdx"]["up"]["MSFT"], "—")
        self.assertNotEqual(result["per_ticker_mdx"]["down"]["MSFT"], "—")

    def test_a_reason_is_scoped_to_its_own_column(self):
        """`down` has no reasons of its own - MSFT's real 0.8 there must
        not inherit `up`'s explanation for the same ticker."""
        result = self.measurement.run(etf_id="SPY")

        self.assertEqual(
            result["per_ticker_reason"]["up"]["MSFT"],
            "fewer than 30 overlapping daily returns (12 available)",
        )
        self.assertNotIn("down", result["per_ticker_reason"])

    def test_a_single_column_plugins_response_is_unaffected(self):
        """The other half of the same guarantee: a plugin that never
        declared `columns` still gets the flat shape it always has."""
        result = SingleColumnMeasurement().run(etf_id="SPY")

        self.assertEqual(result["per_ticker"], {"AAPL": 1.0, "MSFT": None})
        self.assertEqual(result["per_ticker_mdx"]["MSFT"], "—")
        self.assertNotIn("per_ticker_reason", result)


class ManifestColumnEntriesTests(unittest.TestCase):
    def test_a_single_column_plugin_produces_one_entry_reusing_the_plugin_id(self):
        entries = _column_manifest_entries(SingleColumnMeasurement())

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "single_col_fake")
        self.assertEqual(entries[0]["measurement_id"], "single_col_fake")
        self.assertEqual(entries[0]["column_key"], "value")
        self.assertEqual(entries[0]["column_label"], "VALUE")

    def test_a_two_column_plugin_produces_two_namespaced_entries(self):
        entries = _column_manifest_entries(TwoColumnMeasurement())

        self.assertEqual(len(entries), 2)
        self.assertEqual({e["id"] for e in entries}, {"two_col_fake.up", "two_col_fake.down"})
        self.assertTrue(all(e["measurement_id"] == "two_col_fake" for e in entries))
        self.assertEqual({e["column_key"] for e in entries}, {"up", "down"})
        up = next(e for e in entries if e["column_key"] == "up")
        down = next(e for e in entries if e["column_key"] == "down")
        self.assertEqual(up["column_label"], "UP CAPTURE")
        self.assertEqual(down["column_label"], "DOWN CAPTURE")
        self.assertTrue(up["default_enabled"])
        self.assertFalse(down["default_enabled"])
        # Both columns still describe the one plugin behind them, e.g.
        # its route - a picker or a future doc page needs this to know
        # both columns are explained by the same .mdx.
        self.assertEqual(up["route"], down["route"])
        self.assertEqual(up["name"], down["name"])


class OfficialMeasurementsUnaffectedTests(unittest.TestCase):
    """The acceptance criterion, checked directly: the three shipped
    measurements' manifest rows are the ones they always were, plus only
    the one new field (`measurement_id`) this issue's own decisions
    require."""

    def test_each_official_measurement_still_produces_exactly_one_row(self):
        by_id = {m.id: m for m in ALL_MEASUREMENTS}
        for measurement_id in ("correlation", "etf_weight", "value_held"):
            measurement = by_id[measurement_id]
            entries = _column_manifest_entries(measurement)

            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry["id"], measurement_id)
            self.assertEqual(entry["measurement_id"], measurement_id)
            self.assertEqual(entry["column_key"], measurement.column_key)
            self.assertEqual(entry["column_label"], measurement.column_label)
            self.assertEqual(entry["column_width"], measurement.column_width)
            self.assertEqual(entry["default_enabled"], measurement.default_enabled)

    def test_the_live_manifest_endpoint_lists_each_by_its_old_id(self):
        resp = client.get("/api/measurements")

        self.assertEqual(resp.status_code, 200)
        by_id = {row["id"]: row for row in resp.json()}
        for measurement_id in ("correlation", "etf_weight", "value_held"):
            self.assertIn(measurement_id, by_id)
            self.assertEqual(by_id[measurement_id]["measurement_id"], measurement_id)


if __name__ == "__main__":
    unittest.main()
