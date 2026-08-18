"""
Fixture-based parser tests for fetcher/ark.py - get_fund_slugs,
get_fund_details, and parse_holdings_csv are all explicitly separated from
the HTTP request (see their docstrings) so they can be exercised here
against static fixtures, without network access.
"""

from pathlib import Path

from ark import get_fund_details, get_fund_slugs, parse_holdings_csv

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ark"


def test_get_fund_slugs_extracts_and_dedupes():
    html = (FIXTURES / "fund_list.html").read_text(encoding="utf-8")

    slugs = get_fund_slugs(html)

    # "arkk" appears twice in the fixture's nav - deduped, and sorted.
    assert slugs == ["arkk", "arkq", "arkw"]


def test_get_fund_details_extracts_ticker_name_and_holdings_endpoint():
    html = (FIXTURES / "fund_page.html").read_text(encoding="utf-8")

    fund = get_fund_details("arkk", html)

    assert fund is not None
    assert fund.ticker == "ARKK"
    assert fund.name == "ARK Innovation ETF"
    assert fund.product_url == "https://ark-funds.com/funds/arkk"
    # holdings_url carries the numeric fund id, not a real URL.
    assert fund.holdings_url == "1001"


def test_get_fund_details_returns_none_for_a_non_exchange_traded_product():
    """ARK's interval funds (e.g. the ARK Venture Fund) have no numeric
    fund id and no downloadable holdings CSV - must be skipped, not
    treated as a fetch failure."""
    html = (FIXTURES / "fund_page_no_id.html").read_text(encoding="utf-8")

    assert get_fund_details("arkventure", html) is None


def test_parse_holdings_csv_extracts_holdings_and_skips_cash_and_disclaimer():
    csv_bytes = (FIXTURES / "holdings.csv").read_bytes()

    holdings, note = parse_holdings_csv(csv_bytes)

    assert note is None
    tickers = {h.ticker: h for h in holdings}
    # The cash line (no ticker) and the trailing legal-disclaimer row (no
    # ticker column populated) must both be excluded.
    assert set(tickers) == {"TSLA", "ROKU", "COIN"}
    assert tickers["TSLA"].name == "TESLA INC"
    assert tickers["TSLA"].weight_pct == 10.87
