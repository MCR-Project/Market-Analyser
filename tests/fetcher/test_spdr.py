"""
Fixture-based parser tests for fetcher/spdr.py - get_etf_list and
parse_holdings_xlsx are both explicitly separated from the HTTP request
(see their docstrings) so they can be exercised here against static
fixtures, without network access.
"""

import json
from pathlib import Path

from spdr import get_etf_list, parse_holdings_xlsx

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "spdr"


def test_get_etf_list_extracts_funds_and_strips_non_ticker_symbols():
    payload = json.loads((FIXTURES / "etf_list.json").read_text(encoding="utf-8"))

    funds = get_etf_list(payload)

    tickers = {f.ticker: f for f in funds}
    # "GLD(R)" -> "GLD" trademark symbol's parens stripped (letters kept),
    # the missing-ticker entry dropped.
    assert set(tickers) == {"SPY", "GLDR"}
    assert tickers["SPY"].name == "SPDR S&P 500 ETF Trust"
    assert tickers["SPY"].holdings_url == (
        "https://www.ssga.com/us/en/intermediary/etfs/library-content"
        "/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
    )


def test_parse_holdings_xlsx_skips_title_rows_and_cash_line():
    xlsx_bytes = (FIXTURES / "holdings.xlsx").read_bytes()

    holdings, note = parse_holdings_xlsx(xlsx_bytes)

    assert note is None
    tickers = {h.ticker: h for h in holdings}
    assert set(tickers) == {"AAPL", "MSFT"}
    assert tickers["AAPL"].name == "Apple Inc"
    assert tickers["AAPL"].weight_pct == 7.05


def test_parse_holdings_xlsx_notes_a_fixed_income_fund_with_no_ticker_column():
    xlsx_bytes = (FIXTURES / "holdings_bond_fund.xlsx").read_bytes()

    holdings, note = parse_holdings_xlsx(xlsx_bytes)

    assert holdings == []
    assert note is not None
