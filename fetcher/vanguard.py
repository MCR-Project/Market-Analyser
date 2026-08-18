"""
Vanguard holdings fetcher.

Automatically retrieves:
  1. The full list of Vanguard ETFs (from investor.vanguard.com's fund-list
     API)
  2. The stock holdings of each ETF (stocks held + weights, when applicable)

No API key required: relies on investor.vanguard.com's public endpoints -
the same ones the fund profile pages themselves call. Talks to them
through fetcher/common.py's Playwright-backed BrowserSession rather than
plain requests - see that module's docstring.

Usage (from the repo root, deps in fetcher/requirements.txt, plus a
one-time `playwright install chromium`):
    python fetcher/vanguard.py
    python fetcher/vanguard.py --output vanguard_holdings.json --delay 1.5
    python fetcher/vanguard.py --limit 5             # quick test on 5 ETFs
    python fetcher/vanguard.py --tickers VTI VXUS    # only these funds

Endpoints (verified manually against real network traffic on a fund profile
page):
  - Fund list: GET /investment-products/list/funddetail/all - returns every
    Vanguard fund (mutual funds and ETFs together); each entry's
    profile.isETF flags the ones we want, and profile.ticker/longName are
    used directly - no separate id lookup needed.
  - Holdings: GET /vmf/api/<ticker>/portfolio-holding/stock.json
    ?start=1&count=10000 - equity holdings only (Vanguard splits holdings
    into stock/bond/short-term-reserve/currency/derivative/commodity/
    money-market files; we only need stock.json). A single request with a
    generous count covers every fund seen so far (VTI ~3.5k, VXUS ~8.7k
    holdings) - no pagination loop needed. A pure bond/cash fund (e.g. BSV)
    just returns size: 0, not an error.

Country filtering (important, same hazard as fetcher/ishares.py): Vanguard's
international funds hold securities that reuse plain ticker symbols across
countries - e.g. VXUS's "ROP" is Roche Holding AG (Switzerland), not Roper
Technologies (US, NASDAQ), the same collision fetcher/ishares.py found via
iShares' Location column. Vanguard's holdings payload has no such column,
but every row carries an ISIN, whose first two characters are the ISO
3166-1 country code - holdings are kept only when isin starts with "US",
so non-US listings (and the collision risk they carry) never reach the
completion pipeline.

Output schema: see fetcher/common.py - consumed by
backend/scripts/complete_database.py --holdings-json.
"""

from typing import List, Optional, Tuple

from common import BrowserSession, EtfFund, EtfHolding, run_fetcher

BASE_URL = "https://investor.vanguard.com"
FUND_LIST_URL = "https://investor.vanguard.com/investment-products/list/funddetail/all"
HOLDINGS_URL_TEMPLATE = "https://investor.vanguard.com/vmf/api/{ticker}/portfolio-holding/stock.json"
HOLDINGS_PARAMS = {"start": 1, "count": 10000}


def get_etf_list(payload: dict) -> List[EtfFund]:
    """
    Extract each ETF's ticker, name, and product URL from the fund-detail
    feed (a combined list of every Vanguard fund - mutual funds and ETFs).

    holdings_url stores the ticker itself - the holdings endpoint is keyed
    directly by ticker, no separate id resolution needed.

    Separated from the HTTP request so it can be unit-tested against a
    static payload, without network access.
    """
    entities = (payload.get("fund") or {}).get("entity") or []

    funds: List[EtfFund] = []
    seen = set()
    for entry in entities:
        profile = entry.get("profile") or {}
        if not profile.get("isETF"):
            continue
        ticker = (profile.get("ticker") or "").strip()
        if not ticker or ticker in seen:
            continue

        funds.append(EtfFund(
            ticker=ticker,
            name=(profile.get("longName") or "").strip(),
            product_url=f"{BASE_URL}/investment-products/etfs/profile/{ticker.lower()}",
            holdings_url=ticker,
        ))
        seen.add(ticker)

    if not funds:
        raise RuntimeError(
            "No ETF found in the fund-detail feed. The API has probably changed."
        )
    return funds


def parse_holdings_response(payload: dict) -> Tuple[List[EtfHolding], Optional[str]]:
    """
    Parse a portfolio-holding/stock.json response.
    Returns (list of holdings, optional note).
    Separated from the HTTP request to be unit-testable.
    """
    rows = (payload.get("fund") or {}).get("entity") or []
    if not rows:
        return [], "No stock holdings in this file (probably a non-equity fund)."

    holdings = []
    for row in rows:
        ticker = (row.get("ticker") or "").strip()
        if not ticker:
            continue  # delisted/illiquid entities with no live ticker
        isin = (row.get("isin") or "").strip()
        if not isin.startswith("US"):
            continue  # avoid cross-country ticker collisions - see module docstring

        weight = None
        raw_weight = row.get("percentWeight")
        if raw_weight not in (None, ""):
            try:
                weight = float(str(raw_weight).strip().replace("%", ""))
            except ValueError:
                weight = None

        holdings.append(EtfHolding(
            ticker=ticker,
            name=(row.get("longName") or "").strip(),
            weight_pct=weight,
        ))
    return holdings, None


def fetch_etf_list(session: BrowserSession) -> List[EtfFund]:
    resp = session.get(FUND_LIST_URL, timeout=30)
    resp.raise_for_status()
    return get_etf_list(resp.json())


def fetch_etf_holdings(session: BrowserSession, ticker: str) -> Tuple[List[EtfHolding], Optional[str]]:
    resp = session.get(
        HOLDINGS_URL_TEMPLATE.format(ticker=ticker),
        params=HOLDINGS_PARAMS,
        timeout=20,
    )
    resp.raise_for_status()
    return parse_holdings_response(resp.json())


def main():
    run_fetcher(
        provider_name="Vanguard",
        fetch_etf_list=fetch_etf_list,
        fetch_etf_holdings=fetch_etf_holdings,
        default_output="vanguard_holdings.json",
        tickers_example="VTI VXUS",
    )


if __name__ == "__main__":
    main()
