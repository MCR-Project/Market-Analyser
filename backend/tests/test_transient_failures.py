"""
Unit tests for the transient-vs-permanent failure split (cold-start wedge).

A cold start makes the backend answer requests before Yahoo or Supabase
will answer *it*, and the two possible outcomes of a live fetch need
opposite handling at the edge. An empty answer is a fact about the ticker
- cacheable, and a 404. A failed fetch is a fact about right now - it must
not be cached, and it has to reach the frontend as a 503, because
useFetch deliberately never auto-retries a 4xx. Collapsing the two (a
blanket `except Exception: return []`, or an unguarded yfinance call
crashing out as a 500) is what left the dashboard parked on an error panel
until someone reloaded the page by hand.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yfinance.exceptions import YFDataException, YFRateLimitError

from services.cache import TTLCache
from services.market_data import (
    DataUnavailable,
    _get_etf_holdings_live,
    _get_etf_info_db,
    get_etf_holdings,
    get_etf_info,
)


def _ticker_whose_holdings_raise(exc):
    """A yf.Ticker stand-in where reading .funds_data.top_holdings raises."""
    funds = MagicMock()
    type(funds).top_holdings = PropertyMock(side_effect=exc)
    ticker = MagicMock()
    ticker.funds_data = funds
    return ticker


class EtfHoldingsLiveTests(unittest.TestCase):
    def test_not_a_fund_is_an_empty_answer(self):
        """Yahoo raising YFDataException for a plain stock is a real
        answer - it has no holdings - so [] is correct and the caller is
        free to cache it."""
        ticker = _ticker_whose_holdings_raise(YFDataException("AAPL: No Fund data found."))
        with patch("services.market_data.yf.Ticker", return_value=ticker):
            self.assertEqual(_get_etf_holdings_live("AAPL"), [])

    def test_unreachable_upstream_propagates(self):
        """A connection failure is not an answer. It must escape rather
        than be flattened into [] - that flattening is what let one
        cold-start blip get cached as "SPY has no holdings" for the whole
        fallback TTL, 404-ing every endpoint built on holdings."""
        ticker = _ticker_whose_holdings_raise(ConnectionError("connection refused"))
        with patch("services.market_data.yf.Ticker", return_value=ticker):
            with self.assertRaises(ConnectionError):
                _get_etf_holdings_live("SPY")

    def test_rate_limiting_propagates(self):
        """YFRateLimitError is a YFException like the not-a-fund one, but
        it means "ask again later", not "this isn't a fund" - so it must
        take the failure path, not the empty-answer path."""
        ticker = _ticker_whose_holdings_raise(YFRateLimitError())
        with patch("services.market_data.yf.Ticker", return_value=ticker):
            with self.assertRaises(YFRateLimitError):
                _get_etf_holdings_live("SPY")


class GetEtfHoldingsTransientTests(unittest.TestCase):
    def test_live_failure_raises_data_unavailable_and_is_not_cached(self):
        """DB miss plus a failing live fetch must surface as
        DataUnavailable (which the API answers 503 to) and leave the cache
        untouched, so the very next request retries instead of being
        pinned to a failure for the fallback TTL."""
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._get_etf_holdings_db", return_value=None), \
             patch("services.market_data._get_etf_holdings_live",
                   side_effect=ConnectionError("connection refused")) as mock_live:
            with self.assertRaises(DataUnavailable):
                get_etf_holdings("SPY")
            with self.assertRaises(DataUnavailable):
                get_etf_holdings("SPY")

        self.assertEqual(mock_live.call_count, 2)


class GetEtfInfoTransientTests(unittest.TestCase):
    def test_live_failure_raises_data_unavailable_and_is_not_cached(self):
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._get_etf_info_db", return_value=None), \
             patch("services.market_data._get_etf_info_live",
                   side_effect=ConnectionError("connection refused")) as mock_live:
            with self.assertRaises(DataUnavailable):
                get_etf_info("SPY")
            with self.assertRaises(DataUnavailable):
                get_etf_info("SPY")

        self.assertEqual(mock_live.call_count, 2)

    def test_db_row_survives_a_failed_aum_lookup(self):
        """AUM is the one live value on the DB path and nothing renders
        from it. A Yahoo hiccup must degrade it to 0, not throw away a row
        that already carries everything the dashboard shows - that
        unguarded call turned a healthy DB hit into a 500."""
        resp = MagicMock()
        resp.data = [{"id": "SPY", "name": "SPDR S&P 500 ETF Trust", "cat": "Large Blend", "desc": "d"}]
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = resp

        with patch("services.market_data.get_client_optional", return_value=db), \
             patch("services.market_data.yf.Ticker", side_effect=ConnectionError("connection refused")):
            result = _get_etf_info_db("SPY")

        self.assertEqual(result["name"], "SPDR S&P 500 ETF Trust")
        self.assertEqual(result["aum"], 0)


if __name__ == "__main__":
    unittest.main()
