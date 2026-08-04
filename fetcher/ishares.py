"""
iShares (BlackRock) holdings fetcher.

Automatically retrieves:
  1. The full list of US iShares ETFs (from ishares.com's product-screener
     JSON feed)
  2. The holdings of each ETF (stocks held + weights, when applicable)

No API key required: relies on ishares.com's and blackrock.com's public
endpoints.

Usage (from the repo root, deps in fetcher/requirements.txt):
    python fetcher/ishares.py
    python fetcher/ishares.py --output ishares_holdings.json --delay 1.5
    python fetcher/ishares.py --limit 5              # quick test on 5 ETFs
    python fetcher/ishares.py --tickers SOXX URTH    # only these funds

Endpoints (verified manually):
  - Fund list: GET /us/product-screener/product-screener-v3.1.jsn
    ?dcrPath=/templatedata/config/product-screener-v3/data/en/us-ishares
    /ishares-product-screener-backend-config&siteEntryPassthrough=true -
    the same JSON feed the site's product screener widget loads on page
    load; a dict keyed by numeric portfolio id, with localExchangeTicker/
    fundName/productPageUrl per fund. (Naively guessing the fund page's
    "download holdings" .ajax URL, the other pattern BlackRock has used
    historically, returns a bot-check interstitial instead of data - this
    JSON feed and the API below don't.)
  - Holdings: GET blackrock.com/varnish-api/.../get-fund-document
    ?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=us-ishares
    &locale=en_US&portfolioId=<id>&userType=individual&component=holdings -
    the API behind the fund page's "Detailed Holdings and Analytics" link.
    Omitting asOfDate (unlike the fund page's own link) still returns the
    latest holdings, so no need to track/guess a valid as-of date.

Location-based filtering (important): iShares CSVs reuse plain ticker
symbols across countries with no exchange suffix - e.g. "ROP" is both
Roper Technologies (US, NASDAQ) and Roche's Swiss listing in the same
file. Trusting the bare ticker would risk inserting one company's data
under another's identity once yfinance-validated downstream. Every row
carries its own Location and Asset Class, so holdings are kept only when
Location == "United States" and Asset Class == "Equity" - cash, futures,
collateral, and non-US listings are dropped before they ever leave this
fetcher.

Holdings files have a handful of fund-summary rows before the real header
row ("Ticker,Name,Sector,Asset Class,...", or just "Name,Sector,..." with
no Ticker column for fixed-income funds, e.g. AGG - detected the same way
as fetcher/vaneck.py's header search, then treated as a no-tickers note
rather than a crash.

Output schema: see fetcher/common.py - consumed by
backend/scripts/complete_database.py --holdings-json.
"""

import argparse
import csv
import time
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import requests

from common import HEADERS, EtfFund, EtfHolding, EtfResult, write_output

BASE_URL = "https://www.ishares.com"
FUND_LIST_URL = "https://www.ishares.com/us/product-screener/product-screener-v3.1.jsn"
FUND_LIST_PARAMS = {
    "dcrPath": "/templatedata/config/product-screener-v3/data/en/us-ishares/ishares-product-screener-backend-config",
    "siteEntryPassthrough": "true",
}
HOLDINGS_URL = "https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v1/get-fund-document"
HOLDINGS_PARAMS = {
    "appType": "PRODUCT_PAGE",
    "appSubType": "ISHARES",
    "targetSite": "us-ishares",
    "locale": "en_US",
    "userType": "individual",
    "component": "holdings",
}


def get_etf_list(payload: dict) -> List[EtfFund]:
    """
    Extract each ETF's ticker, name, and product URL from the
    product-screener JSON feed (a dict keyed by numeric portfolio id).

    holdings_url stores the fund's portfolio id (as a string), not an
    actual URL - fetch_etf_holdings builds the real request from it.

    Separated from the HTTP request so it can be unit-tested against a
    static payload, without network access.
    """
    funds: List[EtfFund] = []
    seen = set()
    for portfolio_id, entry in payload.items():
        ticker = (entry.get("localExchangeTicker") or "").strip()
        name = (entry.get("fundName") or "").strip()
        page_url = entry.get("productPageUrl")
        if not ticker or not page_url or ticker in seen:
            continue

        funds.append(EtfFund(
            ticker=ticker,
            name=name,
            product_url=urljoin(BASE_URL, page_url),
            holdings_url=str(portfolio_id),
        ))
        seen.add(ticker)

    if not funds:
        raise RuntimeError(
            "No ETF found in the product-screener feed. The API has probably changed."
        )
    return funds


def _find_header_row(lines: List[str], max_rows_to_scan: int = 15) -> Optional[int]:
    """
    iShares holdings files have a handful of fund-summary rows ("Fund
    Holdings as of,...", "Inception Date,...", ...) before the real header
    row. Locate it by looking for the row containing "ticker" or "name" as
    a column - equity funds have both, fixed-income funds (no per-holding
    ticker) only have "name".
    """
    for i, line in enumerate(lines[:max_rows_to_scan]):
        if not line.strip():
            continue
        cells = next(csv.reader([line]))
        lowered = {c.strip().lower() for c in cells}
        if "ticker" in lowered or "name" in lowered:
            return i
    return None


def parse_holdings_csv(csv_bytes: bytes) -> Tuple[List[EtfHolding], Optional[str]]:
    """
    Parse the binary content of a holdings CSV.
    Returns (list of holdings, optional note).
    Separated from the HTTP request to be unit-testable.
    """
    lines = csv_bytes.decode("utf-8-sig").splitlines()

    header_row_idx = _find_header_row(lines)
    if header_row_idx is None:
        return [], "Could not locate the header row in this holdings file."

    reader = csv.DictReader(lines[header_row_idx:])
    if reader.fieldnames is None:
        return [], "Could not locate the header row in this holdings file."

    ticker_col = next((c for c in reader.fieldnames if c.strip().lower() == "ticker"), None)
    if ticker_col is None:
        # Normal for a fixed-income / non-equity fund: no per-holding ticker.
        return [], "No 'Ticker' column in this file (probably a non-equity fund)."

    name_col = next((c for c in reader.fieldnames if c.strip().lower() == "name"), None)
    weight_col = next((c for c in reader.fieldnames if "weight" in c.strip().lower()), None)
    location_col = next((c for c in reader.fieldnames if c.strip().lower() == "location"), None)
    asset_class_col = next((c for c in reader.fieldnames if c.strip().lower() == "asset class"), None)

    holdings = []
    for row in reader:
        h_ticker = (row.get(ticker_col) or "").strip()
        if not h_ticker or h_ticker == "-":
            continue  # cash/futures/collateral lines have no ticker
        if location_col and (row.get(location_col) or "").strip() != "United States":
            continue  # avoid cross-country ticker collisions - see module docstring
        if asset_class_col and (row.get(asset_class_col) or "").strip() != "Equity":
            continue  # cash, futures, collateral - only real stock positions

        weight = None
        if weight_col and row.get(weight_col) not in (None, "", "-"):
            raw_weight = str(row[weight_col]).strip().replace("%", "")
            try:
                weight = float(raw_weight)
            except ValueError:
                weight = None

        holdings.append(EtfHolding(
            ticker=h_ticker,
            name=(row.get(name_col) or "").strip() if name_col else "",
            weight_pct=weight,
        ))
    return holdings, None


def fetch_etf_list(session: requests.Session) -> List[EtfFund]:
    resp = session.get(FUND_LIST_URL, headers=HEADERS, params=FUND_LIST_PARAMS, timeout=20)
    resp.raise_for_status()
    return get_etf_list(resp.json())


def fetch_etf_holdings(session: requests.Session, portfolio_id: str) -> Tuple[List[EtfHolding], Optional[str]]:
    params = {**HOLDINGS_PARAMS, "portfolioId": portfolio_id}
    resp = session.get(HOLDINGS_URL, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "csv" not in content_type and "text" not in content_type:
        raise ValueError(f"Unexpected response (Content-Type: {content_type}), not a valid CSV file.")

    return parse_holdings_csv(resp.content)


def main():
    parser = argparse.ArgumentParser(description="Scrape the list of US iShares ETFs and their holdings.")
    parser.add_argument("--output", default="ishares_holdings.json", help="Output JSON file")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay in seconds between holdings requests")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of ETFs processed (useful for testing)")
    parser.add_argument("--tickers", nargs="+", metavar="ID", help="Only fetch these fund tickers (e.g. SOXX URTH)")
    args = parser.parse_args()

    session = requests.Session()

    print("Fetching the iShares ETF list...")
    funds = fetch_etf_list(session)
    print(f"{len(funds)} ETFs found.")

    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers}
        funds = [f for f in funds if f.ticker.upper() in wanted]
        missing = wanted - {f.ticker.upper() for f in funds}
        if missing:
            print(f"Not in the iShares fund list: {', '.join(sorted(missing))}")
    if args.limit:
        funds = funds[: args.limit]

    results: List[EtfResult] = []
    for i, fund in enumerate(funds, start=1):
        print(f"[{i}/{len(funds)}] {fund.ticker} ({fund.name})...", end=" ", flush=True)
        try:
            holdings, note = fetch_etf_holdings(session, fund.holdings_url)
            results.append(EtfResult(etf_ticker=fund.ticker, etf_name=fund.name, holdings=holdings, note=note))
            if note:
                print(f"OK - {note}")
            else:
                print(f"OK ({len(holdings)} positions)")
        except Exception as exc:  # keep going even if one fund fails
            results.append(EtfResult(etf_ticker=fund.ticker, etf_name=fund.name, error=str(exc)))
            print(f"FAILED ({exc})")
        time.sleep(args.delay)

    write_output(results, args.output)

    ok = sum(1 for r in results if r.error is None)
    with_tickers = sum(1 for r in results if r.holdings)
    print(f"\nDone: {ok}/{len(results)} ETFs fetched without error, {with_tickers} with stock tickers extracted.")
    print(f"Output written to {args.output}")


if __name__ == "__main__":
    main()
