"""
Fixture-based parser tests for fetcher/ishares.py - get_etf_list and
parse_holdings_csv are both explicitly separated from the HTTP request (see
their docstrings) so they can be exercised here against static fixtures,
without network access.
"""

import json
from pathlib import Path

from ishares import get_etf_list, parse_holdings_csv

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ishares"


def test_get_etf_list_extracts_funds_and_skips_missing_ticker():
    payload = json.loads((FIXTURES / "etf_list.json").read_text(encoding="utf-8"))

    funds = get_etf_list(payload)

    tickers = {f.ticker: f for f in funds}
    assert set(tickers) == {"SOXX", "URTH"}
    assert tickers["SOXX"].name == "iShares Semiconductor ETF"
    assert tickers["SOXX"].product_url == (
        "https://www.ishares.com/us/products/239716/ishares-phlx-semiconductor-etf"
    )
    # holdings_url carries the numeric portfolio id, not a real URL.
    assert tickers["SOXX"].holdings_url == "239716"


def test_parse_holdings_csv_keeps_only_us_equity_rows():
    """Same cross-country collision hazard the module docstring calls
    out - Roche's Swiss listing shares the "ROP" ticker with Roper
    Technologies - so a non-US Location row must be dropped even though it
    has a plausible-looking ticker, and the cash line must be dropped via
    its "-" ticker placeholder."""
    csv_bytes = (FIXTURES / "holdings.csv").read_bytes()

    holdings, note = parse_holdings_csv(csv_bytes)

    assert note is None
    tickers = {h.ticker: h for h in holdings}
    assert set(tickers) == {"NVDA", "AVGO"}
    assert tickers["NVDA"].name == "NVIDIA Corp"
    assert tickers["NVDA"].weight_pct == 9.85


def test_parse_holdings_csv_notes_a_fixed_income_fund_with_no_ticker_column():
    csv_bytes = (FIXTURES / "holdings_bond_fund.csv").read_bytes()

    holdings, note = parse_holdings_csv(csv_bytes)

    assert holdings == []
    assert note is not None
