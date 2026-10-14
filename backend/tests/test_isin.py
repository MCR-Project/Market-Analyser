"""
Tests for resolving an ISIN to its listings (issue #190).

An ISIN identifies a security wherever it trades, so one code can lead to
several tickers - or to none, even when the code is genuine. Three things are
under test, each at the boundary a caller sees:

  - **The code itself.** `normalise_isin` accepts what a person pastes
    (any case, spaces round it) and says *which* way a bad one is bad: the
    wrong shape, or a check digit that does not add up. Both are a 400, and
    neither costs an upstream call.

  - **What Yahoo's answer is made into.** `resolve_isin` drops hits that are
    not usable (the ISIN standing in as a symbol, anything `SYMBOL_PATTERN`
    would refuse), keeps Yahoo's order, and describes each one that is left
    with its exchange and currency. A currency it cannot read is `None`,
    never a guessed "USD" (invariant 7).

  - **The three outcomes stay three.** A listing found is 200, a genuine ISIN
    with nothing usable is 404 - worded so as not to call the code invalid -
    and an upstream that could not be asked is 503, which the frontend retries
    and which is never cached.

Nothing here reaches Yahoo or Supabase: the live search and the live
currency read are patched at the `market_data` seam, and the tracked universe
comes from a fake client, the way test_tickers.py does it.

Run with:   pytest   (from the repo root)
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from yfinance.exceptions import YFRateLimitError

from config import CACHE_TTL_HOLDINGS, CACHE_TTL_ISIN_MISS
from main import app
from rate_limit import FixedWindowLimiter
from services.cache import TTLCache
from services.market_data import DataUnavailable, SymbolNotFound, _RateLimitCooldown
from services.tickers import normalise_isin, resolve_isin

client = TestClient(app, raise_server_exceptions=False)

# Real ISINs, so the check digit is verified against a source other than the
# code under test. Apple, iShares Core MSCI World, TotalEnergies, SPDR S&P 500.
REAL_ISINS = ["US0378331005", "IE00B4L5Y983", "FR0000120271", "US78462F1030"]


class NormaliseIsinTests(unittest.TestCase):
    def test_a_real_isin_is_accepted_whatever_its_case_and_padding(self):
        self.assertEqual(normalise_isin("US0378331005"), "US0378331005")
        self.assertEqual(normalise_isin("  us0378331005 "), "US0378331005")

    def test_every_real_isin_passes_its_own_check_digit(self):
        for isin in REAL_ISINS:
            with self.subTest(isin=isin):
                self.assertEqual(normalise_isin(isin), isin)

    def test_changing_any_one_digit_breaks_the_check_digit(self):
        """A single mistyped digit is always caught by the Luhn check -
        which is what turns a typo into a precise message instead of an
        ambiguous "not found"."""
        for isin in REAL_ISINS:
            for position in range(2, 12):
                original = isin[position]
                swapped = "0" if original != "0" else "1"
                if not original.isdigit():
                    continue
                broken = isin[:position] + swapped + isin[position + 1:]
                with self.subTest(isin=broken):
                    with self.assertRaises(ValueError) as ctx:
                        normalise_isin(broken)
                    self.assertIn("check digit", str(ctx.exception))

    def test_a_wrong_shape_is_refused_and_says_it_is_the_shape(self):
        for candidate in ("", "AAPL", "US037833100", "US03783310055", "0378331005US",
                          "US037833100A", "U10378331005", "US-378331005"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError) as ctx:
                    normalise_isin(candidate)
                self.assertNotIn("check digit", str(ctx.exception))

TICKERS = [
    {"id": "AAPL", "name": "Apple Inc.", "sector": "Technology", "logo": "aapl.png"},
]
ETFS = [
    {"id": "SPY", "name": "State Street SPDR S&P 500 ETF Trust", "cat": "Large Blend"},
]


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def range(self, start, end):
        self._rows = self._rows[start:end + 1]
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _FakeClient:
    def table(self, name):
        return _FakeQuery({"ticker": TICKERS, "etfs": ETFS}.get(name, []))


class _SpyCache(TTLCache):
    """A real cache that also remembers the TTL each key was stored with."""

    def __init__(self):
        super().__init__()
        self.ttls = {}

    def set(self, key, value, ttl):
        self.ttls[key] = ttl
        super().set(key, value, ttl)


def _hit(symbol, name=None, exchange="London"):
    return {"symbol": symbol, "name": name, "exchange": exchange}


class _Fixture(unittest.TestCase):
    """An empty cache and a two-symbol tracked universe for every test, so
    one test's cached answer cannot stand in for another's lookup."""

    def setUp(self):
        for p in (
            patch("services.tickers.cache", TTLCache()),
            patch("services.tickers.get_client_optional", return_value=_FakeClient()),
            # The route tests make a dozen /api calls from the one address
            # every TestClient shares; a limiter of their own keeps them
            # from spending the real bucket the rest of the suite relies on
            # (backend/CLAUDE.md, "Tests").
            patch("rate_limit.general_limiter", FixedWindowLimiter(limit=100_000)),
            patch("rate_limit.simulate_limiter", FixedWindowLimiter(limit=100_000)),
        ):
            p.start()
            self.addCleanup(p.stop)

    def resolve(self, hits, currency="USD", isin="IE00B4L5Y983"):
        with patch("services.tickers.search_listings", return_value=hits), \
             patch("services.tickers.get_listing_currency", return_value=currency):
            return resolve_isin(isin)


class ResolveIsinTests(_Fixture):
    def test_an_untracked_listing_is_described_from_the_hit(self):
        resolved = self.resolve([_hit("IWDA.L", "iShares Core MSCI World UCITS ETF")])

        self.assertEqual(resolved["isin"], "IE00B4L5Y983")
        (listing,) = resolved["listings"]
        self.assertEqual(listing["symbol"], "IWDA.L")
        self.assertEqual(listing["name"], "iShares Core MSCI World UCITS ETF")
        self.assertEqual(listing["exchange"], "London")
        self.assertEqual(listing["currency"], "USD")
        self.assertFalse(listing["tracked"])
        # Nothing in a search hit is a promise about what it is (ADR 0004).
        self.assertIsNone(listing["kind"])

    def test_a_tracked_listing_is_described_from_the_tracked_universe(self):
        (listing,) = self.resolve([_hit("AAPL", "APPLE INC", "NASDAQ")],
                                  isin="US0378331005")["listings"]

        self.assertTrue(listing["tracked"])
        self.assertEqual(listing["kind"], "stock")
        self.assertEqual(listing["name"], "Apple Inc.")
        self.assertEqual(listing["exchange"], "NASDAQ")

    def test_a_tracked_fund_keeps_its_kind(self):
        (listing,) = self.resolve([_hit("SPY", "SPDR S&P 500", "NYSE Arca")],
                                  isin="US78462F1030")["listings"]

        self.assertEqual(listing["kind"], "etf")
        self.assertTrue(listing["tracked"])

    def test_the_isin_standing_in_as_a_symbol_is_dropped(self):
        """Yahoo lists IE00BK5BQT80.SG - a Stuttgart line whose "symbol" is
        the ISIN itself - beside the real VWRA.L."""
        resolved = self.resolve(
            [_hit("VWRA.L", "Vanguard FTSE All-World"), _hit("IE00BK5BQT80.SG", None, "Stuttgart")],
            isin="IE00BK5BQT80",
        )

        self.assertEqual([l["symbol"] for l in resolved["listings"]], ["VWRA.L"])

    def test_a_hit_that_is_not_a_symbol_is_dropped(self):
        resolved = self.resolve([_hit("NOT A SYMBOL!"), _hit("TOOLONGSYMBOL.XX"), _hit("IWDA.L")])

        self.assertEqual([l["symbol"] for l in resolved["listings"]], ["IWDA.L"])

    def test_yahoos_order_is_kept_and_at_most_three_are_described(self):
        hits = [_hit(s) for s in ("A.L", "B.PA", "C.DE", "D.MI", "E.AS")]

        resolved = self.resolve(hits)

        self.assertEqual([l["symbol"] for l in resolved["listings"]], ["A.L", "B.PA", "C.DE"])

    def test_a_symbol_listed_twice_is_one_listing(self):
        resolved = self.resolve([_hit("IWDA.L"), _hit("IWDA.L")])

        self.assertEqual(len(resolved["listings"]), 1)

    def test_a_currency_that_cannot_be_read_is_null_not_a_guess(self):
        """`get_stock_info` defaults a missing currency to USD. Here that
        would state a currency nobody read, on the very row meant to warn
        that a listing may not be in dollars (invariant 7)."""
        (listing,) = self.resolve([_hit("IWDA.L")], currency=None)["listings"]

        self.assertIsNone(listing["currency"])

    def test_a_hit_upstream_has_no_info_for_is_kept_with_a_null_currency(self):
        with patch("services.tickers.search_listings", return_value=[_hit("IWDA.L")]), \
             patch("services.tickers.get_listing_currency", side_effect=SymbolNotFound("no info")):
            (listing,) = resolve_isin("IE00B4L5Y983")["listings"]

        self.assertIsNone(listing["currency"])

    def test_the_code_is_normalised_before_it_is_asked_about(self):
        with patch("services.tickers.search_listings", return_value=[_hit("IWDA.L")]) as search, \
             patch("services.tickers.get_listing_currency", return_value="USD"):
            resolve_isin(" ie00b4l5y983 ")

        search.assert_called_once_with("IE00B4L5Y983")

    def test_an_answer_with_an_unknown_currency_is_kept_only_briefly(self):
        """Yahoo can return a thin `.info` without raising. A blank read
        that is really a hiccup must not be held for the hour."""
        spy = _SpyCache()
        with patch("services.tickers.cache", spy):
            self.resolve([_hit("IWDA.L")], currency=None)
            self.resolve([_hit("VWRA.L")], currency="USD", isin="IE00BK5BQT80")

        self.assertEqual(spy.ttls["isin:IE00B4L5Y983"], CACHE_TTL_ISIN_MISS)
        self.assertEqual(spy.ttls["isin:IE00BK5BQT80"], CACHE_TTL_HOLDINGS)

    def test_an_answer_is_cached(self):
        with patch("services.tickers.search_listings", return_value=[_hit("IWDA.L")]) as search, \
             patch("services.tickers.get_listing_currency", return_value="USD") as currency:
            resolve_isin("IE00B4L5Y983")
            resolve_isin("ie00b4l5y983")

        search.assert_called_once()
        currency.assert_called_once()


class NothingUsableTests(_Fixture):
    def test_a_genuine_isin_with_no_hit_is_not_found_and_not_called_invalid(self):
        """GB00B10RZP78 (Unilever) is a real ISIN that Yahoo answers with
        nothing. "No listing" is a fact about Yahoo's index, so the message
        must not send somebody off to recheck a code that was right."""
        with patch("services.tickers.search_listings", return_value=[]):
            with self.assertRaises(SymbolNotFound) as ctx:
                resolve_isin("GB00B10RZP78")

        self.assertIn("GB00B10RZP78", str(ctx.exception))
        self.assertNotIn("invalid", str(ctx.exception).lower())

    def test_hits_that_are_all_dropped_read_the_same_way(self):
        with patch("services.tickers.search_listings",
                   return_value=[_hit("IE00BK5BQT80.SG")]):
            with self.assertRaises(SymbolNotFound):
                resolve_isin("IE00BK5BQT80")

    def test_an_empty_answer_is_remembered_briefly(self):
        with patch("services.tickers.search_listings", return_value=[]) as search:
            for _ in range(2):
                with self.assertRaises(SymbolNotFound):
                    resolve_isin("GB00B10RZP78")

        search.assert_called_once()

    def test_a_bad_code_is_refused_before_upstream_is_asked(self):
        with patch("services.tickers.search_listings") as search:
            for candidate in ("US0378331006", "AAPL", ""):
                with self.subTest(candidate=candidate):
                    with self.assertRaises(ValueError):
                        resolve_isin(candidate)

        search.assert_not_called()


class UpstreamFailureTests(_Fixture):
    def test_an_outage_is_not_a_missing_listing_and_is_not_cached(self):
        with patch("services.tickers.search_listings", side_effect=DataUnavailable("down")):
            with self.assertRaises(DataUnavailable):
                resolve_isin("IE00B4L5Y983")

        resolved = self.resolve([_hit("IWDA.L")])
        self.assertEqual(resolved["listings"][0]["symbol"], "IWDA.L")

    def test_a_currency_read_that_could_not_be_made_fails_the_whole_answer(self):
        """A listing with a currency left blank because Yahoo hiccuped would
        be cached for an hour as though blank were the fact."""
        with patch("services.tickers.search_listings", return_value=[_hit("IWDA.L")]), \
             patch("services.tickers.get_listing_currency", side_effect=DataUnavailable("down")):
            with self.assertRaises(DataUnavailable):
                resolve_isin("IE00B4L5Y983")


class IsinRouteTests(_Fixture):
    def test_a_real_isin_answers_200_with_its_listings(self):
        with patch("services.tickers.search_listings", return_value=[_hit("AAPL", None, "NASDAQ")]), \
             patch("services.tickers.get_listing_currency", return_value="USD"):
            resp = client.get("/api/tickers/isin/US0378331005")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["isin"], "US0378331005")
        self.assertEqual(body["listings"][0]["symbol"], "AAPL")
        self.assertEqual(body["listings"][0]["currency"], "USD")

    def test_the_symbol_route_does_not_swallow_it(self):
        """/tickers/{symbol} would read "isin" as a symbol. The answer here
        is a lookup of listings, not a resolution of a symbol called ISIN."""
        with patch("services.tickers.search_listings", return_value=[_hit("AAPL")]), \
             patch("services.tickers.get_listing_currency", return_value="USD"), \
             patch("services.tickers.get_price_series") as series:
            resp = client.get("/api/tickers/isin/us0378331005")

        series.assert_not_called()
        self.assertIn("listings", resp.json())

    def test_a_malformed_isin_is_a_400_and_asks_nobody(self):
        with patch("services.tickers.search_listings") as search:
            resp = client.get("/api/tickers/isin/NOTANISIN")

        self.assertEqual(resp.status_code, 400)
        search.assert_not_called()

    def test_a_wrong_check_digit_is_a_400_that_says_so(self):
        with patch("services.tickers.search_listings") as search:
            resp = client.get("/api/tickers/isin/US0378331006")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("check digit", resp.json()["detail"])
        search.assert_not_called()

    def test_no_listing_is_a_404(self):
        with patch("services.tickers.search_listings", return_value=[]):
            resp = client.get("/api/tickers/isin/GB00B10RZP78")

        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("invalid", resp.json()["detail"].lower())

    def test_an_outage_is_a_retryable_503(self):
        with patch("services.tickers.search_listings", side_effect=DataUnavailable("down")):
            resp = client.get("/api/tickers/isin/US0378331005")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.headers.get("Retry-After"), "3")

    def test_a_rate_limited_upstream_is_a_503_with_the_cooldowns_own_wait(self):
        """The search goes through `_live`, so a 429 starts the same
        cooldown every other live read honours and the frontend waits the
        real time rather than a guess."""
        cooldown = _RateLimitCooldown(duration=45)
        with patch("services.market_data._rate_limit_cooldown", cooldown), \
             patch("services.market_data._search_listings_live", side_effect=YFRateLimitError()):
            resp = client.get("/api/tickers/isin/US0378331005")

        self.assertEqual(resp.status_code, 503)
        self.assertTrue(cooldown.active())
        self.assertEqual(resp.headers.get("Retry-After"), str(cooldown.remaining()))


class SearchStaysOffTheNetworkTests(_Fixture):
    def test_the_search_route_still_never_calls_yfinance(self):
        with patch("services.tickers.search_listings") as search, \
             patch("services.tickers.get_listing_currency") as currency:
            client.get("/api/tickers/search?q=US0378331005")

        search.assert_not_called()
        currency.assert_not_called()


if __name__ == "__main__":
    unittest.main()
