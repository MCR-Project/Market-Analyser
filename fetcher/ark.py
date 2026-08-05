"""
ARK Invest holdings fetcher.

Automatically retrieves:
  1. The full list of ARK's exchange-traded ETFs (from ark-funds.com's site
     navigation, present on every page)
  2. The holdings of each ETF (stocks held + weights, when applicable)

No API key required: relies on ark-funds.com's public pages and the AJAX
endpoint behind their "Full Holdings CSV" download link. Talks to them
through fetcher/common.py's Playwright-backed BrowserSession rather than
plain requests - see that module's docstring.

Usage (from the repo root, deps in fetcher/requirements.txt, plus a
one-time `playwright install chromium`):
    python fetcher/ark.py
    python fetcher/ark.py --output ark_holdings.json --delay 1.5
    python fetcher/ark.py --limit 3           # quick test on 3 ETFs
    python fetcher/ark.py --tickers ARKK ARKQ # only these funds

Discovery (verified manually against ark-funds.com):
  - Every ark-funds.com page (homepage included) links to every fund's page
    at /funds/<slug> from a persistent site-nav component - that's the fund
    list, no separate finder API needed.
  - Each fund page (e.g. /funds/arkk) embeds a numeric fund id used to call
    /api/fund/holdings/<id>?fundHoldingData=<json>, the AJAX endpoint behind
    the page's "Top Holdings" widget. Its HTML response embeds the actual
    "Full Holdings CSV" download link (under assets.ark-funds.com), so the
    CSV filename never needs to be guessed - it's resolved per fund.
  - Not every fund page has a numeric fund id: ARK's non-exchange-traded
    products (e.g. the ARK Venture Fund interval fund, slug "arkvx") don't,
    and are skipped rather than treated as a fetch failure.
  - The holdings CSV is a plain, well-formed CSV (ticker/company/weight
    columns among others) with one quoted legal-disclaimer row appended at
    the end - pandas parses it straight into its own row, isolated in the
    first column, so it's naturally excluded by requiring a non-empty
    ticker (which also excludes cash and options-contract lines that have
    no stock ticker).

Output schema: see fetcher/common.py - consumed by
backend/scripts/complete_database.py --holdings-json.
"""

import argparse
import html
import io
import json
import re
import time
from typing import List, Optional, Tuple

import pandas as pd

from common import BrowserSession, EtfFund, EtfHolding, EtfResult, browser_session, write_output

FUND_LIST_URL = "https://ark-funds.com/"
FUND_PAGE_TEMPLATE = "https://ark-funds.com/funds/{slug}"
HOLDINGS_API_TEMPLATE = "https://ark-funds.com/api/fund/holdings/{fund_id}"
# The AJAX endpoint mirrors back link text/labels from this payload into the
# HTML fragment it returns - the values themselves don't matter, only that
# the fragment includes a "Full Holdings CSV" link for us to extract.
HOLDINGS_API_PAYLOAD = {
    "Heading": "Top 10 Holdings",
    "PdfLinkText": "Full Holdings PDF",
    "CsvLinkText": "Full Holdings CSV",
    "Link": {"Style": "", "Href": "", "Aria": "", "Target": "", "Text": ""},
}

FUND_SLUG_RE = re.compile(r'href="/funds/([a-z0-9\-]+)/?"')
FUND_ID_RE = re.compile(r"/api/fund/holdings/(\d+)")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
TICKER_PREFIX_RE = re.compile(r"^([A-Z]{2,5})\s*[|\-–—]")
CSV_LINK_RE = re.compile(r'href="(https://assets\.ark-funds\.com/[^"]+\.csv)"')


def _clean_fund_name(title: str, ticker: str) -> str:
    name = re.sub(r"\s*[|\-–—]\s*ark-funds\.com\s*$", "", title, flags=re.I).strip()
    name = re.sub(rf"^{re.escape(ticker)}\s*[|\-–—]\s*", "", name).strip()
    name = re.sub(r"^The\s+", "", name)
    return name or ticker


def get_fund_slugs(html: str) -> List[str]:
    """
    Extract every fund's URL slug from the persistent site navigation that's
    present on every ark-funds.com page (verified on both the homepage and
    a fund page).

    Separated from the HTTP request so it can be unit-tested against static
    HTML, without network access.
    """
    slugs = sorted(set(FUND_SLUG_RE.findall(html)))
    if not slugs:
        raise RuntimeError(
            "No fund slug found on the ARK site. The site's structure has probably changed."
        )
    return slugs


def get_fund_details(slug: str, html: str) -> Optional[EtfFund]:
    """
    Extract a fund's numeric id, ticker, and name from its ark-funds.com
    page. Returns None for products with no numeric fund id - these are
    ARK's non-exchange-traded products (e.g. the ARK Venture Fund interval
    fund), not ETFs with a downloadable holdings file.

    holdings_url carries the fund id (as a string), not an actual URL - the
    real CSV URL is only known after calling fetch_etf_holdings, which
    resolves it through the holdings AJAX endpoint.
    """
    fund_id_m = FUND_ID_RE.search(html)
    if fund_id_m is None:
        return None

    title_m = TITLE_RE.search(html)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else slug.upper()
    ticker_m = TICKER_PREFIX_RE.match(title)
    ticker = ticker_m.group(1) if ticker_m else slug.upper()

    return EtfFund(
        ticker=ticker,
        name=_clean_fund_name(title, ticker),
        product_url=FUND_PAGE_TEMPLATE.format(slug=slug),
        holdings_url=fund_id_m.group(1),
    )


def parse_holdings_csv(csv_bytes: bytes) -> Tuple[List[EtfHolding], Optional[str]]:
    """
    Parse the binary content of an ARK holdings CSV.
    Returns (list of holdings, optional note).
    Separated from the HTTP request to be unit-testable.
    """
    df = pd.read_csv(io.BytesIO(csv_bytes))

    ticker_col = next((c for c in df.columns if c.strip().lower() == "ticker"), None)
    name_col = next((c for c in df.columns if c.strip().lower() == "company"), None)
    weight_col = next((c for c in df.columns if "weight" in c.strip().lower()), None)

    if ticker_col is None:
        return [], "No 'ticker' column in this file."

    holdings = []
    for _, row in df.iterrows():
        h_ticker = row[ticker_col]
        # Covers cash/options-contract lines (no ticker) and the trailing
        # legal-disclaimer row, which pandas isolates in the first column.
        if pd.isna(h_ticker) or not str(h_ticker).strip():
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
                ticker=str(h_ticker).strip(),
                name=str(row[name_col]).strip() if name_col and pd.notna(row[name_col]) else "",
                weight_pct=weight,
            )
        )
    return holdings, None


def fetch_etf_list(session: BrowserSession, delay: float = 0.0) -> List[EtfFund]:
    resp = session.get(FUND_LIST_URL, timeout=20)
    resp.raise_for_status()
    slugs = get_fund_slugs(resp.text)

    funds: List[EtfFund] = []
    for slug in slugs:
        fund_resp = session.get(FUND_PAGE_TEMPLATE.format(slug=slug), timeout=20)
        fund_resp.raise_for_status()
        fund = get_fund_details(slug, fund_resp.text)
        if fund is not None:
            funds.append(fund)
        if delay:
            time.sleep(delay)
    return funds


def fetch_etf_holdings(session: BrowserSession, fund_id: str) -> Tuple[List[EtfHolding], Optional[str]]:
    resp = session.get(
        HOLDINGS_API_TEMPLATE.format(fund_id=fund_id),
        params={"fundHoldingData": json.dumps(HOLDINGS_API_PAYLOAD)},
        timeout=20,
    )
    resp.raise_for_status()

    csv_m = CSV_LINK_RE.search(resp.text)
    if csv_m is None:
        raise ValueError("No holdings CSV link found in the holdings widget response.")

    # Fund names with a "&" (e.g. ARKQ's "Tech. & Robotics") come back
    # HTML-entity-escaped ("&amp;") in the href - unescape before requesting.
    csv_url = html.unescape(csv_m.group(1))
    csv_resp = session.get(csv_url, timeout=30)
    csv_resp.raise_for_status()
    return parse_holdings_csv(csv_resp.content)


def main():
    parser = argparse.ArgumentParser(description="Scrape the list of ARK Invest ETFs and their holdings.")
    parser.add_argument("--output", default="ark_holdings.json", help="Output JSON file")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay in seconds between requests")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of ETFs processed (useful for testing)")
    parser.add_argument("--tickers", nargs="+", metavar="ID", help="Only fetch these fund tickers (e.g. ARKK ARKQ)")
    args = parser.parse_args()

    with browser_session() as session:
        print("Fetching the ARK ETF list...")
        funds = fetch_etf_list(session, delay=args.delay)
        print(f"{len(funds)} ETFs found.")

        if args.tickers:
            wanted = {t.strip().upper() for t in args.tickers}
            funds = [f for f in funds if f.ticker.upper() in wanted]
            missing = wanted - {f.ticker.upper() for f in funds}
            if missing:
                print(f"Not in the ARK fund list: {', '.join(sorted(missing))}")
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
