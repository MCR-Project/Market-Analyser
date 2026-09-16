"""
Tests for measurements/cost.py - a metric's derived cost rating
(issue #115).

Real official measurements carry most of this file, exercising the
actual, already-declared cost characteristics on measurements/inputs/*
rather than fabricated stand-ins: `etf_weight`/`value_held` are the
cheap, per-request, no-window case; `correlation` is the pairwise case
the acceptance criterion asks to rate heavier; `volatility` is the
window-aware case used to show widening the shared window raises a
rating. A couple of small stand-in plugins fill in the one shape no real
measurement conveniently isolates on its own (a lookup versus a pairwise
input, holding scaling and network cost equal).

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from measurements import ALL_MEASUREMENTS
from measurements.base import MeasurementBase
from measurements.cost import RATING_THRESHOLDS, rate
from measurements.inputs import INPUT_REGISTRY
from measurements.official_measurements.correlation import CorrelationMeasurement
from measurements.official_measurements.etf_weight import EtfWeightMeasurement
from measurements.official_measurements.value_held import ValueHeldMeasurement
from measurements.official_measurements.volatility import VolatilityMeasurement
from measurements.registry import _column_manifest_entries

MEASUREMENTS_DIR = Path(__file__).resolve().parent.parent / "measurements"


class LookupMeasurement(MeasurementBase):
    """A stand-in touching only the cheapest, per-request input this
    package has - the lookup half of the "pairwise rates heavier than a
    lookup" comparison."""

    id = "cost_lookup_fake"
    name = "Cost Lookup Fake"
    description = "A stand-in used by the tests."
    route = "/measurements/cost-lookup-fake/{etf_id}"
    origin = "official"
    uses_inputs = ["holdings"]
    column_key = "value"
    column_label = "VALUE"

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        return {}

    def compute(self, inputs: dict) -> dict:
        return {"per_ticker": {}}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        return "—"


class PairwiseMeasurement(LookupMeasurement):
    """The same stand-in, plus the one genuinely pairwise input this
    package declares."""

    id = "cost_pairwise_fake"
    route = "/measurements/cost-pairwise-fake/{etf_id}"
    uses_inputs = ["holdings", "correlation_matrix"]


class UnknownInputMeasurement(LookupMeasurement):
    """Names an input INPUT_REGISTRY has never heard of - the same stale-
    name case examples.py's own _sample_inputs degrades on rather than
    raising for."""

    id = "cost_unknown_input_fake"
    route = "/measurements/cost-unknown-input-fake/{etf_id}"
    uses_inputs = ["not_a_real_input"]


# ── The scoring model itself ──────────────────────────────────────────────────

class RealMeasurementRatingTests(unittest.TestCase):
    """The three existing columns (issue #115's own to-do), read
    straight off the real registry rather than a copy of them."""

    def test_weight_derived_columns_are_the_cheapest_tier(self):
        etf_weight = rate(EtfWeightMeasurement())
        value_held = rate(ValueHeldMeasurement())

        self.assertEqual(etf_weight["rating"], "Short")
        self.assertEqual(value_held["rating"], "Short")

    def test_correlation_rates_heavier_than_either_weight_column(self):
        correlation = rate(CorrelationMeasurement())
        etf_weight = rate(EtfWeightMeasurement())
        value_held = rate(ValueHeldMeasurement())

        self.assertGreater(correlation["score"], etf_weight["score"])
        self.assertGreater(correlation["score"], value_held["score"])
        self.assertNotEqual(correlation["rating"], "Short")


class SyntheticScalingTests(unittest.TestCase):
    def test_a_pairwise_metric_rates_heavier_than_a_lookup_metric(self):
        """Same base plugin, same everything else - the one difference
        is correlation_matrix's own declared "pairwise" scaling, which
        must be reflected in the score without either stand-in declaring
        a rating of its own."""
        lookup = rate(LookupMeasurement())
        pairwise = rate(PairwiseMeasurement())

        self.assertGreater(pairwise["score"], lookup["score"])

    def test_an_unknown_input_name_is_skipped_not_raised(self):
        result = rate(UnknownInputMeasurement())

        self.assertEqual(result, {"score": 0, "rating": "Short"})


class WindowRaisesRatingTests(unittest.TestCase):
    """Widening the shared window can raise a rating, visibly (issue
    #115's own acceptance criterion) - checked against the real,
    shipped VolatilityMeasurement rather than a stand-in, since this is
    exactly the plugin a reader would widen the window on in the app."""

    def test_widening_the_window_raises_volatilitys_score(self):
        narrow = rate(VolatilityMeasurement(), window="3mo")
        wide = rate(VolatilityMeasurement(), window="max")

        self.assertGreater(wide["score"], narrow["score"])

    def test_widening_the_window_can_cross_a_rating_boundary(self):
        at_default = rate(VolatilityMeasurement(), window="1y")
        at_max = rate(VolatilityMeasurement(), window="max")

        self.assertEqual(at_default["rating"], "Medium")
        self.assertEqual(at_max["rating"], "Long")

    def test_no_window_argument_falls_back_to_the_plugins_own_default(self):
        implicit = rate(VolatilityMeasurement())
        explicit = rate(VolatilityMeasurement(), window=VolatilityMeasurement().window_default)

        self.assertEqual(implicit, explicit)

    def test_a_non_window_aware_plugin_still_prices_its_own_fixed_period(self):
        """correlation.py never declares window_options, but
        correlation_matrix still reads a real, bounded stretch of
        history (its own DEFAULT_PERIOD) every time it runs - the score
        must reflect that fixed cost rather than reading a windowed
        input with nothing supplied as free."""
        with_window_input = rate(CorrelationMeasurement())
        without_any_windowed_input = rate(EtfWeightMeasurement())

        self.assertGreater(with_window_input["score"], without_any_windowed_input["score"] + 6)


# ── The manifest carries the resolved rating (issue #115's own to-do) ────────

class ManifestCostTests(unittest.TestCase):
    def test_every_manifest_row_carries_a_cost(self):
        entries = _column_manifest_entries(CorrelationMeasurement())

        self.assertEqual(len(entries), 1)
        self.assertIn("cost", entries[0])
        self.assertIn("score", entries[0]["cost"])
        self.assertIn("rating", entries[0]["cost"])

    def test_the_manifest_rating_matches_rate_at_the_plugins_own_default(self):
        measurement = VolatilityMeasurement()
        entries = _column_manifest_entries(measurement)

        self.assertEqual(entries[0]["cost"], rate(measurement))


# ── No plugin hand-declares its own rating (the acceptance criterion) ────────

class NoHandWrittenRatingTests(unittest.TestCase):
    def test_no_official_or_addon_measurement_declares_a_rating_attribute(self):
        for measurement in ALL_MEASUREMENTS:
            with self.subTest(id=measurement.id):
                self.assertFalse(hasattr(type(measurement), "rating"))
                self.assertFalse(hasattr(type(measurement), "cost_rating"))

    def test_no_plugin_source_file_hand_writes_a_rating(self):
        """The acceptance criterion, checked the way it is stated:
        grepping the plugin source for a hand-set rating. Scoped to the
        plugin directories themselves - measurements/cost.py and
        measurements/inputs/*.py's own INPUT_SPEC declarations are the
        one legitimate, documented place a cost characteristic (not a
        rating) is declared at all."""
        plugin_dirs = [
            MEASUREMENTS_DIR / "official_measurements",
            MEASUREMENTS_DIR / "addon_measurements",
        ]
        offenders = []
        for directory in plugin_dirs:
            for path in directory.glob("*.py"):
                text = path.read_text(encoding="utf-8")
                if "cost_rating" in text or "rating =" in text or '"rating"' in text:
                    offenders.append(str(path))
        self.assertEqual(offenders, [])


class RatingThresholdsTests(unittest.TestCase):
    def test_thresholds_are_sorted_highest_first_and_bottom_out_at_zero(self):
        scores = [threshold for threshold, _ in RATING_THRESHOLDS]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(scores[-1], 0)

    def test_every_input_in_the_registry_declares_a_cost(self):
        """The other half of "derived, never hand-declared": a getter
        with no cost characteristic at all would silently score as
        free (issue #115's own to-do: extend every INPUT_SPEC)."""
        for name, spec in INPUT_REGISTRY.items():
            with self.subTest(input=name):
                cost = spec.get("cost")
                self.assertIsNotNone(cost, f"{name} has no cost characteristic")
                self.assertIn(cost.get("scaling"), ("per_request", "per_holding", "pairwise"))
                self.assertIn(cost.get("network"), ("db", "live"))
                self.assertIn(cost.get("windowed"), (True, False))


if __name__ == "__main__":
    unittest.main()
