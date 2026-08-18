"""
Fixture-based parser tests for fetcher/vaneck.py - get_etf_list and
parse_holdings_xlsx are both explicitly separated from the HTTP request
(see their docstrings) so they can be exercised here against static
fixtures, without network access.
"""

from pathlib import Path

import pytest

from vaneck import get_etf_list, parse_holdings_xlsx

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "vaneck"


def test_get_etf_list_prefers_the_embedded_json_and_skips_missing_ticker():
    html = (FIXTURES / "fund_finder.html").read_text(encoding="utf-8")

    funds = get_etf_list(html)

    tickers = {f.ticker: f for f in funds}
    assert set(tickers) == {"SMH", "MOAT"}
    assert tickers["SMH"].name == "VanEck Semiconductor ETF"
    assert tickers["SMH"].product_url == (
        "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/overview/"
    )
    assert tickers["SMH"].holdings_url == (
        "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/overview/"
        "downloads/holdings/"
    )


def test_get_etf_list_falls_back_to_the_table_when_json_is_absent():
    """The visible <table> is only ever populated client-side in real
    pages, but get_etf_list must still cope if the embedded JSON script
    tag is ever missing."""
    html = (FIXTURES / "fund_finder_table_fallback.html").read_text(encoding="utf-8")

    funds = get_etf_list(html)

    tickers = {f.ticker for f in funds}
    assert tickers == {"SMH", "MOAT"}


def test_get_etf_list_raises_when_neither_source_has_funds():
    with pytest.raises(RuntimeError):
        get_etf_list("<html><body><table></table></body></html>")


def test_parse_holdings_xlsx_skips_title_rows_and_cash_line():
    xlsx_bytes = (FIXTURES / "holdings.xlsx").read_bytes()

    holdings, note = parse_holdings_xlsx(xlsx_bytes)

    assert note is None
    tickers = {h.ticker: h for h in holdings}
    assert set(tickers) == {"NVDA", "AVGO"}
    assert tickers["NVDA"].name == "NVIDIA Corp"
    assert tickers["NVDA"].weight_pct == 19.86


def test_parse_holdings_xlsx_notes_a_fixed_income_fund_with_no_ticker_column():
    xlsx_bytes = (FIXTURES / "holdings_bond_fund.xlsx").read_bytes()

    holdings, note = parse_holdings_xlsx(xlsx_bytes)

    assert holdings == []
    assert note is not None
