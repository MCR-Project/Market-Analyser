"""
Unit tests for the pagination helpers added to services/supabase_client.py
(issue #14): PostgREST caps a single response at 1000 rows by default and
returns the truncated page with no error, so a plain .select().execute()
over a table that grows past the cap silently acts on partial data.
paginated_select is meant to close that gap by looping .range() calls until
a short page comes back; these tests lock in its core loop (multi-page
accumulation, the short-page stop condition, and the fresh-builder-per-page
requirement its own docstring calls out) plus assert_not_truncated's guard.

Run with:   python -m unittest discover -s tests   (from backend/)
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.supabase_client import assert_not_truncated, paginated_select


class _FakeRangeQuery:
    """Stands in for a Supabase/postgrest query builder that only needs to
    support .range(start, end).execute() to drive paginated_select without a
    real DB. Each instance is meant to serve exactly one page - mirroring
    the fresh-builder-per-page contract paginated_select's docstring
    requires, since postgrest-py's .range() *adds* offset/limit params
    rather than replacing them, so a builder reused across pages would
    accumulate stale params instead of advancing the window."""

    def __init__(self, data):
        self._data = data
        self.range_calls: list[tuple[int, int]] = []

    def range(self, start, end):
        self.range_calls.append((start, end))
        return self

    def execute(self):
        start, end = self.range_calls[-1]
        return SimpleNamespace(data=self._data[start:end + 1])


class PaginatedSelectTests(unittest.TestCase):
    def test_single_short_page_needs_no_further_requests(self):
        data = [{"id": i} for i in range(3)]
        builders = []

        def build_query():
            b = _FakeRangeQuery(data)
            builders.append(b)
            return b

        rows = paginated_select(build_query, page_size=10)

        self.assertEqual(rows, data)
        self.assertEqual(len(builders), 1)
        self.assertEqual(builders[0].range_calls, [(0, 9)])

    def test_concatenates_full_page_then_short_page(self):
        """The exact shape the review asked for: a full page (equal to
        page_size, so the loop must keep going) followed by a short page
        (below page_size, so the loop must stop) - result is every row, in
        order, with nothing dropped or duplicated at the page boundary."""
        data = [{"id": i} for i in range(3)]
        builders = []

        def build_query():
            b = _FakeRangeQuery(data)
            builders.append(b)
            return b

        rows = paginated_select(build_query, page_size=2)

        self.assertEqual(rows, data)
        self.assertEqual(len(builders), 2)
        self.assertEqual(builders[0].range_calls, [(0, 1)])
        self.assertEqual(builders[1].range_calls, [(2, 3)])

    def test_multi_page_accumulation_across_several_full_pages(self):
        """Two full pages before the final short one - guards against an
        off-by-one that only happens to work for a single full page."""
        data = [{"id": i} for i in range(5)]

        def build_query():
            return _FakeRangeQuery(data)

        rows = paginated_select(build_query, page_size=2)

        self.assertEqual(rows, data)

    def test_exact_multiple_of_page_size_terminates(self):
        """When the total row count is an exact multiple of page_size, the
        last real page is itself full - the loop must issue one more
        (empty) request to observe the short page and stop, rather than
        looping forever or mistaking the full last page for truncation."""
        data = [{"id": i} for i in range(4)]

        def build_query():
            return _FakeRangeQuery(data)

        rows = paginated_select(build_query, page_size=2)

        self.assertEqual(rows, data)

    def test_calls_build_query_fresh_for_every_page(self):
        """paginated_select must call build_query() again for each page
        rather than reusing/re-ranging one builder - reusing a builder
        would accumulate offset/limit params instead of advancing them
        (see paginated_select's docstring)."""
        data = [{"id": i} for i in range(3)]
        builders = []

        def build_query():
            b = _FakeRangeQuery(data)
            builders.append(b)
            return b

        paginated_select(build_query, page_size=2)

        self.assertEqual(len(builders), 2)
        self.assertIsNot(builders[0], builders[1])
        # Each builder only ever sees ONE .range() call - proof the offsets
        # advance via a fresh builder per page, not by re-ranging one.
        self.assertEqual(len(builders[0].range_calls), 1)
        self.assertEqual(len(builders[1].range_calls), 1)


class AssertNotTruncatedTests(unittest.TestCase):
    def test_raises_when_row_count_equals_page_size(self):
        rows = [{"id": i} for i in range(1000)]
        with self.assertRaises(RuntimeError):
            assert_not_truncated(rows, page_size=1000)

    def test_passes_through_when_under_page_size(self):
        rows = [{"id": i} for i in range(5)]
        self.assertEqual(assert_not_truncated(rows, page_size=1000), rows)

    def test_passes_through_empty_result(self):
        self.assertEqual(assert_not_truncated([], page_size=1000), [])


if __name__ == "__main__":
    unittest.main()
