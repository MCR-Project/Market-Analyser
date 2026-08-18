"""
State Street SPDR holdings fetcher.

Automatically retrieves:
  1. The full list of US SPDR ETFs (from ssga.com's fund-finder JSON API)
  2. The holdings of each ETF (stocks held + weights, when applicable)

No API key required: relies on ssga.com's public endpoints. Talks to them
through fetcher/common.py's Playwright-backed BrowserSession rather than
plain requests - see that module's docstring.

Usage (from the repo root, deps in fetcher/requirements.txt, plus a
one-time `playwright install chromium`):
    python fetcher/spdr.py
    python fetcher/spdr.py --output spdr_holdings.json --delay 1.5
    python fetcher/spdr.py --limit 5          # quick test on 5 ETFs
    python fetcher/spdr.py --tickers SPY MDY  # only these funds

Endpoints (verified manually):
  - Fund list: GET /bin/v1/ssmp/fund/fundfinder?country=us&language=en
    &role=intermediary&product=etfs&ui=fund-finder - the JSON feed behind
    the site's fund-finder widget; funds live under data.funds.etfs.datas
    with fundTicker / fundName / fundUri fields.
  - Holdings: GET /us/en/intermediary/etfs/library-content/products/
    fund-data/etfs/us/holdings-daily-us-en-<ticker>.xlsx (lowercase ticker).

Holdings files have 3 title rows ("Fund Name:", "Ticker Symbol:",
"Holdings: As of ...") before the header row ("Name", "Ticker",
"Identifier", "SEDOL", "Weight", ...) and a legal-disclaimer footer.
Fixed-income funds (e.g. JNK) have no "Ticker" column - detected and
returned as an empty holdings list with a note instead of crashing.

Output schema: see fetcher/common.py - consumed by
backend/scripts/complete_database.py --holdings-json.
"""

import io
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import pandas as pd

from common import BrowserSession, EtfFund, EtfHolding, run_fetcher

BASE_URL = "https://www.ssga.com"
FUND_FINDER_URL = (
    "https://www.ssga.com/bin/v1/ssmp/fund/fundfinder"
    "?country=us&language=en&role=intermediary&product=etfs&ui=fund-finder"
)
HOLDINGS_URL_TEMPLATE = (
    "https://www.ssga.com/us/en/intermediary/etfs/library-content"
    "/products/fund-data/etfs/us/holdings-daily-us-en-{ticker}.xlsx"
)


def get_etf_list(payload: dict) -> List[EtfFund]:
    """
    Extract each ETF's ticker, name, and product URL from the fund-finder
    JSON payload (data.funds.etfs.datas).

    Separated from the HTTP request so it can be unit-tested against a
    static payload, without network access.
    """
    try:
        entries = payload["data"]["funds"]["etfs"]["datas"]
    except (KeyError, TypeError):
        raise RuntimeError(
            "Unexpected fund-finder JSON layout (no data.funds.etfs.datas). "
            "The API has probably changed."
        )

    funds: List[EtfFund] = []
    seen = set()
    for entry in entries:
        # Some fundTicker values carry a trailing (R)/(TM) symbol (e.g.
        # "GLD(R)") that would 404 the holdings URL - keep ticker chars only.
        raw_ticker = (entry.get("fundTicker") or "").strip()
        ticker = "".join(ch for ch in raw_ticker if ch.isascii() and (ch.isalnum() or ch in ".-"))
        name = (entry.get("fundName") or "").strip()
        uri = entry.get("fundUri") or ""
        if not ticker or ticker in seen:
            continue

        funds.append(EtfFund(
            ticker=ticker,
            name=name,
            product_url=urljoin(BASE_URL, uri),
            holdings_url=HOLDINGS_URL_TEMPLATE.format(ticker=ticker.lower()),
        ))
        seen.add(ticker)

    if not funds:
        raise RuntimeError("No ETF found in the fund-finder payload.")

    return funds


def _find_header_row(raw: pd.DataFrame, max_rows_to_scan: int = 10) -> Optional[int]:
    """
    SPDR holdings files have 3 title rows ("Fund Name:", "Ticker Symbol:",
    "Holdings: As of ...") and a blank line before the real header row
    ("Name", "Ticker", ..., "Weight", ...). Locate it by looking for the
    row containing both "name" and "weight".
    """
    for i in range(min(max_rows_to_scan, len(raw))):
        row_values = {str(v).strip().lower() for v in raw.iloc[i].tolist()}
        if "name" in row_values and "weight" in row_values:
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
    name_col = next((c for c in df.columns if c.lower() == "name"), None)
    weight_col = next((c for c in df.columns if c.lower() == "weight"), None)

    if ticker_col is None:
        # Normal for a fixed-income / non-equity fund: no ticker column.
        return [], "No 'Ticker' column in this file (probably a non-equity fund)."

    # 'nan' also drops the blank spacer rows and the legal-disclaimer footer.
    excluded = {"nan", "--", "-", "n/a", "", "cash_usd", "usd"}
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
    return get_etf_list(resp.json())


def fetch_etf_holdings(session: BrowserSession, holdings_url: str) -> Tuple[List[EtfHolding], Optional[str]]:
    resp = session.get(holdings_url, timeout=30)
    resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if "spreadsheet" not in content_type and "excel" not in content_type:
        raise ValueError(f"Unexpected response (Content-Type: {content_type}), not a valid XLSX file.")

    return parse_holdings_xlsx(resp.content)


def main():
    run_fetcher(
        provider_name="SPDR",
        fetch_etf_list=fetch_etf_list,
        fetch_etf_holdings=fetch_etf_holdings,
        default_output="spdr_holdings.json",
        tickers_example="SPY MDY",
    )


if __name__ == "__main__":
    main()
