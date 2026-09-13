"""
Unit tests for services/market_data.py.

auto_adjust=True coverage (issue #13) locks in the two live-fallback paths
that must keep agreeing with fetch_ticker_rows's own guard in
test_fetch_daily.py - _get_price_series_live (single-ticker series) and
_closes_live (the correlation matrix's multi-ticker path) - so an upstream
yfinance default change, or an incautious edit, can't silently reintroduce
raw closes on just one of the read paths.

_correlation_summary coverage exercises its degenerate-input boundaries:
with zero or one available ticker there are no pairs to compare, so
strongest/weakest must come back None rather than an out-of-range sentinel
(value=-1 / value=2) leaking into the result unexamined - hub, which has no
pairs requirement, must still reflect the real (possibly negative) average
rather than a hardcoded avgCorr=0 baseline that an all-negative average set
could never beat, and must itself be None rather than 0 when nothing is
available to average at all (issue #97).

It also covers the overlap-gating rule from issue #97: a pair with fewer
than MIN_OVERLAPPING_RETURNS jointly non-null returns reports None, not
0.0 - "we do not know" and "these move independently" are not the same
claim, and only the first is true of a holding that only just listed.
Every test below that checks a real (non-null) correlation value patches
MIN_OVERLAPPING_RETURNS down to 2, since the tiny hand-built samples here
are far short of the real default and would otherwise report null for
every pair - that patch is orthogonal to what those tests are actually
checking (the pre-existing degenerate-case handling), while the dedicated
overlap tests patch it to exercise the gate itself.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from services.cache import TTLCache
from services.market_data import (
    _closes_live,
    _correlation_summary,
    _get_price_series_live,
    _throttled_force_refresh,
    get_etf_holdings,
    get_etf_info,
)


class GetPriceSeriesLiveTests(unittest.TestCase):
    def _fake_history(self):
        dates = pd.to_datetime(["2024-06-06", "2024-06-07"])
        return pd.DataFrame(
            {"Close": [1205.0, 120.5], "Volume": [1_000_000, 2_000_000]},
            index=dates,
        )

    def test_requests_adjusted_history(self):
        """auto_adjust=True must stay explicit - relying on yfinance's
        default would silently reintroduce the mismatch with
        scripts/fetch_daily.py's fetch_ticker_rows if that default ever
        changed upstream."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._fake_history()
        with patch("services.market_data.yf.Ticker", return_value=mock_ticker) as mock_cls:
            result = _get_price_series_live("NVDA", "1y", "1d")

        mock_cls.assert_called_once_with("NVDA")
        mock_ticker.history.assert_called_once_with(period="1y", interval="1d", auto_adjust=True)
        self.assertEqual(result[1]["close"], 120.5)


class ClosesLiveTests(unittest.TestCase):
    def _fake_download(self):
        dates = pd.to_datetime(["2024-06-06", "2024-06-07"])
        columns = pd.MultiIndex.from_tuples([("Close", "NVDA"), ("Close", "SMH")])
        return pd.DataFrame(
            [[1205.0, 200.0], [120.5, 201.0]], index=dates, columns=columns
        )

    def test_requests_adjusted_history(self):
        """Same guard as _get_price_series_live, for the correlation
        matrix's multi-ticker download path - a raw close here makes
        pct_change() read a stock split as a huge one-day return
        (compute_correlation_matrix, issue #13)."""
        with patch("services.market_data.yf.download", return_value=self._fake_download()) as mock_download:
            closes = _closes_live(["NVDA", "SMH"], "1y", "1d")

        mock_download.assert_called_once_with(
            ["NVDA", "SMH"], period="1y", interval="1d", progress=False, threads=True,
            auto_adjust=True,
        )
        self.assertEqual(list(closes.columns), ["NVDA", "SMH"])


# ── get_etf_holdings ─────────────────────────────────────────────────────────

class GetEtfHoldingsCachingTests(unittest.TestCase):
    def test_empty_holdings_result_is_cached_not_refetched_live(self):
        """An ETF with genuinely no holdings (DB miss, live fetch also
        empty) must be cached like any other result - `if cached:` used to
        be falsy for a cached empty list, so this fell through to a live
        yfinance call on every single request despite the docstring's
        claim otherwise. Second call must hit the cache: _get_etf_holdings_db
        and _get_etf_holdings_live are each called exactly once, not once
        per request."""
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._get_etf_holdings_db", return_value=None) as mock_db, \
             patch("services.market_data._get_etf_holdings_live", return_value=[]) as mock_live:
            first = get_etf_holdings("EMPTYETF")
            second = get_etf_holdings("EMPTYETF")

        mock_db.assert_called_once_with("EMPTYETF")
        mock_live.assert_called_once_with("EMPTYETF")
        self.assertEqual(first, ([], True))
        self.assertEqual(second, ([], True))

    def test_stale_flag_travels_with_holdings_not_a_sibling_key(self):
        """stale must come back bundled with the holdings it describes
        (a single cached tuple), not as a second cache lookup a caller has
        to make in the right order - so a DB hit reports stale=False and a
        live fallback reports stale=True, both readable straight off this
        one call's return value."""
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._get_etf_holdings_db", return_value=[["AAPL", 10.0]]), \
             patch("services.market_data._get_etf_holdings_live") as mock_live:
            db_hit = get_etf_holdings("DBHITETF")

        mock_live.assert_not_called()
        self.assertEqual(db_hit, ([["AAPL", 10.0]], False))


# ── _correlation_summary ─────────────────────────────────────────────────────

class CorrelationSummaryTests(unittest.TestCase):
    def test_zero_available_tickers_returns_none_pairs(self):
        """No requested ticker has a returns column at all (e.g. yfinance/DB
        had data for none of them) - available ends up empty, so there's no
        pair to compare and no ticker to be the hub. strongest/weakest/hub
        all come back None (not a fake pair, not a "" / 0 sentinel), rather
        than leaking a scan sentinel into the result."""
        returns = pd.DataFrame(index=pd.to_datetime(["2024-06-06", "2024-06-07"]))

        result = _correlation_summary(returns, ["AAPL", "MSFT"])

        self.assertEqual(result["tickers"], [])
        self.assertEqual(result["matrix"], {})
        self.assertEqual(result["averages"], {})
        self.assertIsNone(result["strongest"])
        self.assertIsNone(result["weakest"])
        self.assertIsNone(result["hub"])

    def test_requested_ticker_missing_from_returns_is_dropped_from_available(self):
        """A ticker requested but absent from `returns.columns` (not yet
        synced) is silently excluded from `tickers`/`matrix`, not an
        error - the summary is computed over whichever subset is present."""
        returns = pd.DataFrame(
            {"AAPL": [0.01, -0.02, 0.03]},
            index=pd.to_datetime(["2024-06-06", "2024-06-07", "2024-06-10"]),
        )

        result = _correlation_summary(returns, ["AAPL", "MSFT"])

        self.assertEqual(result["tickers"], ["AAPL"])
        self.assertNotIn("MSFT", result["matrix"])

    def test_single_ticker_has_no_pairs_and_a_null_average(self):
        """With exactly one available ticker there's no peer to correlate
        against at all - not "insufficient overlap" but no pair to begin
        with - so the average is None (issue #97), not a defaulted zero,
        and hub has no ticker to point to. A ticker's self-correlation is
        still exactly 1.0 regardless of how little history it has: that's
        the diagonal's definition, not a claim the overlap minimum
        governs. strongest/weakest - which only ever compare pairs - stay
        None, matching the 0-ticker case."""
        returns = pd.DataFrame(
            {"AAPL": [0.01, -0.02, 0.03]},
            index=pd.to_datetime(["2024-06-06", "2024-06-07", "2024-06-10"]),
        )

        result = _correlation_summary(returns, ["AAPL"])

        self.assertEqual(result["tickers"], ["AAPL"])
        self.assertEqual(result["matrix"]["AAPL"]["AAPL"], 1.0)
        self.assertIsNone(result["averages"]["AAPL"])
        self.assertIsNone(result["hub"])
        self.assertIsNone(result["strongest"])
        self.assertIsNone(result["weakest"])

    @patch("services.market_data.MIN_OVERLAPPING_RETURNS", 2)
    def test_all_negative_averages_hub_reflects_real_value(self):
        """When every ticker's average correlation to its peers is negative,
        a hardcoded avgCorr=0 baseline would never lose to any of them,
        silently reporting a hub that doesn't exist in the data. The hub
        must reflect the actual best (least negative) average instead.
        MIN_OVERLAPPING_RETURNS is patched down to 2 because this sample
        is 4 rows - far short of the real default - and the point of this
        test is the hub/average logic, not the overlap gate."""
        dates = pd.to_datetime(["2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06"])
        returns = pd.DataFrame(
            {
                "A": [0.01, -0.02, 0.03, -0.01],
                "B": [-0.01, 0.02, -0.03, 0.01],
            },
            index=dates,
        )

        result = _correlation_summary(returns, ["A", "B"])

        self.assertEqual(result["averages"], {"A": -1.0, "B": -1.0})
        self.assertEqual(result["hub"]["avgCorr"], -1.0)
        self.assertIn(result["hub"]["ticker"], {"A", "B"})

    @patch("services.market_data.MIN_OVERLAPPING_RETURNS", 2)
    def test_three_tickers_picks_strongest_weakest_pair_and_hub(self):
        """Sanity check of the non-degenerate path: A and B move in
        lockstep (correlation 1), C is their exact mirror image
        (correlation -1 with both) - strongest must be the A/B pair,
        weakest either C pair (both are -1; scan order picks A/C first and
        a tie never overwrites it), and each ticker's average correlation
        to its peers must reflect that shape. MIN_OVERLAPPING_RETURNS is
        patched down for the same reason as above."""
        dates = pd.to_datetime(["2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06", "2024-06-07"])
        returns = pd.DataFrame(
            {
                "A": [0.01, -0.02, 0.03, -0.01, 0.02],
                "B": [0.01, -0.02, 0.03, -0.01, 0.02],
                "C": [-0.01, 0.02, -0.03, 0.01, -0.02],
            },
            index=dates,
        )

        result = _correlation_summary(returns, ["A", "B", "C"])

        self.assertEqual(result["tickers"], ["A", "B", "C"])
        self.assertEqual(result["strongest"], {"a": "A", "b": "B", "value": 1.0})
        self.assertEqual(result["weakest"], {"a": "A", "b": "C", "value": -1.0})
        self.assertEqual(result["averages"], {"A": 0, "B": 0, "C": -1})

    @patch("services.market_data.MIN_OVERLAPPING_RETURNS", 3)
    def test_pair_below_overlap_minimum_is_null_not_zero(self):
        """C only shares two non-null returns with A and with B - one short
        of the (patched) minimum of 3 - simulating a holding that listed
        partway through the window. Its pairs with A and B must be None,
        not a correlation computed from too little to mean anything and
        certainly not the 0.0 this used to default to (issue #97). A and
        B, which fully overlap, still get a real value; C's diagonal is
        still 1.0 regardless."""
        dates = pd.to_datetime(
            ["2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06", "2024-06-07"]
        )
        returns = pd.DataFrame(
            {
                "A": [0.01, -0.02, 0.03, -0.01, 0.02],
                "B": [0.02, -0.01, 0.02, -0.02, 0.01],
                "C": [None, None, None, 0.01, -0.01],
            },
            index=dates,
        )

        result = _correlation_summary(returns, ["A", "B", "C"])

        self.assertIsNone(result["matrix"]["A"]["C"])
        self.assertIsNone(result["matrix"]["C"]["A"])
        self.assertIsNone(result["matrix"]["B"]["C"])
        self.assertIsNotNone(result["matrix"]["A"]["B"])
        self.assertEqual(result["matrix"]["C"]["C"], 1.0)

    @patch("services.market_data.MIN_OVERLAPPING_RETURNS", 3)
    def test_averages_and_hub_exclude_a_ticker_with_no_usable_pair(self):
        """C's only two potential peers are both null pairs (see above), so
        its average must be null rather than computed as if the missing
        pairs were zero, and it must never become the hub or the
        strongest/weakest pair - those stay confined to the one real (A/B)
        pair that exists."""
        dates = pd.to_datetime(
            ["2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06", "2024-06-07"]
        )
        returns = pd.DataFrame(
            {
                "A": [0.01, -0.02, 0.03, -0.01, 0.02],
                "B": [0.02, -0.01, 0.02, -0.02, 0.01],
                "C": [None, None, None, 0.01, -0.01],
            },
            index=dates,
        )

        result = _correlation_summary(returns, ["A", "B", "C"])

        self.assertIsNone(result["averages"]["C"])
        self.assertIsNotNone(result["averages"]["A"])
        self.assertIsNotNone(result["averages"]["B"])
        self.assertIn(result["hub"]["ticker"], {"A", "B"})
        self.assertNotIn("C", (result["strongest"]["a"], result["strongest"]["b"]))
        self.assertNotIn("C", (result["weakest"]["a"], result["weakest"]["b"]))


class ThrottledForceRefreshTests(unittest.TestCase):
    """_throttled_force_refresh in isolation (issue #93). Every test here
    patches in a fresh dict - the real _last_force_refresh is a genuine
    5-minute-per-key store and would otherwise leak between tests the
    same way _rate_limit_cooldown would without the same care
    (test_transient_failures.py)."""

    def test_false_when_not_requested(self):
        with patch("services.market_data._last_force_refresh", {}):
            self.assertFalse(_throttled_force_refresh("etf_info:SPY", False))

    def test_true_on_first_request_for_a_key(self):
        with patch("services.market_data._last_force_refresh", {}):
            self.assertTrue(_throttled_force_refresh("etf_info:SPY", True))

    def test_false_for_a_second_request_inside_the_window(self):
        with patch("services.market_data._last_force_refresh", {}), \
             patch("services.market_data.time.time", side_effect=[1_000.0, 1_000.0 + 60]):
            self.assertTrue(_throttled_force_refresh("etf_info:SPY", True))
            self.assertFalse(_throttled_force_refresh("etf_info:SPY", True))

    def test_true_again_once_the_window_has_passed(self):
        with patch("services.market_data._last_force_refresh", {}), \
             patch("services.market_data.time.time", side_effect=[1_000.0, 1_000.0 + 301]):
            self.assertTrue(_throttled_force_refresh("etf_info:SPY", True))
            self.assertTrue(_throttled_force_refresh("etf_info:SPY", True))

    def test_different_keys_do_not_share_a_throttle(self):
        with patch("services.market_data._last_force_refresh", {}):
            self.assertTrue(_throttled_force_refresh("etf_info:SPY", True))
            self.assertTrue(_throttled_force_refresh("etf_info:SMH", True))


class ForceRefreshIntegrationTests(unittest.TestCase):
    """get_etf_info/get_etf_holdings honouring the throttle end to end -
    the public functions a route actually calls, not just the private
    helper above."""

    def test_two_refreshes_within_the_window_reach_live_once(self):
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._last_force_refresh", {}), \
             patch("services.market_data._get_etf_info_db", return_value=None), \
             patch("services.market_data._get_etf_info_live",
                   return_value={"id": "SPY", "name": "SPDR S&P 500", "cat": "", "aum": 0, "desc": ""}) as mock_live:
            first = get_etf_info("SPY", force_refresh=True)
            second = get_etf_info("SPY", force_refresh=True)

        self.assertEqual(mock_live.call_count, 1)
        self.assertEqual(first, second)

    def test_a_refresh_outside_the_window_reaches_live_again(self):
        """The mirror of the test above: throttling a refresh must not
        become refusing one forever."""
        import time as time_module

        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._last_force_refresh",
                   {"etf_info:SPY": time_module.time() - 301}), \
             patch("services.market_data._get_etf_info_db", return_value=None), \
             patch("services.market_data._get_etf_info_live",
                   return_value={"id": "SPY", "name": "SPDR S&P 500", "cat": "", "aum": 0, "desc": ""}) as mock_live:
            get_etf_info("SPY", force_refresh=True)

        mock_live.assert_called_once()

    def test_a_plain_request_is_never_throttled(self):
        """force_refresh=False must always read the cache normally -
        the throttle only ever governs *bypassing* it."""
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._last_force_refresh", {}), \
             patch("services.market_data._get_etf_info_db",
                   return_value={"id": "SPY", "name": "SPDR S&P 500", "cat": "", "aum": 0, "desc": ""}) as mock_db:
            get_etf_info("SPY")
            get_etf_info("SPY")

        # The second call is a cache hit either way (10s DB-path TTL),
        # so this pins the *reason* it wasn't fetched twice is the
        # ordinary cache, not the refresh throttle never having been
        # exercised at all.
        self.assertEqual(mock_db.call_count, 1)

    def test_holdings_refresh_is_throttled_the_same_way(self):
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._last_force_refresh", {}), \
             patch("services.market_data._get_etf_holdings_db", return_value=None), \
             patch("services.market_data._get_etf_holdings_live",
                   return_value=[["NVDA", 8.0]]) as mock_live:
            get_etf_holdings("SPY", force_refresh=True)
            get_etf_holdings("SPY", force_refresh=True)

        self.assertEqual(mock_live.call_count, 1)


if __name__ == "__main__":
    unittest.main()
