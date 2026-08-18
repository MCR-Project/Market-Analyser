"""
VanEck holdings fetcher.

Automatically retrieves:
  1. The full list of VanEck ETFs (from their "ETF & Mutual Fund Finder" page)
  2. The holdings of each ETF (stocks held + weights, when applicable)

No API key required: relies on vaneck.com's public pages. Talks to them
through fetcher/common.py's Playwright-backed BrowserSession rather than
plain requests - see that module's docstring.

Usage (from the repo root, deps in fetcher/requirements.txt, plus a
one-time `playwright install chromium`):
    python fetcher/vaneck.py
    python fetcher/vaneck.py --output vaneck_holdings.json --delay 1.5
    python fetcher/vaneck.py --limit 5   # quick test on 5 ETFs

URL pattern (verified manually on several funds, equity and fixed income):
    holdings_url = product_page_url + "downloads/holdings/"
  where product_page_url is the fund page link found in the fund finder
  page's data (e.g. .../investments/semiconductor-etf-smh/).

Note on fixed-income funds: their holdings file has no "Ticker" column
(bonds have no stock ticker) - the script detects this and returns an empty
holdings list for those funds instead of crashing.

Output schema: see fetcher/common.py - consumed by
backend/scripts/complete_database.py --holdings-json.
"""

import io
import json
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup

from common import BrowserSession, EtfFund, EtfHolding, run_fetcher

BASE_URL = "https://www.vaneck.com"
FUND_FINDER_URL = "https://www.vaneck.com/us/en/etf-mutual-fund-finder/"


def _parse_fund_search_data(soup: BeautifulSoup) -> List[EtfFund]:
    """
    The fund finder page embeds a <script class="fund-search-data"> holding a
    JSON blob with every fund (ticker, name, product URL), used by the site's
    JS search widget. The visible <table id="overview"> is filled client-side
    and is empty in the raw server HTML - which is why parsing the table's
    <tr> rows finds nothing.
    """
    script = soup.find("script", class_="fund-search-data")
    if script is None or not script.string:
        return []

    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        return []

    funds: List[EtfFund] = []
    seen = set()
    for entry in data:
        values = entry.get("Values") or []
        ticker = values[0].strip() if values and values[0] else ""
        name = values[1].strip() if len(values) > 1 and values[1] else ""
        url = entry.get("Url")
        # Entries without a ticker are SMAs / mutual funds / model
        # portfolios, not ETFs with a downloadable holdings file.
        if not ticker or not url or ticker in seen:
            continue

        product_url = urljoin(BASE_URL, url)
        if not product_url.endswith("/"):
            product_url += "/"
        holdings_url = product_url + "downloads/holdings/"

        funds.append(EtfFund(ticker=ticker, name=name, product_url=product_url, holdings_url=holdings_url))
        seen.add(ticker)

    return funds


def _parse_fund_table(soup: BeautifulSoup) -> List[EtfFund]:
    """Legacy fallback: parse the <table> in case it's ever server-rendered."""
    table = soup.find("table")
    if table is None:
        return []

    funds: List[EtfFund] = []
    seen = set()
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue  # header row

        ticker_link = cells[0].find("a")
        if ticker_link is None or not ticker_link.get("href"):
            continue

        ticker = ticker_link.get_text(strip=True)
        if not ticker or ticker in seen:
            continue

        name = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        product_url = urljoin(BASE_URL, ticker_link["href"])
        if not product_url.endswith("/"):
            product_url += "/"
        holdings_url = product_url + "downloads/holdings/"

        funds.append(EtfFund(ticker=ticker, name=name, product_url=product_url, holdings_url=holdings_url))
        seen.add(ticker)

    return funds


def get_etf_list(html: str) -> List[EtfFund]:
    """
    Extract each ETF's ticker, name, and product URL from the
    'ETF & Mutual Fund Finder' page.

    Tries the embedded JSON first (script.fund-search-data), which is the
    source of truth used by the site's search widget and is present in the
    raw HTML (unlike the visible table, rendered in JS). Falls back to
    parsing the <table> should the structure ever change.

    Separated from the HTTP request so it can be unit-tested against static
    HTML, without network access.
    """
    soup = BeautifulSoup(html, "lxml")

    funds = _parse_fund_search_data(soup)
    if not funds:
        funds = _parse_fund_table(soup)

    if not funds:
        raise RuntimeError(
            "No ETF found on the fund finder page (neither embedded JSON nor table). "
            "The site's structure has probably changed."
        )

    return funds


def _find_header_row(raw: pd.DataFrame, max_rows_to_scan: int = 10) -> Optional[int]:
    """
    VanEck holdings files have 1-2 title rows ("Daily Holdings (%) ...")
    before the real header row ("Number", "Ticker"/"Holding Name", ...).
    Locate it by looking for the row containing "Ticker" or "Holding Name".
    """
    for i in range(min(max_rows_to_scan, len(raw))):
        row_values = {str(v).strip().lower() for v in raw.iloc[i].tolist()}
        if "ticker" in row_values or "holding name" in row_values:
            return i
    return None


def parse_holdings_xlsx(xlsx_bytes: bytes) -> Tuple[List[EtfHolding], Optional[str]]:
    """
    Parse the binary content of a holdings XLSX file.
    Returns (list of holdings, optional note).
    Separated from the HTTP request to be unit-testable.
    """
    raw = pd.read_excel(io.BytesIO(xlsx_bytes), header=None)

    header_row_idx = _find_header_row(raw)
    if header_row_idx is None:
        return [], "Could not locate the header row in this holdings file."

    columns = [str(c).strip() for c in raw.iloc[header_row_idx].tolist()]
    df = raw.iloc[header_row_idx + 1 :].copy()
    df.columns = columns

    ticker_col = next((c for c in df.columns if c.lower() == "ticker"), None)
    name_col = next((c for c in df.columns if "holding" in c.lower() and "name" in c.lower()), None)
    weight_col = next((c for c in df.columns if "net assets" in c.lower()), None)

    if ticker_col is None:
        # Normal for a fixed-income / non-equity fund: no ticker column.
        return [], "No 'Ticker' column in this file (probably a non-equity fund)."

    excluded = {"nan", "--", "-usd cash-", "n/a", ""}
    holdings = []
    for _, row in df.iterrows():
        h_ticker = str(row[ticker_col]).strip()
        if h_ticker.lower() in excluded:
            continue
        weight = None
        if weight_col and pd.notna(row[weight_col]):
            raw_weight = str(row[weight_col]).strip().replace("%", "")
            try:
                weight = float(raw_weight)
            except ValueError:
                weight = None
        holdings.append(
            EtfHolding(
                ticker=h_ticker,
                name=str(row[name_col]).strip() if name_col and pd.notna(row[name_col]) else "",
                weight_pct=weight,
            )
        )
    return holdings, None


def fetch_etf_list(session: BrowserSession) -> List[EtfFund]:
    resp = session.get(FUND_FINDER_URL, timeout=20)
    resp.raise_for_status()
    return get_etf_list(resp.text)


def fetch_etf_holdings(session: BrowserSession, holdings_url: str) -> Tuple[List[EtfHolding], Optional[str]]:
    resp = session.get(holdings_url, timeout=20)
    resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if "spreadsheet" not in content_type and "excel" not in content_type:
        raise ValueError(f"Unexpected response (Content-Type: {content_type}), not a valid XLSX file.")

    return parse_holdings_xlsx(resp.content)


def main():
    run_fetcher(
        provider_name="VanEck",
        fetch_etf_list=fetch_etf_list,
        fetch_etf_holdings=fetch_etf_holdings,
        default_output="vaneck_holdings.json",
    )


if __name__ == "__main__":
    main()
