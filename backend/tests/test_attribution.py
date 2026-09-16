"""
Tests for plugin attribution (issue #114): who wrote a measurement or a
portfolio metric, where to read more about them, what version it is, and
which metrics that plugin provides.

Stand-in plugins carry the whole suite rather than the real official
ones, the same convention test_measurement_docs.py and
test_measurement_columns.py already follow, so these tests do not depend
on whether any real plugin happens to declare an author at a given
moment. `FakeMeasurement`/`TwoColumnFake` mirror the shapes those two
files already define; `FakeMetric` is their portfolio_metrics
counterpart.

The frontend half - AttributionCard actually rendering in the picker and
at the head of a doc page - is verified live in the browser rather than
here, the same way every other UI-only acceptance criterion in this app
is; what is pinned down here is that the backend hands the frontend
everything it needs to do that: resolved attribution on every manifest
row, grouped correctly for a multi-column plugin, with frontmatter
winning over the class and a typo still failing loudly.

Run with:   pytest   (from the repo root)
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from main import app
from measurements.base import MeasurementBase
from measurements.docs import DocError, parse_doc
from measurements.docs import resolve_attribution as resolve_measurement_attribution
from measurements.registry import _column_manifest_entries
from portfolio_metrics.base import RunMetric
from portfolio_metrics.docs import DocError as PortfolioMetricDocError
from portfolio_metrics.docs import resolve_attribution as resolve_metric_attribution
from portfolio_metrics.registry import _manifest as portfolio_metric_manifest

client = TestClient(app, raise_server_exceptions=False)


class FakeMeasurement(MeasurementBase):
    """A stand-in single-column plugin, undeclared attribution by
    default - the same "no author unless one is set" state every real
    official measurement is in today."""

    id = "attribution_fake"
    name = "Attribution Fake"
    description = "A stand-in used by the tests."
    route = "/measurements/attribution-fake/{etf_id}"
    origin = "official"
    column_key = "value"
    column_label = "VALUE"

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        return {}

    def compute(self, inputs: dict) -> dict:
        return {"per_ticker": {}}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        return "—"


class TwoColumnFake(MeasurementBase):
    """A two-column plugin (issue #100's own shape), for checking that
    attribution is resolved once per *plugin* and carried onto every
    column it provides, identically."""

    id = "attribution_two_col_fake"
    name = "Attribution Two Column Fake"
    description = "A stand-in used by the tests."
    route = "/measurements/attribution-two-col-fake/{etf_id}"
    origin = "official"
    author = "Jane Doe"
    version = "2.1"
    columns = [
        {
            "key": "up", "label": "UP", "width": 100,
            "default_enabled": True, "filterable": False, "filter_type": "none",
            "filter_options": [], "filter_min": 0, "filter_max": 1, "filter_step": 0.05,
            "sort_type": "numerical", "sort_order": [],
        },
        {
            "key": "down", "label": "DOWN", "width": 100,
            "default_enabled": False, "filterable": False, "filter_type": "none",
            "filter_options": [], "filter_min": 0, "filter_max": 1, "filter_step": 0.05,
            "sort_type": "numerical", "sort_order": [],
        },
    ]

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        return {}

    def compute(self, inputs: dict) -> dict:
        return {"per_ticker": {"up": {}, "down": {}}}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        return "—"


class FakeMetric(RunMetric):
    """A stand-in portfolio metric, undeclared attribution by default."""

    id = "attributionFake"
    name = "Attribution Fake"
    description = "A stand-in used by the tests."
    family = "portfolio"


def _doc_file(obj, contents):
    """Point `obj`'s `doc_path` at a real temp .mdx file for one block -
    works for a measurement or a portfolio metric, since both resolve
    `doc_path` from `inspect.getfile(type(self))` the same way."""

    class _Ctx:
        def __enter__(self):
            self.dir = tempfile.TemporaryDirectory()
            path = Path(self.dir.name) / "fake.mdx"
            path.write_text(contents, encoding="utf-8")
            self.patcher = patch.object(type(obj), "doc_path", path)
            self.patcher.start()
            return path

        def __exit__(self, *exc):
            self.patcher.stop()
            self.dir.cleanup()
            return False

    return _Ctx()


# ── Frontmatter parsing accepts the three new keys ───────────────────────────

class AttributionFrontmatterParsingTests(unittest.TestCase):
    def test_attribution_keys_are_kept(self):
        frontmatter, _ = parse_doc(
            "---\ntitle: T\nsummary: S\nauthor: Jane Doe\n"
            "author_url: https://example.com/jane\nversion: \"1.2\"\n---\nbody",
            "x.mdx",
        )

        self.assertEqual(frontmatter["author"], "Jane Doe")
        self.assertEqual(frontmatter["author_url"], "https://example.com/jane")
        self.assertEqual(frontmatter["version"], "1.2")

    def test_an_unquoted_version_that_parses_as_a_number_is_rejected(self):
        """version: 1.2 (no quotes) arrives as a YAML float, not text -
        the same rule that already applies to example_etf, now exercised
        by the field most likely to be written unquoted by habit."""
        with self.assertRaises(DocError) as caught:
            parse_doc("---\ntitle: T\nsummary: S\nversion: 1.2\n---\nbody", "n.mdx")

        self.assertIn("version", str(caught.exception))

    def test_a_typo_in_an_attribution_key_still_fails_loudly(self):
        with self.assertRaises(DocError) as caught:
            parse_doc(
                "---\ntitle: T\nsummary: S\nauthr: Jane Doe\n---\nbody",
                "typo.mdx",
            )

        message = str(caught.exception)
        self.assertIn("typo.mdx", message)
        self.assertIn("authr", message)


# ── Resolution precedence: frontmatter > class > unattributed ────────────────

class MeasurementAttributionResolutionTests(unittest.TestCase):
    def setUp(self):
        self.measurement = FakeMeasurement()

    def tearDown(self):
        type(self.measurement).author = ""
        type(self.measurement).author_url = ""
        type(self.measurement).version = ""

    def test_an_unattributed_plugin_resolves_to_empty_strings(self):
        """Never defaults to the repository owner - the acceptance
        criterion, checked directly against the resolver itself."""
        resolved = resolve_measurement_attribution(self.measurement, {})

        self.assertEqual(resolved, {"author": "", "author_url": "", "version": ""})

    def test_the_class_attribute_is_used_when_no_frontmatter_says_otherwise(self):
        type(self.measurement).author = "Jane Doe"
        type(self.measurement).version = "1.0"

        resolved = resolve_measurement_attribution(self.measurement, {})

        self.assertEqual(resolved["author"], "Jane Doe")
        self.assertEqual(resolved["version"], "1.0")

    def test_frontmatter_overrides_the_class_attribute(self):
        """The doc is the more specific statement, the same reason
        example_etf's own frontmatter already wins over the class."""
        type(self.measurement).author = "Jane Doe"

        resolved = resolve_measurement_attribution(self.measurement, {"author": "John Smith"})

        self.assertEqual(resolved["author"], "John Smith")

    def test_frontmatter_overrides_the_class_attribute_end_to_end(self):
        """Same override, exercised through a real temp .mdx and
        load_doc rather than calling the resolver directly."""
        from measurements.docs import load_doc

        type(self.measurement).author = "Jane Doe"
        doc = "---\ntitle: T\nsummary: S\nauthor: John Smith\n---\nbody"
        with _doc_file(self.measurement, doc):
            payload = load_doc(self.measurement)

        self.assertEqual(payload["frontmatter"]["author"], "John Smith")


class PortfolioMetricAttributionResolutionTests(unittest.TestCase):
    def setUp(self):
        self.metric = FakeMetric()

    def tearDown(self):
        type(self.metric).author = ""
        type(self.metric).author_url = ""
        type(self.metric).version = ""

    def test_an_unattributed_metric_resolves_to_empty_strings(self):
        resolved = resolve_metric_attribution(self.metric, {})

        self.assertEqual(resolved, {"author": "", "author_url": "", "version": ""})

    def test_frontmatter_overrides_the_class_attribute(self):
        type(self.metric).author = "Jane Doe"

        resolved = resolve_metric_attribution(self.metric, {"author": "John Smith"})

        self.assertEqual(resolved["author"], "John Smith")


# ── Manifest exposure, grouped per plugin (issue #114's own to-do) ───────────

class MeasurementManifestAttributionTests(unittest.TestCase):
    def test_every_manifest_row_carries_the_three_fields(self):
        entries = _column_manifest_entries(FakeMeasurement())

        self.assertEqual(len(entries), 1)
        for key in ("author", "author_url", "version"):
            self.assertIn(key, entries[0])

    def test_a_two_column_plugin_is_described_once_with_both_columns_listed(self):
        """Attribution is resolved per *plugin*, not per column - both
        of this plugin's manifest rows must carry the identical answer,
        which is what lets the frontend group them under one card rather
        than showing the author twice with nothing to distinguish them."""
        entries = _column_manifest_entries(TwoColumnFake())

        self.assertEqual(len(entries), 2)
        self.assertEqual({e["column_key"] for e in entries}, {"up", "down"})
        self.assertTrue(all(e["author"] == "Jane Doe" for e in entries))
        self.assertTrue(all(e["version"] == "2.1" for e in entries))
        # Both rows still name the one plugin behind them - the same
        # thing the frontend groups columns under one card by.
        self.assertEqual(len({e["measurement_id"] for e in entries}), 1)

    def test_a_malformed_doc_falls_back_to_the_class_rather_than_500ing(self):
        """A broken .mdx belongs to that one plugin's own doc endpoint,
        not to the shared manifest every other plugin's picker depends
        on - _column_manifest_entries must not propagate the DocError."""
        measurement = FakeMeasurement()
        type(measurement).author = "Jane Doe"
        try:
            with patch(
                "measurements.registry.load_doc",
                side_effect=DocError("attribution_fake.mdx: broken"),
            ):
                entries = _column_manifest_entries(measurement)
        finally:
            type(measurement).author = ""

        self.assertEqual(entries[0]["author"], "Jane Doe")

    def test_the_live_manifest_endpoint_carries_attribution(self):
        resp = client.get("/api/measurements")

        self.assertEqual(resp.status_code, 200)
        for row in resp.json():
            for key in ("author", "author_url", "version"):
                self.assertIn(key, row)


class PortfolioMetricManifestAttributionTests(unittest.TestCase):
    def test_every_manifest_row_carries_the_three_fields(self):
        entry = portfolio_metric_manifest(FakeMetric())

        for key in ("author", "author_url", "version"):
            self.assertIn(key, entry)

    def test_a_malformed_doc_falls_back_to_the_class_rather_than_500ing(self):
        metric = FakeMetric()
        type(metric).author = "Jane Doe"
        try:
            with patch(
                "portfolio_metrics.registry.load_doc",
                side_effect=PortfolioMetricDocError("attributionFake.mdx: broken"),
            ):
                entry = portfolio_metric_manifest(metric)
        finally:
            type(metric).author = ""

        self.assertEqual(entry["author"], "Jane Doe")

    def test_the_live_manifest_endpoint_carries_attribution(self):
        resp = client.get("/api/portfolio-metrics")

        self.assertEqual(resp.status_code, 200)
        for row in resp.json()["metrics"]:
            for key in ("author", "author_url", "version"):
                self.assertIn(key, row)


if __name__ == "__main__":
    unittest.main()
