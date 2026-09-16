"""
Tests for tracking a risk-free rate and letting the interface override it
(issue #103).

Three layers:

  - `scripts/fetch_daily.py`'s `fetch_risk_free_rate_rows` /
    `sync_risk_free_rate` — the pipeline side. No test here touches the
    network: yfinance is mocked, and the Supabase client is a small fake
    whose `.table("risk_free_rate")`/`.table("risk_free_rate_source")`
    calls are recorded rather than sent anywhere. `_risk_free_rate_symbol`
    reading the source symbol from the database rather than a Python
    constant is itself under test - invariant 4 ("no hardcoded ticker
    list anywhere") applies to this series exactly the same way it
    applies to the tracked ETF/stock universe.
  - `services.market_data.get_risk_free_rate` — the reader a future
    Sharpe/Sortino implementation (issue #112) will read a run's window
    from. No live fallback, the same reasoning `get_dividends` already
    gives - covered here the same way `test_price_windows.py` covers
    `get_dividends`'s own window handling.
  - `PortfolioIn.rate` — the request field `POST /api/portfolio/simulate`
    now accepts, so a caller that already knows about the override (or the
    future `POST /api/portfolio/risk`, issue #113, sharing the same body
    shape) does not get a 422 for sending one. Not yet read by
    `simulate_portfolio` - the ratios themselves are out of scope here -
    so this only proves the field round-trips harmlessly.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from fastapi.testclient import TestClient

from main import app
from scripts.fetch_daily import (
    _risk_free_rate_symbol,
    fetch_risk_free_rate_rows,
    sync_risk_free_rate,
)
from services.market_data import get_risk_free_rate

client = TestClient(app, raise_server_exceptions=False)


# ── fetch_risk_free_rate_rows ─────────────────────────────────────────────────

class FetchRiskFreeRateRowsTests(unittest.TestCase):
    def _fake_history(self):
        dates = pd.to_datetime(["2024-06-06", "2024-06-07"])
        return pd.DataFrame({"Close": [5.24, 5.26]}, index=dates)

    def test_requests_the_given_symbol(self):
        """The symbol is a caller-supplied parameter, never a constant in
        this module - see _risk_free_rate_symbol, which is what actually
        decides it, from the database."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._fake_history()
        with patch("scripts.fetch_daily.yf.Ticker", return_value=mock_ticker) as mock_cls:
            fetch_risk_free_rate_rows("^IRX", "5d")

        mock_cls.assert_called_once_with("^IRX")
        mock_ticker.history.assert_called_once_with(period="5d")

    def test_close_is_read_as_a_yield_not_a_price(self):
        """No auto_adjust here, unlike fetch_ticker_rows - a quote has
        nothing to split-adjust."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._fake_history()
        with patch("scripts.fetch_daily.yf.Ticker", return_value=mock_ticker):
            rows = fetch_risk_free_rate_rows("^IRX", "5d")

        self.assertEqual(rows, [
            {"date": "2024-06-06", "rate": 5.24},
            {"date": "2024-06-07", "rate": 5.26},
        ])

    def test_an_empty_response_is_a_bare_empty_list(self):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        with patch("scripts.fetch_daily.yf.Ticker", return_value=mock_ticker):
            self.assertEqual(fetch_risk_free_rate_rows("^IRX", "5d"), [])


# ── _risk_free_rate_symbol / sync_risk_free_rate ──────────────────────────────

class _FakeRateQuery:
    def __init__(self, rows):
        self._rows = rows
        self.upserted = None

    def select(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def upsert(self, rows):
        self.upserted = rows
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _FakeRateClient:
    """`source_rows` stands in for risk_free_rate_source (what symbol to
    fetch), `existing_rows` for risk_free_rate (whether it has ever been
    synced) - two different tables, so a real client keys off which one
    was asked for the same way this fake does."""

    def __init__(self, source_rows, existing_rows=None):
        self.queries = {
            "risk_free_rate_source": _FakeRateQuery(source_rows),
            "risk_free_rate": _FakeRateQuery(existing_rows or []),
        }

    def table(self, name):
        return self.queries[name]


class RiskFreeRateSymbolTests(unittest.TestCase):
    def test_reads_the_configured_symbol(self):
        client_ = _FakeRateClient(source_rows=[{"symbol": "^IRX"}])
        self.assertEqual(_risk_free_rate_symbol(client_), "^IRX")

    def test_none_when_nothing_is_configured(self):
        """Not a Python default - a source is a database fact
        (risk_free_rate_source), the same way the tracked ETF universe is
        a fact about `etfs` rather than a hardcoded list."""
        client_ = _FakeRateClient(source_rows=[])
        self.assertIsNone(_risk_free_rate_symbol(client_))


class SyncRiskFreeRateTests(unittest.TestCase):
    def test_an_empty_table_gets_a_full_backfill(self):
        client_ = _FakeRateClient(source_rows=[{"symbol": "^IRX"}], existing_rows=[])
        with patch("scripts.fetch_daily.fetch_risk_free_rate_rows",
                    return_value=[{"date": "2024-06-06", "rate": 5.24}]) as mock_fetch:
            ok = sync_risk_free_rate(client_)

        mock_fetch.assert_called_once_with("^IRX", "max")
        self.assertTrue(ok)
        self.assertEqual(
            client_.queries["risk_free_rate"].upserted,
            [{"date": "2024-06-06", "rate": 5.24}],
        )

    def test_an_already_synced_table_gets_a_top_up(self):
        client_ = _FakeRateClient(
            source_rows=[{"symbol": "^IRX"}], existing_rows=[{"date": "2024-06-01"}]
        )
        with patch("scripts.fetch_daily.fetch_risk_free_rate_rows",
                    return_value=[]) as mock_fetch:
            sync_risk_free_rate(client_)

        mock_fetch.assert_called_once_with("^IRX", "5d")

    def test_a_fetch_failure_is_reported_not_raised(self):
        """main() folds this into its own exit code rather than crashing -
        one bad fetch must not take the rest of the run down with it."""
        client_ = _FakeRateClient(source_rows=[{"symbol": "^IRX"}], existing_rows=[])
        with patch("scripts.fetch_daily.fetch_risk_free_rate_rows",
                    side_effect=RuntimeError("boom")):
            ok = sync_risk_free_rate(client_)

        self.assertFalse(ok)

    def test_no_configured_source_is_skipped_not_failed(self):
        """Reachable only if risk_free_rate_source's seed row (from the
        migration) was deliberately removed - skipping quietly beats
        guessing at a default no code here is allowed to hardcode."""
        client_ = _FakeRateClient(source_rows=[], existing_rows=[])
        with patch("scripts.fetch_daily.fetch_risk_free_rate_rows") as mock_fetch:
            ok = sync_risk_free_rate(client_)

        mock_fetch.assert_not_called()
        self.assertTrue(ok)


# ── services.market_data.get_risk_free_rate ───────────────────────────────────

class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def gte(self, column, value):
        self._rows = [r for r in self._rows if r[column] >= value]
        return self

    def lte(self, column, value):
        self._rows = [r for r in self._rows if r[column] <= value]
        return self

    def range(self, start, end):
        self._rows = self._rows[start:end + 1]
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "risk_free_rate"
        return _FakeQuery(sorted(self._rows, key=lambda r: r["date"]))


def _rate_rows():
    return [
        {"date": "2024-06-06", "rate": 5.24},
        {"date": "2024-06-07", "rate": 5.26},
    ]


class GetRiskFreeRateTests(unittest.TestCase):
    def test_returns_the_series_oldest_first(self):
        db = _FakeClient(_rate_rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            result = get_risk_free_rate()

        self.assertEqual(result, _rate_rows())

    def test_a_window_filters_the_series(self):
        db = _FakeClient(_rate_rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            result = get_risk_free_rate(start="2024-06-07", end="2024-06-07")

        self.assertEqual(result, [{"date": "2024-06-07", "rate": 5.26}])

    def test_no_supabase_client_is_none_not_an_empty_list(self):
        """A caller must be able to tell "not synced/unreachable" from
        "genuinely nothing in this window" apart from an empty result -
        None is the former."""
        with patch("services.market_data.get_client_optional", return_value=None):
            self.assertIsNone(get_risk_free_rate())

    def test_an_empty_window_is_none_not_an_empty_list(self):
        db = _FakeClient(_rate_rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            result = get_risk_free_rate(start="2019-01-01", end="2019-01-02")

        self.assertIsNone(result)

    def test_a_query_failure_is_none_not_raised(self):
        class _BrokenClient:
            def table(self, name):
                raise RuntimeError("boom")

        with patch("services.market_data.get_client_optional", return_value=_BrokenClient()):
            self.assertIsNone(get_risk_free_rate())


# ── PortfolioIn.rate round-trips ────────────────────────────────────────────────

class SimulateRateFieldTests(unittest.TestCase):
    def _body(self, **overrides):
        body = {
            "holdings": [{"ticker": "AAPL", "weight": 100}],
            "value": 10_000,
            "start": "2020-01-01",
            "end": "2020-12-31",
        }
        body.update(overrides)
        return body

    def _closes(self):
        return pd.DataFrame(
            {"AAPL": [100.0, 200.0]},
            index=pd.to_datetime(["2020-01-02", "2020-06-01"]),
        )

    def test_an_override_changes_only_the_rate_and_what_depends_on_it(self):
        """The rate is a scoring assumption, not a property of the
        simulation itself (issue #112): an override changes
        metrics.riskFreeRate/riskFreeRateSource and whatever Sharpe/
        Sortino read from them, and nothing else about the run - every
        other series and metric stays byte-identical."""
        with (
            patch("services.portfolio.get_closes", return_value=self._closes()),
            patch("services.portfolio.get_dividends", return_value={}),
            patch("services.portfolio.tracked_tickers", return_value=set()),
            # Deterministic "no tracked rate" for the un-overridden run,
            # rather than depending on this test environment happening to
            # have no real Supabase configured.
            patch("services.portfolio.get_risk_free_rate", return_value=None),
        ):
            without = client.post("/api/portfolio/simulate", json=self._body())
            withrate = client.post("/api/portfolio/simulate", json=self._body(rate=4.2))

        self.assertEqual(without.status_code, 200)
        self.assertEqual(withrate.status_code, 200)
        without_body, withrate_body = without.json(), withrate.json()

        self.assertEqual(without_body["dates"], withrate_body["dates"])
        self.assertEqual(without_body["total"], withrate_body["total"])
        for key in ("cagr", "volatility", "maxDrawdown", "timeUnderWater", "shareUnderWater", "painIndex"):
            self.assertEqual(without_body["metrics"][key], withrate_body["metrics"][key])

        self.assertIsNone(without_body["metrics"]["riskFreeRate"])
        self.assertIsNone(without_body["metrics"]["riskFreeRateSource"])
        self.assertEqual(withrate_body["metrics"]["riskFreeRate"], 4.2)
        self.assertEqual(withrate_body["metrics"]["riskFreeRateSource"], "override")

    def test_omitting_it_is_still_the_default(self):
        with (
            patch("services.portfolio.get_closes", return_value=self._closes()),
            patch("services.portfolio.get_dividends", return_value={}),
            patch("services.portfolio.tracked_tickers", return_value=set()),
        ):
            resp = client.post("/api/portfolio/simulate", json=self._body())

        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
