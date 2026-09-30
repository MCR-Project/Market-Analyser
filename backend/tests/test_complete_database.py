"""
Unit tests for scripts/complete_database.py.

The stage that used to be prune_below_threshold (issue #14's pagination
regression, now demotion under issue #168) is tested in
test_untracked_holdings.py, against a double that applies filters and writes.

normalize_symbol / normalize_holdings - decide what actually enters the
tracked universe from a provider's holdings file: non-US (Bloomberg-style)
listings are skipped so a foreign security never gets inserted under a US
ticker's identity, slash share classes are dotted to the repo's canonical
form, and known share-class aliases (DUPLICATE_TICKERS) are merged so e.g.
GOOG and GOOGL don't become two separate tracked tickers.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.complete_database import normalize_holdings, normalize_symbol


# ── normalize_symbol ─────────────────────────────────────────────────────────

class NormalizeSymbolTests(unittest.TestCase):
    def test_plain_us_ticker_passes_through(self):
        self.assertEqual(normalize_symbol("AAPL"), ("AAPL", None))

    def test_lowercase_and_surrounding_whitespace_are_normalized(self):
        self.assertEqual(normalize_symbol("  aapl  "), ("AAPL", None))

    def test_non_us_bloomberg_style_ticker_is_skipped(self):
        """A Bloomberg-style id with a space-separated exchange qualifier
        (e.g. "NPN SJ" - Naspers on the Johannesburg exchange) is a non-US
        listing yfinance won't resolve - skipped rather than risking it
        being inserted under a US ticker's identity."""
        canonical, reason = normalize_symbol("NPN SJ")
        self.assertIsNone(canonical)
        self.assertIn("non-US", reason)

    def test_slash_share_class_becomes_dot_form(self):
        self.assertEqual(normalize_symbol("BRK/B"), ("BRK.B", None))

    def test_known_duplicate_ticker_is_merged_to_its_canonical_form(self):
        """GOOG and BRK-B are both in DUPLICATE_TICKERS - normalize_symbol
        must resolve them to the same canonical id the rest of the
        pipeline (and the `ticker` table) uses, so they don't end up
        tracked as two separate tickers."""
        self.assertEqual(normalize_symbol("GOOG"), ("GOOGL", None))
        self.assertEqual(normalize_symbol("BRK-B"), ("BRK.B", None))

    def test_dot_form_alias_of_a_duplicate_is_also_merged(self):
        """BRK.B (dot form, post slash-to-dot normalization) must resolve
        the same way as the hyphen form BRK-B does."""
        self.assertEqual(normalize_symbol("BRK.B"), ("BRK.B", None))


# ── normalize_holdings ───────────────────────────────────────────────────────

class NormalizeHoldingsTests(unittest.TestCase):
    def test_holdings_are_normalized_and_weight_kept(self):
        holdings_by_etf = {
            "QQQ": {
                "holdings": [
                    {"ticker": "AAPL", "name": "Apple Inc", "weight_pct": 12.5},
                ]
            }
        }
        normalized, names = normalize_holdings(holdings_by_etf, ["QQQ"])
        self.assertEqual(normalized, {"QQQ": {"AAPL": 12.5}})
        self.assertEqual(names, {"AAPL": "Apple Inc"})

    def test_non_us_holding_is_skipped_and_excluded_from_names(self):
        holdings_by_etf = {
            "EFA": {
                "holdings": [
                    {"ticker": "NPN SJ", "name": "Naspers", "weight_pct": 3.0},
                    {"ticker": "AAPL", "name": "Apple Inc", "weight_pct": 5.0},
                ]
            }
        }
        normalized, names = normalize_holdings(holdings_by_etf, ["EFA"])
        self.assertEqual(normalized, {"EFA": {"AAPL": 5.0}})
        self.assertNotIn("NPN SJ", names)

    def test_duplicate_share_classes_are_merged_and_weights_summed(self):
        """A provider file listing both GOOG and GOOGL as separate holdings
        must collapse to one canonical entry with the combined weight, not
        two rows that would otherwise double-count the position."""
        holdings_by_etf = {
            "QQQ": {
                "holdings": [
                    {"ticker": "GOOG", "name": "Alphabet Inc Class C", "weight_pct": 2.0},
                    {"ticker": "GOOGL", "name": "Alphabet Inc Class A", "weight_pct": 2.5},
                ]
            }
        }
        normalized, names = normalize_holdings(holdings_by_etf, ["QQQ"])
        self.assertEqual(normalized, {"QQQ": {"GOOGL": 4.5}})
        # First-seen name wins for the merged canonical ticker.
        self.assertEqual(names["GOOGL"], "Alphabet Inc Class C")

    def test_missing_weight_does_not_crash_merge(self):
        """A holding with weight_pct=None merged with a weighted duplicate
        must keep the weighted value, not be blanked out by the missing one."""
        holdings_by_etf = {
            "QQQ": {
                "holdings": [
                    {"ticker": "GOOG", "name": "Alphabet Inc Class C", "weight_pct": None},
                    {"ticker": "GOOGL", "name": "Alphabet Inc Class A", "weight_pct": 2.5},
                ]
            }
        }
        normalized, _ = normalize_holdings(holdings_by_etf, ["QQQ"])
        self.assertEqual(normalized, {"QQQ": {"GOOGL": 2.5}})

    def test_each_etf_is_normalized_independently(self):
        holdings_by_etf = {
            "QQQ": {"holdings": [{"ticker": "AAPL", "name": "Apple Inc", "weight_pct": 10.0}]},
            "SPY": {"holdings": [{"ticker": "MSFT", "name": "Microsoft Corp", "weight_pct": 6.0}]},
        }
        normalized, names = normalize_holdings(holdings_by_etf, ["QQQ", "SPY"])
        self.assertEqual(normalized, {"QQQ": {"AAPL": 10.0}, "SPY": {"MSFT": 6.0}})
        self.assertEqual(names, {"AAPL": "Apple Inc", "MSFT": "Microsoft Corp"})


if __name__ == "__main__":
    unittest.main()
