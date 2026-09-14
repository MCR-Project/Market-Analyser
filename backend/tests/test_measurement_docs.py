"""
Tests for the per-measurement documentation loader and its endpoint.

Two contracts are being pinned down here.

The first is the difference between "no doc" and "broken doc". Shipping a
measurement without an .mdx file is supported — an addon author should not
have to write prose to plug something in — so that answers 200 with
has_doc=false. A doc that exists but is malformed is the opposite case:
somebody hand-wrote it to be read, so it fails loudly, naming the file and
the offending key, rather than being silently dropped from the page.

The second is that frontmatter is validated strictly, including rejecting
keys nobody declared. A typo like `exemple_etf` would otherwise sit in a
doc doing nothing for as long as it takes someone to notice the worked
example is computed against the wrong fund.

Run with:   pytest   (from the repo root)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from config import DOCS_EXAMPLE_ETF, DOCS_EXAMPLE_STOCK
from main import app
from measurements import ALL_MEASUREMENTS
from measurements.base import MeasurementBase
from measurements.docs import DocError, load_doc, parse_doc

client = TestClient(app, raise_server_exceptions=False)


class FakeMeasurement(MeasurementBase):
    """A stand-in plugin, so these tests don't depend on the docs the
    official measurements happen to ship at any given moment."""

    id = "fake"
    name = "Fake Measurement"
    description = "A stand-in used by the tests."
    route = "/measurements/fake/{etf_id}"
    origin = "official"

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        return {}

    def compute(self, inputs: dict) -> dict:
        return {"per_ticker": {}}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        return "—"


VALID_DOC = """---
title: Correlation to Fund
summary: How closely a holding moves with the rest of the fund.
---

The body is *not* validated — it is free-form MDX.
"""


# ── Frontmatter parsing ──────────────────────────────────────────────────────

class ParseDocTests(unittest.TestCase):
    def test_splits_frontmatter_from_body(self):
        frontmatter, body = parse_doc(VALID_DOC, "correlation.mdx")

        self.assertEqual(frontmatter["title"], "Correlation to Fund")
        self.assertEqual(
            frontmatter["summary"],
            "How closely a holding moves with the rest of the fund.",
        )
        self.assertTrue(body.startswith("The body is *not* validated"))

    def test_optional_example_keys_are_kept(self):
        frontmatter, _ = parse_doc(
            "---\ntitle: T\nsummary: S\nexample_etf: SMH\nexample_stock: NVDA\n---\nbody",
            "x.mdx",
        )

        self.assertEqual(frontmatter["example_etf"], "SMH")
        self.assertEqual(frontmatter["example_stock"], "NVDA")

    def test_body_may_contain_its_own_horizontal_rules(self):
        """A `---` inside the prose must not be mistaken for the fence."""
        _, body = parse_doc(
            "---\ntitle: T\nsummary: S\n---\nabove\n\n---\n\nbelow",
            "x.mdx",
        )

        self.assertIn("above", body)
        self.assertIn("below", body)

    def test_missing_required_key_names_the_file_and_the_key(self):
        with self.assertRaises(DocError) as caught:
            parse_doc("---\ntitle: Only a title\n---\nbody", "correlation.mdx")

        message = str(caught.exception)
        self.assertIn("correlation.mdx", message)
        self.assertIn("summary", message)

    def test_unknown_key_is_rejected_rather_than_ignored(self):
        with self.assertRaises(DocError) as caught:
            parse_doc(
                "---\ntitle: T\nsummary: S\nexemple_etf: SMH\n---\nbody",
                "typo.mdx",
            )

        message = str(caught.exception)
        self.assertIn("typo.mdx", message)
        self.assertIn("exemple_etf", message)

    def test_absent_frontmatter_is_an_error(self):
        with self.assertRaises(DocError):
            parse_doc("Just a body, no metadata.\n", "bare.mdx")

    def test_unclosed_frontmatter_is_an_error(self):
        with self.assertRaises(DocError):
            parse_doc("---\ntitle: T\nsummary: S\n", "unclosed.mdx")

    def test_unparseable_yaml_is_an_error(self):
        with self.assertRaises(DocError):
            parse_doc("---\ntitle: [unclosed\n---\nbody", "broken.mdx")

    def test_non_text_value_is_an_error(self):
        """`example_etf: 2026-01-01` would arrive as a date object."""
        with self.assertRaises(DocError) as caught:
            parse_doc("---\ntitle: T\nsummary: S\nexample_etf: 12345\n---\nb", "n.mdx")

        self.assertIn("example_etf", str(caught.exception))


# ── Loading, including the no-doc fallback ───────────────────────────────────

class LoadDocTests(unittest.TestCase):
    def setUp(self):
        self.measurement = FakeMeasurement()

    def test_missing_doc_file_is_not_an_error(self):
        with patch.object(type(self.measurement), "doc_path",
                          Path("does-not-exist.mdx")):
            payload = load_doc(self.measurement)

        self.assertFalse(payload["has_doc"])
        self.assertIsNone(payload["mdx"])
        self.assertEqual(payload["frontmatter"]["title"], "Fake Measurement")
        self.assertEqual(payload["frontmatter"]["summary"],
                         "A stand-in used by the tests.")

    def test_existing_doc_is_parsed(self):
        with _doc_file(self, VALID_DOC):
            payload = load_doc(self.measurement)

        self.assertTrue(payload["has_doc"])
        self.assertEqual(payload["frontmatter"]["title"], "Correlation to Fund")
        self.assertIn("free-form MDX", payload["mdx"])

    def test_example_falls_back_to_the_config_default(self):
        with patch.object(type(self.measurement), "doc_path",
                          Path("does-not-exist.mdx")):
            payload = load_doc(self.measurement)

        self.assertEqual(payload["frontmatter"]["example_etf"], DOCS_EXAMPLE_ETF)
        self.assertEqual(payload["frontmatter"]["example_stock"], DOCS_EXAMPLE_STOCK)

    def test_class_attribute_overrides_the_config_default(self):
        self.measurement.example_etf = "SMH"
        try:
            with patch.object(type(self.measurement), "doc_path",
                              Path("does-not-exist.mdx")):
                payload = load_doc(self.measurement)
        finally:
            self.measurement.example_etf = ""

        self.assertEqual(payload["frontmatter"]["example_etf"], "SMH")

    def test_frontmatter_overrides_the_class_attribute(self):
        """The doc is the more specific statement about how to explain
        this measurement, so it wins over the class."""
        self.measurement.example_etf = "SMH"
        doc = "---\ntitle: T\nsummary: S\nexample_etf: XLK\n---\nbody"
        try:
            with _doc_file(self, doc):
                payload = load_doc(self.measurement)
        finally:
            self.measurement.example_etf = ""

        self.assertEqual(payload["frontmatter"]["example_etf"], "XLK")

    def test_malformed_doc_raises(self):
        with _doc_file(self, "---\ntitle: no summary here\n---\nbody"):
            with self.assertRaises(DocError):
                load_doc(self.measurement)


def _doc_file(test, contents):
    """Point the measurement at a real temp .mdx file for one block."""
    import tempfile

    class _Ctx:
        def __enter__(self):
            self.dir = tempfile.TemporaryDirectory()
            path = Path(self.dir.name) / "fake.mdx"
            path.write_text(contents, encoding="utf-8")
            self.patcher = patch.object(type(test.measurement), "doc_path", path)
            self.patcher.start()
            return path

        def __exit__(self, *exc):
            self.patcher.stop()
            self.dir.cleanup()
            return False

    return _Ctx()


# ── Manifest and endpoint ────────────────────────────────────────────────────

class ManifestOriginTests(unittest.TestCase):
    def test_official_measurements_are_tagged_official(self):
        resp = client.get("/api/measurements")

        self.assertEqual(resp.status_code, 200)
        by_id = {m["id"]: m for m in resp.json()}
        for measurement_id in ("correlation", "etf_weight", "value_held"):
            self.assertEqual(by_id[measurement_id]["origin"], "official")

    def test_every_registered_measurement_declares_an_origin(self):
        """An addon added to ADDON_MEASUREMENTS must come out as "addon"
        with no further wiring — that is what the barrel's tagging buys."""
        for measurement in ALL_MEASUREMENTS:
            self.assertIn(measurement.origin, ("official", "addon"))

    def test_addon_measurements_are_tagged_addon(self):
        from measurements import _tag_origin

        plugged_in = FakeMeasurement()
        _tag_origin([plugged_in], "addon")

        self.assertEqual(plugged_in.origin, "addon")
        self.assertEqual(plugged_in.manifest()["origin"], "addon")


class DocEndpointTests(unittest.TestCase):
    def test_unknown_measurement_is_a_404(self):
        resp = client.get("/api/measurement-docs/not-a-measurement")

        self.assertEqual(resp.status_code, 404)

    def test_known_measurement_without_a_doc_is_a_200(self):
        resp = client.get("/api/measurement-docs/correlation")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["id"], "correlation")
        self.assertEqual(payload["origin"], "official")
        self.assertIn("has_doc", payload)
        self.assertTrue(payload["frontmatter"]["title"])
        self.assertTrue(payload["frontmatter"]["example_etf"])

    def test_malformed_doc_surfaces_as_a_500_naming_the_file(self):
        with patch("measurements.registry.load_doc",
                   side_effect=DocError("correlation.mdx: frontmatter is missing "
                                        "required key 'summary'.")):
            resp = client.get("/api/measurement-docs/correlation")

        self.assertEqual(resp.status_code, 500)
        self.assertIn("correlation.mdx", resp.json()["detail"])

    def test_doc_route_is_not_shadowed_by_a_plugin_route(self):
        """The reason the endpoint is /measurement-docs/{id} and not
        /measurements/{id}/doc: the latter collides with the correlation
        plugin's own /measurements/correlation/{etf_id}."""
        resp = client.get("/api/measurement-docs/etf_weight")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], "etf_weight")


if __name__ == "__main__":
    unittest.main()
