"""
Unit tests for services.market_data.list_etf_summaries (issue #20).

GET /api/etfs previously looped over every tracked ETF, calling
get_etf_info (one live yfinance call each, purely for AUM) and
get_etf_holdings (one Supabase query each) per ETF. list_etf_summaries
replaces that loop with exactly two Supabase queries total - one for
etfs metadata, one for etf_holdings - regardless of how many ETFs are
tracked, and never touches yfinance.

Run with:   python -m unittest discover -s tests   (from backend/)
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.market_data import list_etf_summaries


class _FakeQuery:
    """Minimal stand-in for the Supabase fluent query builder - enough to
    drive paginated_select's .select(...).order(...).range(...).execute()
    chain without a real DB."""

    def __init__(self, data):
        self._data = data
        self._start = 0
        self._end = None

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        page = self._data[self._start:self._end + 1]
        return SimpleNamespace(data=page)


class _FakeClient:
    def __init__(self, tables: dict):
        self._tables = tables
        self.table_calls = []

    def table(self, name):
        self.table_calls.append(name)
        return _FakeQuery(self._tables.get(name, []))


class ListEtfSummariesTests(unittest.TestCase):
    def test_returns_empty_list_when_supabase_unconfigured(self):
        with patch("services.market_data.get_client_optional", return_value=None):
            self.assertEqual(list_etf_summaries(), [])

    def test_joins_holding_counts_onto_etf_metadata(self):
        client = _FakeClient({
            "etfs": [
                {"id": "SPY", "name": "SPDR S&P 500", "cat": "Large Blend"},
                {"id": "QQQ", "name": "Invesco QQQ", "cat": "Large Growth"},
            ],
            "etf_holdings": [
                {"etf_id": "SPY", "ticker": "AAPL"},
                {"etf_id": "SPY", "ticker": "MSFT"},
                {"etf_id": "QQQ", "ticker": "AAPL"},
            ],
        })
        with patch("services.market_data.get_client_optional", return_value=client):
            result = list_etf_summaries()

        self.assertEqual(
            result,
            [
                {"id": "SPY", "name": "SPDR S&P 500", "cat": "Large Blend", "holdingCount": 2},
                {"id": "QQQ", "name": "Invesco QQQ", "cat": "Large Growth", "holdingCount": 1},
            ],
        )
        # No AUM field, and no growth in the number of tables touched
        # regardless of how many ETFs/holdings rows exist.
        self.assertNotIn("aum", result[0])
        self.assertEqual(sorted(set(client.table_calls)), ["etf_holdings", "etfs"])

    def test_etf_with_no_synced_holdings_gets_zero_count(self):
        client = _FakeClient({
            "etfs": [{"id": "NEW", "name": "New Fund", "cat": ""}],
            "etf_holdings": [],
        })
        with patch("services.market_data.get_client_optional", return_value=client):
            result = list_etf_summaries()

        self.assertEqual(result, [{"id": "NEW", "name": "New Fund", "cat": "", "holdingCount": 0}])

    def test_supabase_error_returns_empty_list(self):
        class _RaisingClient:
            def table(self, name):
                raise RuntimeError("boom")

        with patch("services.market_data.get_client_optional", return_value=_RaisingClient()):
            self.assertEqual(list_etf_summaries(), [])


if __name__ == "__main__":
    unittest.main()
