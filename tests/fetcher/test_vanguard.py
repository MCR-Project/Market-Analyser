"""
Fixture-based parser tests for fetcher/vanguard.py - get_etf_list and
parse_holdings_response are both explicitly separated from the HTTP
request (see their docstrings) so they can be exercised here against
static payloads, without network access.
"""

import json
from pathlib import Path

from vanguard import get_etf_list, parse_holdings_response

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "vanguard"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_get_etf_list_keeps_only_etfs_with_a_ticker():
    payload = _load("fund_list.json")

    funds = get_etf_list(payload)

    tickers = {f.ticker: f for f in funds}
    # VTSAX (isETF=False) and the missing-ticker entry are both dropped.
    assert set(tickers) == {"VTI", "VXUS"}
    assert tickers["VTI"].name == "Vanguard Total Stock Market ETF"
    assert tickers["VTI"].product_url == (
        "https://investor.vanguard.com/investment-products/etfs/profile/vti"
    )
    # holdings_url stores the ticker itself - the holdings endpoint is
    # keyed directly by ticker.
    assert tickers["VTI"].holdings_url == "VTI"


def test_parse_holdings_response_keeps_only_us_isin_rows():
    """Same cross-country collision hazard as fetcher/ishares.py: VXUS's
    "ROP" is Roche Holding AG (Switzerland), not Roper Technologies (US) -
    only an ISIN starting with "US" is trusted, and an entity with no live
    ticker (delisted/illiquid) is dropped too."""
    payload = _load("holdings.json")

    holdings, note = parse_holdings_response(payload)

    assert note is None
    tickers = {h.ticker: h for h in holdings}
    assert set(tickers) == {"AAPL", "MSFT"}
    assert tickers["AAPL"].weight_pct == 6.15


def test_parse_holdings_response_notes_a_fund_with_no_stock_holdings():
    """A pure bond/cash fund (e.g. BSV) returns an empty entity list, not
    an error."""
    payload = _load("holdings_empty.json")

    holdings, note = parse_holdings_response(payload)

    assert holdings == []
    assert note is not None
