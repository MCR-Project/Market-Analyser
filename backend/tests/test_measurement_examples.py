"""
Tests for the worked-example payload behind a measurement's doc page.

Three contracts.

**The computed values must be the real ones.** The example runs the
measurement over the whole fund and slices the result afterwards. Running
it over the five sampled holdings instead would be cheaper and wrong:
correlation's average ρ is an average over every peer, so a five-ticker
run would print numbers that contradict the table the reader is looking
at. `test_per_ticker_values_come_from_the_full_run` pins that down.

**Everything must be truncated.** fetch_inputs() legitimately returns an
NxN matrix and whole price histories. Nothing that large may reach the
page, and anything cut has to be flagged rather than silently implying
the sample is the whole picture.

**`uses_inputs` must name real getters.** It exists so a doc page can
explain where numbers came from; a stale name there would quietly drop a
section, so it fails the suite instead.

Run with:   pytest   (from the repo root)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from main import app
from measurements import ALL_MEASUREMENTS
from measurements.examples import (
    MAX_LIST_ITEMS,
    MAX_STRING_CHARS,
    MAX_TICKERS,
    build_example,
    truncate,
)
from measurements.inputs import INPUT_REGISTRY
from services.market_data import DataUnavailable

client = TestClient(app, raise_server_exceptions=False)

# A fund with more holdings than the example will ever show.
FAKE_HOLDINGS = [[f"T{i}", round(10 - i * 0.1, 2)] for i in range(20)]
FAKE_TICKERS = [row[0] for row in FAKE_HOLDINGS]


def _stub_holdings():
    """Stub every seam that reaches ETF holdings.

    There are three: examples.py's own import, the holdings input spec's
    sampler, and the measurement's own fetch_inputs. Missing one lets a
    test quietly hit the real data source and compare fake tickers against
    live ones.
    """
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        with patch("measurements.examples.get_holdings", return_value=FAKE_HOLDINGS), \
             patch("measurements.inputs.holdings.get_holdings", return_value=FAKE_HOLDINGS), \
             patch("measurements.official_measurements.etf_weight.get_holdings",
                   return_value=FAKE_HOLDINGS):
            yield

    return _ctx()


class UsesInputsTests(unittest.TestCase):
    def test_every_declared_input_exists_in_the_registry(self):
        for measurement in ALL_MEASUREMENTS:
            for name in measurement.uses_inputs:
                self.assertIn(
                    name, INPUT_REGISTRY,
                    f"{measurement.id} declares unknown input {name!r}",
                )

    def test_official_measurements_declare_their_inputs(self):
        by_id = {m.id: m for m in ALL_MEASUREMENTS}

        self.assertEqual(by_id["correlation"].uses_inputs,
                         ["holdings", "correlation_matrix"])
        self.assertEqual(by_id["etf_weight"].uses_inputs, ["holdings"])
        self.assertEqual(by_id["value_held"].uses_inputs, ["holdings", "etf_info"])

    def test_every_registry_entry_is_self_describing(self):
        for name, spec in INPUT_REGISTRY.items():
            self.assertTrue(spec["description"].strip(), f"{name} has no description")
            self.assertIn("defaults", spec)
            self.assertTrue(callable(spec["sample"]))

    def test_correlation_matrix_reports_the_window_it_assumes(self):
        """The lookback is invisible everywhere else in the app, so the
        doc page is the only place a reader can learn it."""
        defaults = INPUT_REGISTRY["correlation_matrix"]["defaults"]

        self.assertEqual(defaults["period"], "1y")
        self.assertEqual(defaults["interval"], "1d")


class TruncateTests(unittest.TestCase):
    def test_ticker_keyed_dict_is_filtered_to_the_sample(self):
        value = {t: 1.0 for t in FAKE_TICKERS}

        out, dropped = truncate(value, ["T0", "T1"], FAKE_TICKERS)

        self.assertEqual(sorted(out), ["T0", "T1"])
        self.assertTrue(dropped)

    def test_nested_matrix_is_filtered_on_both_axes(self):
        matrix = {a: {b: 0.5 for b in FAKE_TICKERS} for a in FAKE_TICKERS}

        out, dropped = truncate(matrix, ["T0", "T1"], FAKE_TICKERS)

        self.assertEqual(sorted(out), ["T0", "T1"])
        self.assertEqual(sorted(out["T0"]), ["T0", "T1"])
        self.assertTrue(dropped)

    def test_ticker_weight_pairs_are_filtered_to_the_sample(self):
        out, dropped = truncate(FAKE_HOLDINGS, ["T0", "T3"], FAKE_TICKERS)

        self.assertEqual([row[0] for row in out], ["T0", "T3"])
        self.assertTrue(dropped)

    def test_a_record_with_fields_is_not_mistaken_for_an_index(self):
        """A dict whose keys are field names, not tickers, keeps them all."""
        info = {"name": "Fund", "aum": 1.0, "category": "Equity"}

        out, dropped = truncate(info, ["T0"], FAKE_TICKERS)

        self.assertEqual(out, info)
        self.assertFalse(dropped)

    def test_long_lists_are_capped(self):
        out, dropped = truncate(list(range(100)), ["T0"], FAKE_TICKERS)

        self.assertEqual(len(out), MAX_LIST_ITEMS)
        self.assertTrue(dropped)

    def test_long_strings_are_capped(self):
        out, dropped = truncate({"description": "x" * 5000}, ["T0"], FAKE_TICKERS)

        self.assertLessEqual(len(out["description"]), MAX_STRING_CHARS + 1)
        self.assertTrue(dropped)

    def test_filtered_structures_come_back_in_sample_order(self):
        """Every table in a worked example must list the same holdings in
        the same order, so a reader can follow one ticker straight down
        from the input to the computed value. The inputs arrive in weight
        order while the sample leads with the declared example stock, so
        without this they disagree — and value_held.mdx tells the reader
        the numbers should visibly multiply out."""
        sample = ["T3", "T0", "T1"]

        pairs, _ = truncate(FAKE_HOLDINGS, sample, FAKE_TICKERS)
        keyed, _ = truncate({t: 1.0 for t in FAKE_TICKERS}, sample, FAKE_TICKERS)
        names, _ = truncate(list(FAKE_TICKERS), sample, FAKE_TICKERS)

        self.assertEqual([row[0] for row in pairs], sample)
        self.assertEqual(list(keyed), sample)
        self.assertEqual(names, sample)

    def test_small_values_are_left_alone(self):
        value = {"strongest": {"pair": ["T0", "T1"], "rho": 0.9}}

        out, dropped = truncate(value, FAKE_TICKERS, FAKE_TICKERS)

        self.assertEqual(out, value)
        self.assertFalse(dropped)


class BuildExampleTests(unittest.TestCase):
    def setUp(self):
        by_id = {m.id: m for m in ALL_MEASUREMENTS}
        self.measurement = by_id["etf_weight"]

    def _build(self, frontmatter=None):
        # build_example reaches holdings through two seams — its own
        # import, and the holdings input spec's sampler — so both are
        # stubbed, and nothing here touches Yahoo or Supabase.
        with _stub_holdings(), \
             patch.object(self.measurement, "run", return_value={
                 "per_ticker": {t: 1.0 for t in FAKE_TICKERS},
                 "per_ticker_mdx": {t: "<Stat text=\"1.0%\" />" for t in FAKE_TICKERS},
             }):
            return build_example(self.measurement, frontmatter or {})

    def test_sample_is_capped_and_flagged(self):
        payload = self._build()

        self.assertEqual(len(payload["tickers"]), MAX_TICKERS)
        self.assertEqual(len(payload["per_ticker"]), MAX_TICKERS)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["total_tickers"], len(FAKE_TICKERS))

    def test_heaviest_holdings_lead_when_no_example_stock_is_held(self):
        payload = self._build()

        self.assertEqual(payload["tickers"], FAKE_TICKERS[:MAX_TICKERS])
        self.assertIsNone(payload["example_stock"])

    def test_declared_example_stock_is_listed_first(self):
        payload = self._build({"title": "T", "summary": "S", "example_stock": "T9"})

        self.assertEqual(payload["tickers"][0], "T9")
        self.assertEqual(payload["example_stock"], "T9")

    def test_frontmatter_chooses_the_example_etf(self):
        payload = self._build({"title": "T", "summary": "S", "example_etf": "SMH"})

        self.assertEqual(payload["etf_id"], "SMH")

    def test_per_ticker_values_come_from_the_full_run(self):
        """The measurement is run over the whole fund and sliced after —
        never re-run over the five sampled holdings, which would print
        numbers that disagree with the table."""
        seen = {}

        def fake_run(**params):
            seen.update(params)
            return {"per_ticker": {t: 0.5 for t in FAKE_TICKERS}, "per_ticker_mdx": {}}

        with _stub_holdings(), patch.object(self.measurement, "run", side_effect=fake_run):
            payload = build_example(self.measurement, {})

        self.assertEqual(seen, {"etf_id": payload["etf_id"]})
        self.assertEqual(payload["total_tickers"], len(FAKE_TICKERS))

    def test_inputs_are_sampled_over_the_whole_fund_then_sliced(self):
        """Regression: the sampler must see every holding, not the five
        the doc shows.

        Correlation's averages, hub and strongest pair are properties of
        the full set. Computing them over the sample produced an
        `averages` block that disagreed with `per_ticker` — two different
        numbers for the same quantity, side by side on one page.
        """
        seen = {}

        def spy_sample(etf_id, tickers):
            seen["tickers"] = list(tickers)
            return {t: 1.0 for t in tickers}

        spec = {"description": "d", "defaults": {}, "sample": spy_sample}
        with _stub_holdings(), \
             patch.dict("measurements.examples.INPUT_REGISTRY",
                        {"holdings": spec}, clear=False), \
             patch.object(self.measurement, "run", return_value={
                 "per_ticker": {t: 1.0 for t in FAKE_TICKERS}, "per_ticker_mdx": {}}):
            payload = build_example(self.measurement, {})

        self.assertEqual(seen["tickers"], FAKE_TICKERS)
        self.assertEqual(sorted(payload["inputs"][0]["sample"]),
                         sorted(payload["tickers"]))
        self.assertTrue(payload["inputs"][0]["truncated"])

    def test_sampled_correlation_averages_match_the_computed_values(self):
        """The same quantity must not appear twice with two values."""
        averages = {t: round(0.1 * i, 4) for i, t in enumerate(FAKE_TICKERS)}
        spec = {
            "description": "d",
            "defaults": {},
            "sample": lambda etf_id, tickers: {
                "averages": dict(averages),
                "hub": {"ticker": FAKE_TICKERS[-1], "avgCorr": 0.9},
            },
        }

        with _stub_holdings(), \
             patch.dict("measurements.examples.INPUT_REGISTRY",
                        {"holdings": spec}, clear=False), \
             patch.object(self.measurement, "run", return_value={
                 "per_ticker": dict(averages), "per_ticker_mdx": {}}):
            payload = build_example(self.measurement, {})

        sampled = payload["inputs"][0]["sample"]["averages"]
        for ticker, value in payload["per_ticker"].items():
            self.assertEqual(sampled[ticker], value)
        # A fund-wide fact stays whole even when it names an unsampled
        # ticker — that is the point of computing it over everything.
        self.assertEqual(payload["inputs"][0]["sample"]["hub"]["ticker"],
                         FAKE_TICKERS[-1])

    def test_inputs_are_described_and_sampled(self):
        payload = self._build()

        names = [entry["name"] for entry in payload["inputs"]]
        self.assertEqual(names, ["holdings"])
        entry = payload["inputs"][0]
        self.assertTrue(entry["description"].strip())
        self.assertIn("defaults", entry)
        self.assertTrue(entry["truncated"])
        self.assertEqual([row[0] for row in entry["sample"]], payload["tickers"])


class ExampleEndpointTests(unittest.TestCase):
    def test_unknown_measurement_is_a_404(self):
        resp = client.get("/api/measurement-docs/nope/example")

        self.assertEqual(resp.status_code, 404)

    def test_upstream_failure_is_a_retryable_503(self):
        """A doc page opened during a Yahoo blip must heal itself, not
        show invented numbers or a permanent-looking error."""
        with patch("measurements.examples.get_holdings",
                   side_effect=DataUnavailable("holdings for 'SPY' is temporarily unavailable upstream")):
            resp = client.get("/api/measurement-docs/etf_weight/example")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.headers.get("Retry-After"), "3")

    def test_example_payload_shape(self):
        """Every holdings seam is stubbed, so this exercises the route
        end to end without touching Yahoo or Supabase."""
        with _stub_holdings():
            resp = client.get("/api/measurement-docs/etf_weight/example")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        for key in ("etf_id", "tickers", "inputs", "per_ticker",
                    "per_ticker_mdx", "truncated", "total_tickers"):
            self.assertIn(key, payload)
        self.assertLessEqual(len(payload["tickers"]), MAX_TICKERS)


if __name__ == "__main__":
    unittest.main()
