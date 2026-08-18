"""
Unit tests for scripts/complete_database.py.

prune_below_threshold (issue #14) - the most damaging read in the whole
codebase to leave unpaginated: it computes each tracked ticker's maximum
weight across every ETF that holds it from a single etf_holdings read, then
deletes tickers (and their entire price history) whose max weight never
clears the threshold. PostgREST caps a single response at 1000 rows by
default with no error, so a ticker whose only heavily-weighted etf_holdings
row sorts past row 1000 - while an earlier, underweight row for the same
ticker sits inside the first page - would previously look underweight
overall and get pruned by mistake. prune_below_threshold now reads via
paginated_select, which must see every row before deciding.

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
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.complete_database import normalize_holdings, normalize_symbol, prune_below_threshold
from services.supabase_client import SUPABASE_PAGE_SIZE


class _FakeQuery:
    """Minimal stand-in for the Supabase fluent query builder - enough to
    drive prune_below_threshold's paginated_select(...).select(...).order(...)
    .order(...) chain, including .range() paging, without a real DB."""

    def __init__(self, data):
        self._data = data
        self._start = 0
        self._end = None

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        page = self._data[self._start:self._end + 1]
        return SimpleNamespace(data=page)


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def table(self, name):
        # A fresh query builder every call - paginated_select's build_query
        # calls client.table(...) again for each page, exactly like this.
        return _FakeQuery(self._tables.get(name, []))


class PruneBelowThresholdTests(unittest.TestCase):
    def test_nothing_to_prune_is_reported_as_such(self):
        client = _FakeClient({"etf_holdings": []})
        pruned, failed = prune_below_threshold(client, min_weight=1.0, dry_run=True)
        self.assertEqual(pruned, [])
        self.assertEqual(failed, [])

    def test_underweight_ticker_is_proposed_for_pruning(self):
        client = _FakeClient(
            {"etf_holdings": [{"ticker": "SMALL", "weight": 0.1}]}
        )
        pruned, failed = prune_below_threshold(client, min_weight=1.0, dry_run=True)
        self.assertEqual(pruned, ["SMALL"])
        self.assertEqual(failed, [])

    def test_truncation_past_the_page_cap_does_not_cause_a_false_prune(self):
        """Regression for issue #14's headline scenario. Build an
        etf_holdings result with more rows than PostgREST's page cap: an
        underweight row for HEAVY sits inside the first page, and its real,
        above-threshold weight only shows up on a row that sorts past the
        cap. A truncated (non-paginated) read would only ever see the
        underweight row and wrongly propose HEAVY for pruning - along with
        its entire price history. With pagination, both rows are read, the
        true max weight (5.0%) wins, and HEAVY must NOT be pruned.
        """
        page_size = SUPABASE_PAGE_SIZE
        rows = [{"ticker": f"FILL{i}", "weight": 0.05} for i in range(page_size - 1)]
        rows.append({"ticker": "HEAVY", "weight": 0.1})  # underweight row, inside page 1
        self.assertEqual(len(rows), page_size)
        rows.append({"ticker": "HEAVY", "weight": 5.0})  # true weight, past the cap

        client = _FakeClient({"etf_holdings": rows})
        pruned, failed = prune_below_threshold(client, min_weight=1.0, dry_run=True)

        self.assertNotIn("HEAVY", pruned)
        self.assertIn("FILL0", pruned)  # every filler ticker is genuinely underweight
        self.assertEqual(failed, [])

    def test_ticker_above_threshold_in_any_etf_is_kept(self):
        client = _FakeClient(
            {
                "etf_holdings": [
                    {"ticker": "MIXED", "weight": 0.2},
                    {"ticker": "MIXED", "weight": 3.5},
                ]
            }
        )
        pruned, failed = prune_below_threshold(client, min_weight=1.0, dry_run=True)
        self.assertNotIn("MIXED", pruned)


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
