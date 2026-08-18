"""
Fixture-based parser tests for fetcher/invesco.py - get_etf_list and
parse_holdings_response are both explicitly separated from the HTTP request
(see their docstrings) so they can be exercised here against static
payloads, without network access.
"""

import json
from pathlib import Path

import pytest

from invesco import get_etf_list, parse_holdings_response

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "invesco"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_get_etf_list_extracts_funds_and_skips_missing_ticker():
    payload = _load("etf_list.json")

    funds = get_etf_list(payload)

    tickers = {f.ticker: f for f in funds}
    assert set(tickers) == {"QQQ", "RSP"}
    assert tickers["QQQ"].name == "Invesco QQQ Trust"
    assert tickers["QQQ"].product_url == "https://www.invesco.com/us/en/etfs/qqq.html"
    # holdings_url carries the CUSIP, not a real URL - the holdings endpoint
    # is keyed by CUSIP, not ticker.
    assert tickers["QQQ"].holdings_url == "46090E103"


def test_get_etf_list_raises_when_the_search_response_has_no_docs():
    with pytest.raises(RuntimeError):
        get_etf_list({"response": {"docs": []}})


def test_parse_holdings_response_keeps_only_us_dollar_common_stock():
    """Invesco's own `currency` field is always "USD" (the fund's reporting
    currency, not the security's) - only localCurrencyName reliably tells
    a genuine US listing (Apple/Microsoft) apart from a foreign one
    reusing a US-looking ticker (Roche's "ROP", also Roper Technologies'
    ticker) - and securityTypeName excludes the cash line."""
    payload = _load("holdings.json")

    holdings, note = parse_holdings_response(payload)

    assert note is None
    tickers = {h.ticker: h for h in holdings}
    assert set(tickers) == {"AAPL", "MSFT"}
    assert tickers["AAPL"].weight_pct == 8.75


def test_parse_holdings_response_notes_a_fund_with_no_holdings():
    payload = _load("holdings_empty.json")

    holdings, note = parse_holdings_response(payload)

    assert holdings == []
    assert note is not None
