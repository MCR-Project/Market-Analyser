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

from unittest.mock import patch

from yfinance.exceptions import YFDataException, YFRateLimitError

from services.cache import TTLCache
from services.market_data import (
    DataUnavailable,
    RATE_LIMIT_COOLDOWN_SECONDS,
    _RateLimitCooldown,
    _get_etf_holdings_live,
    _get_etf_info_db,
    _live,
    get_etf_holdings,
    get_etf_info,
)


class _UpstreamHTTPError(Exception):
    """A minimal stand-in for curl_cffi's HTTPError, carrying a status on
    an attached response - see test_symbol_not_found.py, which defines
    the same shape for the 404/500 side of this split. Duplicated rather
    than imported: every test file in this suite is standalone (backend/
    CLAUDE.md)."""

    def __init__(self, status_code):
        super().__init__(f"HTTP Error {status_code}")
        self.response = type("Response", (), {"status_code": status_code})()


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


class RateLimitCooldownClassTests(unittest.TestCase):
    """The cooldown as a standalone clock (issue #92) - no yfinance or
    _live() involved, just whether it starts, counts down, and expires
    on its own terms."""

    def test_inactive_until_started(self):
        self.assertFalse(_RateLimitCooldown(duration=60).active())

    def test_active_immediately_after_starting(self):
        cooldown = _RateLimitCooldown(duration=60)
        cooldown.start()
        self.assertTrue(cooldown.active())
        self.assertEqual(cooldown.remaining(), 60)

    def test_expires_once_its_duration_has_passed(self):
        cooldown = _RateLimitCooldown(duration=60)
        with patch("services.market_data.time.time", return_value=1_000.0):
            cooldown.start()
        with patch("services.market_data.time.time", return_value=1_000.0 + 61):
            self.assertFalse(cooldown.active())

    def test_remaining_counts_down_and_rounds_up(self):
        """Rounds up rather than down: a request told to wait 0.4s of a
        59.6s cooldown would be told the cooldown is basically over."""
        cooldown = _RateLimitCooldown(duration=60)
        with patch("services.market_data.time.time", return_value=1_000.0):
            cooldown.start()
        with patch("services.market_data.time.time", return_value=1_000.0 + 59.4):
            self.assertEqual(cooldown.remaining(), 1)

    def test_remaining_never_reads_zero_or_negative(self):
        """remaining() is only ever read right after start() in _live(),
        but it should never itself claim a request can go through
        immediately (0) or that the cooldown owes time back (negative)."""
        cooldown = _RateLimitCooldown(duration=60)
        with patch("services.market_data.time.time", return_value=1_000.0):
            cooldown.start()
        with patch("services.market_data.time.time", return_value=1_000.0 + 120):
            self.assertEqual(cooldown.remaining(), 1)


class LiveRateLimitCooldownTests(unittest.TestCase):
    """_live()'s side of the cooldown: what actually starts one, what
    must not, and what happens to requests while one is active. Every
    test here patches in a fresh cooldown - the real module-level one is
    a genuine 60-second singleton, and leaving a test's 429 in it would
    leak a live cooldown into whatever test runs next in this process."""

    def setUp(self):
        self.cooldown = _RateLimitCooldown(duration=RATE_LIMIT_COOLDOWN_SECONDS)
        patcher = patch("services.market_data._rate_limit_cooldown", self.cooldown)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_upstream_429_starts_the_cooldown(self):
        def boom():
            raise _UpstreamHTTPError(429)

        with self.assertRaises(DataUnavailable) as ctx:
            _live("holdings for 'SPY'", boom)

        self.assertTrue(self.cooldown.active())
        self.assertEqual(ctx.exception.retry_after, RATE_LIMIT_COOLDOWN_SECONDS)

    def test_a_bare_yfratelimiterror_also_starts_the_cooldown(self):
        """YFRateLimitError carries no response or code at all - it's
        raised from parsed error text, not an HTTP exception - so this is
        the case _upstream_status alone cannot see, and the reason _live
        also checks isinstance() directly."""
        def boom():
            raise YFRateLimitError()

        with self.assertRaises(DataUnavailable):
            _live("holdings for 'SPY'", boom)

        self.assertTrue(self.cooldown.active())

    def test_a_404_does_not_start_the_cooldown(self):
        def boom():
            raise _UpstreamHTTPError(404)

        with self.assertRaises(Exception):
            _live("holdings for 'ZZZZ'", boom)

        self.assertFalse(self.cooldown.active())

    def test_a_plain_outage_does_not_start_the_cooldown(self):
        """Every other failure keeps today's behaviour untouched: a
        generic DataUnavailable, default retry_after, no cooldown."""
        def boom():
            raise ConnectionError("connection refused")

        with self.assertRaises(DataUnavailable) as ctx:
            _live("holdings for 'SPY'", boom)

        self.assertFalse(self.cooldown.active())
        self.assertEqual(ctx.exception.retry_after, 3)

    def test_an_active_cooldown_is_answered_without_calling_yfinance_again(self):
        """The whole point: once the cooldown is running, a request does
        not even attempt another call to Yahoo - it fails immediately,
        which is what stops N open tabs each re-discovering the same
        429."""
        self.cooldown.start()
        fn = MagicMock()

        with self.assertRaises(DataUnavailable) as ctx:
            _live("holdings for 'SPY'", fn)

        fn.assert_not_called()
        self.assertEqual(ctx.exception.retry_after, RATE_LIMIT_COOLDOWN_SECONDS)

    def test_retry_after_counts_down_while_the_cooldown_is_active(self):
        with patch("services.market_data.time.time", return_value=1_000.0):
            self.cooldown.start()

        with patch("services.market_data.time.time", return_value=1_000.0 + 40):
            with self.assertRaises(DataUnavailable) as ctx:
                _live("holdings for 'SPY'", MagicMock())

        self.assertEqual(ctx.exception.retry_after, 20)

    def test_the_cooldown_expires_and_yfinance_is_asked_again(self):
        with patch("services.market_data.time.time",
                   return_value=1_000.0):
            self.cooldown.start()

        with patch("services.market_data.time.time",
                   return_value=1_000.0 + RATE_LIMIT_COOLDOWN_SECONDS + 1):
            self.assertEqual(_live("holdings for 'SPY'", lambda: "ok"), "ok")

    def test_a_db_hit_is_unaffected_by_an_active_cooldown(self):
        """A cooldown only ever gates the live fallback inside _live() -
        a request Supabase can already answer must not even notice one is
        running (acceptance criterion on #92)."""
        self.cooldown.start()
        db_row = {"id": "SPY", "name": "SPDR S&P 500 ETF Trust", "cat": "Large Blend",
                  "aum": 500.0, "desc": "d"}

        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._get_etf_info_db", return_value=db_row), \
             patch("services.market_data._get_etf_info_live") as mock_live:
            result = get_etf_info("SPY")

        self.assertEqual(result, db_row)
        mock_live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
