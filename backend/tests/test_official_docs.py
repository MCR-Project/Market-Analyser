"""
Tests for the documentation shipped with the official measurements.

Two things are being protected.

**The docs stay loadable.** They are hand-written files parsed at request
time, so a typo in the frontmatter of one of them would only surface as a
500 on its own page — which nobody visits until they are already confused
about that column. These parse every shipped doc up front instead.

**The template stays copy-and-go.** DOC_TEMPLATE.mdx is what an addon
author starts from, and the whole point of it is that filling in the body
is the only work. If the template itself stopped satisfying the loader,
every new measurement would start from something broken.

Run with:   pytest   (from the repo root)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from main import app
from measurements import ALL_MEASUREMENTS
from measurements.docs import load_doc, parse_doc
from measurements.official_measurements import OFFICIAL_MEASUREMENTS

client = TestClient(app, raise_server_exceptions=False)

TEMPLATE = Path(__file__).resolve().parent.parent / "measurements" / "DOC_TEMPLATE.mdx"

# The convention the template sets and every official doc follows. Not
# enforced by the loader on purpose — a doc is prose, not a form — but the
# shipped ones should not drift apart from each other.
EXPECTED_SECTIONS = [
    "## What it measures",
    "## Where the numbers come from",
    "## How it is computed",
    "## Caveats",
]


class OfficialDocsTests(unittest.TestCase):
    def test_every_official_measurement_ships_a_doc(self):
        for measurement in OFFICIAL_MEASUREMENTS:
            self.assertTrue(
                measurement.has_doc,
                f"{measurement.id} has no .mdx next to its module",
            )

    def test_every_shipped_doc_parses(self):
        for measurement in ALL_MEASUREMENTS:
            if not measurement.has_doc:
                continue
            payload = load_doc(measurement)  # raises DocError on a bad file
            self.assertTrue(payload["frontmatter"]["title"].strip())
            self.assertTrue(payload["frontmatter"]["summary"].strip())
            self.assertTrue(payload["mdx"].strip())

    def test_docs_follow_the_shared_section_convention(self):
        for measurement in OFFICIAL_MEASUREMENTS:
            body = load_doc(measurement)["mdx"]
            for section in EXPECTED_SECTIONS:
                self.assertIn(
                    section, body,
                    f"{measurement.id}.mdx is missing the '{section}' section",
                )

    def test_docs_place_their_own_worked_example(self):
        """Each one puts it beside the formula rather than letting the page
        append it at the end, so the numbers sit next to the arithmetic."""
        for measurement in OFFICIAL_MEASUREMENTS:
            self.assertIn("<WorkedExample />", load_doc(measurement)["mdx"])

    def test_correlation_documents_the_fund_it_illustrates(self):
        doc = next(m for m in OFFICIAL_MEASUREMENTS if m.id == "correlation")

        self.assertEqual(load_doc(doc)["frontmatter"]["example_etf"], "SMH")

    def test_endpoint_serves_them(self):
        for measurement_id in ("correlation", "etf_weight", "value_held"):
            resp = client.get(f"/api/measurement-docs/{measurement_id}")

            self.assertEqual(resp.status_code, 200)
            payload = resp.json()
            self.assertTrue(payload["has_doc"], f"{measurement_id} served no doc")
            self.assertTrue(payload["mdx"])


class DocTemplateTests(unittest.TestCase):
    def test_template_exists_where_the_guides_point(self):
        self.assertTrue(TEMPLATE.is_file(), f"{TEMPLATE} is missing")

    def test_template_is_a_valid_doc_as_shipped(self):
        """Copying it to a new measurement must produce something the
        loader accepts, before a word of it is edited."""
        frontmatter, body = parse_doc(TEMPLATE.read_text(encoding="utf-8"), TEMPLATE.name)

        self.assertTrue(frontmatter["title"].strip())
        self.assertTrue(frontmatter["summary"].strip())
        self.assertTrue(body.strip())

    def test_template_shows_the_optional_keys_without_setting_them(self):
        """example_etf/example_stock are commented out — left live, every
        copied doc would silently point at the template's fund."""
        frontmatter, _ = parse_doc(TEMPLATE.read_text(encoding="utf-8"), TEMPLATE.name)

        self.assertNotIn("example_etf", frontmatter)
        self.assertNotIn("example_stock", frontmatter)
        self.assertIn("example_etf", TEMPLATE.read_text(encoding="utf-8"))

    def test_template_carries_the_section_convention(self):
        body = TEMPLATE.read_text(encoding="utf-8")
        for section in EXPECTED_SECTIONS:
            self.assertIn(section, body)


if __name__ == "__main__":
    unittest.main()
