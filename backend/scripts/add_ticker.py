"""
Manually add (or update) tickers in the Supabase `ticker` table.

This is the only way new tickers enter the tracked universe today - the
daily fetch job only ever refreshes tickers that already exist here.

Usage:
  python scripts/add_ticker.py NVDA AAPL MSFT
  python scripts/add_ticker.py "NVDA:NVIDIA" "AAPL:Apple Inc."
  python scripts/add_ticker.py --inactive OLDCO

Each argument is a ticker id, optionally followed by ":Full Name". If no
name is given, it's looked up via yfinance.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.supabase_client import get_client


def resolve_name(ticker_id: str) -> str:
    import yfinance as yf

    info = yf.Ticker(ticker_id).info or {}
    return info.get("longName") or info.get("shortName") or ticker_id


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "tickers",
        nargs="+",
        help='Ticker id, optionally "ID:Full Name" (e.g. NVDA or "NVDA:NVIDIA")',
    )
    parser.add_argument(
        "--inactive",
        action="store_true",
        help="Insert as inactive (excluded from the daily fetch job)",
    )
    args = parser.parse_args()

    rows = []
    for raw in args.tickers:
        if ":" in raw:
            ticker_id, name = raw.split(":", 1)
            name = name.strip()
        else:
            ticker_id, name = raw, None
        ticker_id = ticker_id.strip().upper()
        if not name:
            name = resolve_name(ticker_id)
        rows.append({"id": ticker_id, "name": name, "active": not args.inactive})

    # Note: rows never sets `last_fetch`. PostgREST's upsert only touches
    # columns present in the payload, so this insert leaves brand-new
    # tickers at the column default (null — backfill on the next fetch_daily
    # run) while leaving an existing ticker's last_fetch untouched.
    client = get_client()
    client.table("ticker").upsert(rows).execute()

    for row in rows:
        status = "active" if row["active"] else "inactive"
        print(f"  {row['id']:8s} {row['name']:40s} [{status}]")
    print(f"\nUpserted {len(rows)} ticker(s).")


if __name__ == "__main__":
    main()
