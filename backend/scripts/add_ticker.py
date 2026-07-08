"""
Manually add (or update) tickers in the Supabase `ticker` table.

This is the only way new tickers enter the tracked universe today - the
daily fetch job only ever refreshes tickers that already exist here.

Usage:
  python scripts/add_ticker.py NVDA AAPL MSFT
  python scripts/add_ticker.py "NVDA:NVIDIA" "AAPL:Apple Inc."
  python scripts/add_ticker.py --inactive OLDCO

Each argument is a ticker id, optionally followed by ":Full Name". If no
name is given, full metadata (name, sector, market cap, currency, exchange,
logo, website) is looked up via yfinance. If a name IS given, only
id/name/active are set - the metadata columns stay null until the next
scripts/fetch_daily.py run backfills them.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.supabase_client import get_client


def resolve_ticker_row(ticker_id: str) -> dict:
    """Full live metadata lookup, used when no name was given on the CLI."""
    from services.market_data import _get_stock_info_live

    info = _get_stock_info_live(ticker_id)
    return {
        "name": info["name"],
        "sector": info["sector"],
        "market_cap": info["marketCap"],
        "currency": info["currency"],
        "exchange": info["exchange"],
        "logo": info["logo"],
        "website": info["website"],
    }


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

        if name:
            row = {"id": ticker_id, "name": name, "active": not args.inactive}
        else:
            row = {"id": ticker_id, "active": not args.inactive, **resolve_ticker_row(ticker_id)}
        rows.append(row)

    # Note: a row only sets the columns it has values for (an explicit-name
    # add skips sector/market_cap/etc). PostgREST's upsert only touches
    # columns present in the payload, so this insert leaves those columns
    # (and last_fetch) at their defaults / untouched on conflict - backfilled
    # by the next fetch_daily.py run either way.
    client = get_client()
    client.table("ticker").upsert(rows).execute()

    for row in rows:
        status = "active" if row["active"] else "inactive"
        print(f"  {row['id']:8s} {row['name']:40s} [{status}]")
    print(f"\nUpserted {len(rows)} ticker(s).")


if __name__ == "__main__":
    main()
