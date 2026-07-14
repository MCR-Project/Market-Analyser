"""
Daily data-refresh job:
  - Fetches OHLCV history for every active ticker from yfinance and upserts
    it into Supabase, then stamps ticker.last_fetch.
  - Refreshes each active ticker's stock metadata (sector, market cap,
    currency, exchange, logo, website) so get_stock_info can be fully
    DB-read - market cap will be as fresh as this run.
  - Refreshes ETF metadata and holdings for every ETF in Supabase's `etfs`
    table (via market_data.list_etfs) into the etfs / etf_holdings tables,
    since holding weights drift over time.

Run manually with:   python scripts/fetch_daily.py
Runs on a schedule via .github/workflows/fetch-daily.yml.

Backfill vs top-up:
  - A ticker whose last_fetch is null gets a full-history backfill, back to
    the ticker's origin (null is the column default, so this is true for
    any ticker scripts/add_ticker.py has just added).
  - A ticker that's already been fetched gets a 5-day top-up, which covers
    weekends, holidays, and the odd missed run. (ticker, date) is the
    primary key on `prices`, so upserting is idempotent - re-fetched days
    just overwrite the same rows.

Which ETFs/stocks are tracked is entirely DB-driven, not a hardcoded list -
see market_data.list_etfs for ETFs, scripts/add_ticker.py for adding stocks
by hand, and scripts/complete_database.py for completing tracked ETFs
(metadata, constituent tickers, and their price history) in bulk.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import yfinance as yf

from services.market_data import (
    list_etfs,
    _get_etf_info_live,
    _get_etf_holdings_live,
    _get_stock_info_live,
)
from services.supabase_client import get_client

BACKFILL_PERIOD = "max"  # first-ever fetch for a ticker - full available history
TOPUP_PERIOD = "5d"      # every subsequent daily run


def _safe_float(v):
    if v is None:
        return None
    f = float(v)
    return round(f, 4) if not np.isnan(f) else None


def fetch_ticker_rows(ticker_id: str, period: str) -> list[dict]:
    hist = yf.Ticker(ticker_id).history(period=period, auto_adjust=False)
    if hist.empty:
        return []

    hist = hist.dropna(subset=["Close"])

    rows = []
    for idx, r in hist.iterrows():
        volume = r.get("Volume", 0)
        rows.append({
            "ticker": ticker_id,
            "date": idx.strftime("%Y-%m-%d"),
            "open": _safe_float(r.get("Open")),
            "high": _safe_float(r.get("High")),
            "low": _safe_float(r.get("Low")),
            "close": _safe_float(r.get("Close")),
            "volume": int(volume) if volume is not None and not np.isnan(volume) else 0,
            "dividends": _safe_float(r.get("Dividends")) or 0,
            "splits": _safe_float(r.get("Stock Splits")) or 0,
        })
    return rows


def sync_etfs(client, known_tickers: set[str]) -> list[str]:
    """Refresh etfs/etf_holdings for every ETF already tracked in Supabase
    (market_data.list_etfs) - this only ever refreshes existing rows, it
    doesn't add new ETFs (scripts/complete_database.py does that from the
    provider holdings files produced by the fetchers in fetcher/).

    The DB's etf_holdings rows are the full constituent list, so they are
    the source of truth for what an ETF contains - yfinance only exposes
    the top ~10 holdings, so the live call is used purely to refresh the
    weights it knows about and never shrinks the DB set. Full-portfolio
    weights refresh whenever the fetch-holdings workflow runs. Since
    etf_holdings.ticker has an FK to ticker.id, every constituent in the
    DB also gets its prices/metadata refreshed by the main loop below.

    The live (not DB-first) lookups are deliberate: this job is what keeps
    the DB fresh, so reading the DB back here would just write the same
    rows in a circle. Metadata fields that come back empty from yfinance
    are left out of the upsert so a flaky response can't blank out values
    the completion script already filled. aum is deliberately not stored -
    it's a live snapshot value; callers needing it use get_etf_info.

    Live holdings for tickers we don't track yet are skipped
    (etf_holdings.ticker has an FK to ticker.id) rather than failing the
    whole ETF - they'll show up once that ticker is added.
    """
    failed = []
    for etf_id in list_etfs():
        try:
            info = _get_etf_info_live(etf_id)
            live_holdings = _get_etf_holdings_live(etf_id)
        except Exception as e:
            print(f"  FAILED  {etf_id:8s} {e}")
            failed.append(etf_id)
            continue

        etf_row = {"id": etf_id}
        if info["name"] and info["name"] != etf_id:
            etf_row["name"] = info["name"]
        if info["cat"]:
            etf_row["cat"] = info["cat"]
        if info["desc"]:
            etf_row["desc"] = info["desc"]
        if len(etf_row) > 1:
            client.table("etfs").upsert(etf_row).execute()

        db_resp = client.table("etf_holdings").select("ticker").eq("etf_id", etf_id).execute()
        db_tickers = {row["ticker"] for row in db_resp.data}

        holding_rows = [
            {"etf_id": etf_id, "ticker": t, "weight": w}
            for t, w in live_holdings if t in known_tickers
        ]
        skipped = len(live_holdings) - len(holding_rows)
        if holding_rows:
            client.table("etf_holdings").upsert(holding_rows).execute()

        total = len(db_tickers | {r["ticker"] for r in holding_rows})
        note = f", {skipped} skipped (untracked ticker)" if skipped else ""
        print(f"  {etf_id:8s} {total:4d} holdings ({len(holding_rows)} weights refreshed){note}")

    return failed


def main():
    client = get_client()

    tickers_resp = client.table("ticker").select("id,last_fetch,active").execute()
    all_ticker_ids = {row["id"] for row in tickers_resp.data}
    active_tickers = sorted(
        (row for row in tickers_resp.data if row["active"]),
        key=lambda row: row["id"],
    )

    print("Syncing ETFs (market_data.list_etfs)...")
    etf_failures = sync_etfs(client, all_ticker_ids)

    if not active_tickers:
        print("\nNo active tickers found - add some with scripts/add_ticker.py first.")
        if etf_failures:
            sys.exit(1)
        return

    print("\nSyncing stock prices...")
    today = date.today().isoformat()
    total_rows = 0
    failed = list(etf_failures)

    for ticker in active_tickers:
        ticker_id = ticker["id"]
        period = BACKFILL_PERIOD if not ticker["last_fetch"] else TOPUP_PERIOD
        try:
            rows = fetch_ticker_rows(ticker_id, period)
        except Exception as e:
            print(f"  FAILED  {ticker_id:8s} {e}")
            failed.append(ticker_id)
            continue

        if rows:
            client.table("prices").upsert(rows).execute()
            total_rows += len(rows)

        client.table("ticker").update({"last_fetch": today}).eq("id", ticker_id).execute()

        metadata_note = ""
        try:
            info = _get_stock_info_live(ticker_id)
            client.table("ticker").update({
                "sector": info["sector"],
                "market_cap": info["marketCap"],
                "currency": info["currency"],
                "exchange": info["exchange"],
                "logo": info["logo"],
                "website": info["website"],
            }).eq("id", ticker_id).execute()
        except Exception as e:
            print(f"  METADATA FAILED  {ticker_id:8s} {e}")
            failed.append(ticker_id)
            metadata_note = ", metadata failed"

        print(f"  {ticker_id:8s} {len(rows):4d} rows  ({period}){metadata_note}")

    print(f"\nDone: {len(active_tickers)} tickers, {total_rows} price rows upserted.")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
