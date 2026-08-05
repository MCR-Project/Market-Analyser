"""
Invesco holdings fetcher.

Automatically retrieves:
  1. The full list of open US Invesco ETFs (from dng-api.invesco.com's
     product search endpoint)
  2. The holdings of each ETF (stocks held + weights, when applicable)

No API key required - but unlike every other fetcher in this folder,
www.invesco.com blocks plain HTTP clients outright: every request gets
HTTP 406, including the bare HTML page, regardless of headers (verified:
requests with a full browser header set, and even Playwright's lightweight
BrowserSession.get(), both get 406 here - this isn't a missing-parameter
issue, it's bot/WAF protection at the domain level). A real page load
resolves whatever check is in place; a decoupled HTTP client, even one
that reuses cookies from a prior real page load, does not - so this
fetcher is the one place that needs BrowserSession.open_page() +
.fetch_json() (see fetcher/common.py) instead of the lightweight .get()
every other fetcher uses. One page load establishes things, then
fetch_json() reaches any dng-api URL from inside that page's own JS
engine, for as many funds as needed - no per-fund page reload.

Endpoints (found via manual browser network inspection):
  - Fund list: dng-api.invesco.com/product/search, a Solr-backed search
    endpoint. Filtering to accountType:ETF, contentType:Product,
    shareClassStatus:open and requesting fl=url,ticker,title,cusip returns
    every open US ETF (245 as of writing) in one call.
  - Holdings: dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/
    <cusip>/holdings/fund?idType=cusip&productType=ETF - keyed by CUSIP,
    not ticker (idType=ticker 500s for at least some funds; cusip is what
    the site's own product pages use).

Country filtering (important, same hazard as fetcher/ishares.py and
fetcher/vanguard.py): Invesco's international funds reuse plain ticker
symbols across countries - e.g. IMFL's "ROP" is Roche Holding AG
(Switzerland), the same Roper-Technologies-vs-Roche collision found via
iShares and Vanguard. Invesco's holdings rows carry no country/ISIN field,
and `currency` is always "USD" regardless of true domicile (it's the
fund's reporting currency, not the security's) - but `localCurrencyName`
is accurate ("Swiss Franc" for Roche, "US Dollar" for genuine US
listings), confirmed against QQQ (100% US, always "US Dollar" or None on
non-equity lines) and IMFL (foreign holdings correctly show their local
currency). Holdings are kept only when localCurrencyName == "US Dollar"
and securityTypeName == "Common Stock" (excluding cash/currency/futures/
collateral lines).

Usage (from the repo root, deps in fetcher/requirements.txt, plus a one-time
`playwright install chromium`):
    python fetcher/invesco.py
    python fetcher/invesco.py --output invesco_holdings.json --delay 1.5
    python fetcher/invesco.py --limit 5           # quick test on 5 ETFs
    python fetcher/invesco.py --tickers QQQ RSP   # only these funds

Output schema: see fetcher/common.py - consumed by
backend/scripts/complete_database.py --holdings-json.
"""

import argparse
import time
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from common import BrowserSession, EtfFund, EtfHolding, EtfResult, browser_session, write_output

BASE_URL = "https://www.invesco.com"
# Any real Invesco page works to establish the session - this one is a
# stable, generic entry point rather than a specific fund's product page.
WARM_UP_URL = "https://www.invesco.com/us/en/financial-products/etfs.html"

PRODUCT_SEARCH_URL = "https://dng-api.invesco.com/product/search"
PRODUCT_SEARCH_PARAMS = [
    ("fq", 'countryCode:"US"'),
    ("fq", 'language:"en_us"'),
    ("fq", 'accountType:"ETF"'),
    ("fq", 'contentType:"Product"'),
    ("fq", 'shareClassStatus:"open"'),
    ("q", "_suggest_:*"),
    ("fl", "url,ticker,title,cusip"),
    ("rows", "2000"),
    ("start", "0"),
]

HOLDINGS_URL_TEMPLATE = "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/{cusip}/holdings/fund"
HOLDINGS_PARAMS = {"idType": "cusip", "productType": "ETF"}


def get_etf_list(payload: dict) -> List[EtfFund]:
    """
    Extract each ETF's ticker, name, and product URL from the product
    search response (response.docs).

    holdings_url stores the fund's CUSIP - the holdings endpoint is keyed
    by CUSIP, not ticker.

    Separated from the HTTP request so it can be unit-tested against a
    static payload, without network access.
    """
    docs = (payload.get("response") or {}).get("docs") or []

    funds: List[EtfFund] = []
    seen = set()
    for doc in docs:
        ticker = (doc.get("ticker") or "").strip()
        cusip = (doc.get("cusip") or "").strip()
        url = doc.get("url")
        if not ticker or not cusip or not url or ticker in seen:
            continue

        funds.append(EtfFund(
            ticker=ticker,
            name=(doc.get("title") or "").strip(),
            product_url=urljoin(BASE_URL, url),
            holdings_url=cusip,
        ))
        seen.add(ticker)

    if not funds:
        raise RuntimeError(
            "No ETF found in the product search response. The API has probably changed."
        )
    return funds


def parse_holdings_response(payload: dict) -> Tuple[List[EtfHolding], Optional[str]]:
    """
    Parse a shareclasses/<cusip>/holdings/fund response.
    Returns (list of holdings, optional note).
    Separated from the HTTP request to be unit-testable.
    """
    rows = payload.get("holdings") or []
    if not rows:
        return [], "No holdings in this file (probably a non-equity fund)."

    holdings = []
    for row in rows:
        if (row.get("securityTypeName") or "").strip() != "Common Stock":
            continue  # cash, currency, futures, collateral - not real stock positions
        ticker = (row.get("ticker") or "").strip()
        if not ticker:
            continue
        if (row.get("localCurrencyName") or "").strip() != "US Dollar":
            continue  # avoid cross-country ticker collisions - see module docstring

        weight = row.get("percentageOfTotalNetAssets")
        try:
            weight = float(weight) if weight is not None else None
        except (TypeError, ValueError):
            weight = None

        holdings.append(EtfHolding(
            ticker=ticker,
            name=(row.get("issuerName") or "").strip(),
            weight_pct=weight,
        ))
    return holdings, None


def fetch_etf_list(session: BrowserSession) -> List[EtfFund]:
    data = session.fetch_json(PRODUCT_SEARCH_URL, params=PRODUCT_SEARCH_PARAMS)
    return get_etf_list(data)


def fetch_etf_holdings(session: BrowserSession, cusip: str) -> Tuple[List[EtfHolding], Optional[str]]:
    data = session.fetch_json(HOLDINGS_URL_TEMPLATE.format(cusip=cusip), params=HOLDINGS_PARAMS)
    return parse_holdings_response(data)


def main():
    parser = argparse.ArgumentParser(description="Scrape the list of Invesco ETFs and their holdings.")
    parser.add_argument("--output", default="invesco_holdings.json", help="Output JSON file")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay in seconds between holdings requests")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of ETFs processed (useful for testing)")
    parser.add_argument("--tickers", nargs="+", metavar="ID", help="Only fetch these fund tickers (e.g. QQQ RSP)")
    args = parser.parse_args()

    with browser_session() as session:
        print("Loading an Invesco page to establish a session...")
        session.open_page(WARM_UP_URL)

        print("Fetching the Invesco ETF list...")
        funds = fetch_etf_list(session)
        print(f"{len(funds)} ETFs found.")

        if args.tickers:
            wanted = {t.strip().upper() for t in args.tickers}
            funds = [f for f in funds if f.ticker.upper() in wanted]
            missing = wanted - {f.ticker.upper() for f in funds}
            if missing:
                print(f"Not in the Invesco fund list: {', '.join(sorted(missing))}")
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
