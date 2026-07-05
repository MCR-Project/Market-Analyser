"""
Daily data-refresh job - fetches OHLCV history for every active ticker from
yfinance and upserts it into Supabase, then stamps ticker.last_fetch.

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
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import yfinance as yf

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


def main():
    client = get_client()

    tickers_resp = client.table("ticker").select("id,last_fetch").eq("active", True).execute()
    tickers = sorted(tickers_resp.data, key=lambda row: row["id"])

    if not tickers:
        print("No active tickers found - add some with scripts/add_ticker.py first.")
        return

    today = date.today().isoformat()
    total_rows = 0
    failed = []

    for ticker in tickers:
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
        print(f"  {ticker_id:8s} {len(rows):4d} rows  ({period})")

    print(f"\nDone: {len(tickers)} tickers, {total_rows} price rows upserted.")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
