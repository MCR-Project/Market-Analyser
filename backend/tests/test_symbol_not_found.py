"""
Tests for telling "this ticker doesn't exist" apart from "Yahoo is down".

Both reach the backend as a failed live call, and both used to answer 503.
That collapsed two opposite facts: an outage is about right now and heals
on its own, while a made-up ticker never will. Since useFetch retries a
5xx and never retries a 4xx, the collapse left a typo'd ticker being
re-requested every three seconds forever, behind a panel promising a
recovery that could not come.

The pairing matters more than either case alone, so each test here has a
mirror: whatever proves a 404 is answered must not also make a real outage
look like a missing ticker, which would be the worse failure - every fund
reported as nonexistent the moment Yahoo hiccups.

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
from services.market_data import DataUnavailable, SymbolNotFound, _live, _upstream_status

client = TestClient(app, raise_server_exceptions=False)


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class UpstreamHTTPError(Exception):
    """Stands in for curl_cffi's HTTPError: carries the status on an
    attached response, and a `code` of 0 that must not be believed."""

    def __init__(self, status_code):
        super().__init__(f"HTTP Error {status_code}")
        self.response = FakeResponse(status_code)
        self.code = 0


class UpstreamStatusTests(unittest.TestCase):
    def test_reads_the_status_off_the_attached_response(self):
        self.assertEqual(_upstream_status(UpstreamHTTPError(404)), 404)

    def test_ignores_a_zero_code(self):
        """curl_cffi sets code=0 even on a real 404, so believing `code`
        over `response.status_code` would classify every 404 as an outage."""
        err = UpstreamHTTPError(404)

        self.assertEqual(err.code, 0)
        self.assertEqual(_upstream_status(err), 404)

    def test_accepts_a_urllib_style_code(self):
        err = Exception("boom")
        err.code = 404

        self.assertEqual(_upstream_status(err), 404)

    def test_walks_the_cause_chain(self):
        """yfinance sometimes re-raises through its own exception type."""
        try:
            try:
                raise UpstreamHTTPError(404)
            except UpstreamHTTPError as inner:
                raise RuntimeError("wrapped") from inner
        except RuntimeError as outer:
            self.assertEqual(_upstream_status(outer), 404)

    def test_a_plain_failure_has_no_status(self):
        self.assertIsNone(_upstream_status(ConnectionError("refused")))


class LiveClassificationTests(unittest.TestCase):
    def test_a_404_becomes_symbol_not_found(self):
        def boom():
            raise UpstreamHTTPError(404)

        with self.assertRaises(SymbolNotFound):
            _live("holdings for 'ZZZZ'", boom)

    def test_a_500_stays_an_outage(self):
        def boom():
            raise UpstreamHTTPError(500)

        with self.assertRaises(DataUnavailable):
            _live("holdings for 'SPY'", boom)

    def test_a_network_failure_stays_an_outage(self):
        """No status at all is the signature of a connection that never
        landed — the cold-start case, and the one that must keep retrying."""
        def boom():
            raise ConnectionError("connection refused")

        with self.assertRaises(DataUnavailable):
            _live("holdings for 'SPY'", boom)

    def test_a_rate_limit_stays_an_outage(self):
        def boom():
            raise UpstreamHTTPError(429)

        with self.assertRaises(DataUnavailable):
            _live("holdings for 'SPY'", boom)


class EndpointTests(unittest.TestCase):
    """The contract the frontend actually reads: the status code."""

    def test_unknown_etf_is_a_permanent_404(self):
        with patch("api.routes.get_etf_info",
                   side_effect=SymbolNotFound("'ETF info for ZZZZ': no such symbol upstream")):
            resp = client.get("/api/etf/ZZZZ")

        self.assertEqual(resp.status_code, 404)
        self.assertIsNone(resp.headers.get("Retry-After"))

    def test_unknown_etf_is_rejected_before_holdings_are_fetched(self):
        """The 404 branch used to sit after the holdings call, which 404s
        upstream for a made-up ticker — so it never ran for the case it
        was written for."""
        info = {"id": "ZZZZ", "name": "ZZZZ", "cat": "", "aum": 0, "desc": ""}

        with patch("api.routes.get_etf_info", return_value=info), \
             patch("api.routes.get_etf_holdings") as holdings:
            resp = client.get("/api/etf/ZZZZ")

        self.assertEqual(resp.status_code, 404)
        holdings.assert_not_called()

    def test_correlation_404s_for_an_unknown_etf(self):
        with patch("api.routes.get_etf_holdings",
                   side_effect=SymbolNotFound("'holdings for ZZZZ': no such symbol upstream")):
            resp = client.get("/api/correlation/ZZZZ")

        self.assertEqual(resp.status_code, 404)

    def test_sectors_404s_for_an_unknown_etf(self):
        with patch("api.routes.get_etf_holdings",
                   side_effect=SymbolNotFound("'holdings for ZZZZ': no such symbol upstream")):
            resp = client.get("/api/sectors/ZZZZ")

        self.assertEqual(resp.status_code, 404)

    def test_measurement_routes_404_for_an_unknown_etf(self):
        """Every column asks about the ETF too. These used to wrap any
        failure in a blanket 500, so all three kept retrying against a
        ticker that does not exist long after /api/etf had given up."""
        measurement = next(m for m in ALL_MEASUREMENTS if m.id == "etf_weight")

        with patch.object(measurement, "run",
                          side_effect=SymbolNotFound("holdings for 'ZZZZ': no such symbol upstream")):
            resp = client.get("/api/measurements/etf-weight/ZZZZ")

        self.assertEqual(resp.status_code, 404)

    def test_measurement_routes_still_503_on_an_outage(self):
        measurement = next(m for m in ALL_MEASUREMENTS if m.id == "etf_weight")

        with patch.object(measurement, "run",
                          side_effect=DataUnavailable("holdings for 'SPY' is temporarily unavailable upstream")):
            resp = client.get("/api/measurements/etf-weight/SPY")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.headers.get("Retry-After"), "3")

    def test_a_genuine_measurement_bug_is_still_a_500(self):
        """Only the two data-availability signals pass through; anything
        else is still the measurement's own fault."""
        measurement = next(m for m in ALL_MEASUREMENTS if m.id == "etf_weight")

        with patch.object(measurement, "run", side_effect=ZeroDivisionError("oops")):
            resp = client.get("/api/measurements/etf-weight/SPY")

        self.assertEqual(resp.status_code, 500)

    def test_a_real_outage_on_a_real_etf_is_still_a_retryable_503(self):
        """The mirror that matters: an unreachable Yahoo must not start
        reporting every fund as nonexistent."""
        with patch("api.routes.get_etf_info",
                   side_effect=DataUnavailable("ETF info for 'SPY' is temporarily unavailable upstream")):
            resp = client.get("/api/etf/SPY")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.headers.get("Retry-After"), "3")


if __name__ == "__main__":
    unittest.main()
