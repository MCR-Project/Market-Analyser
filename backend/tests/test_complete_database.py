"""
Unit tests for prune_below_threshold in scripts/complete_database.py
(issue #14) - the most damaging read in the whole codebase to leave
unpaginated: it computes each tracked ticker's maximum weight across every
ETF that holds it from a single etf_holdings read, then deletes tickers
(and their entire price history) whose max weight never clears the
threshold. PostgREST caps a single response at 1000 rows by default with no
error, so a ticker whose only heavily-weighted etf_holdings row sorts past
row 1000 - while an earlier, underweight row for the same ticker sits
inside the first page - would previously look underweight overall and get
pruned by mistake. prune_below_threshold now reads via paginated_select,
which must see every row before deciding.

Run with:   python -m unittest discover -s tests   (from backend/)
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.complete_database import prune_below_threshold
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


if __name__ == "__main__":
    unittest.main()
