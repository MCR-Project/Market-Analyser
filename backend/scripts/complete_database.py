"""
Complete the tracked universe in Supabase from financedatabase + yfinance.

Where scripts/add_ticker.py adds one ticker by hand and scripts/fetch_daily.py
only refreshes rows that already exist, this script fills the gaps around the
ETFs already tracked in the `etfs` table:

  1. Load the financedatabase catalogs (fd.ETFs() / fd.Equities()) - free,
     no API key, downloaded as DataFrames at startup.
  2. Complete ETF metadata: intersect the fd ETF catalog with the ids in the
     `etfs` table and fill missing name/cat/desc (fd has rich per-ETF
     metadata but no constituent lists).
  3. Retrieve each ETF's constituents via yfinance top holdings (the same
     live path fetch_daily.py syncs from - top ~10 per fund).
  4. For every constituent not yet in the `ticker` table, validate it two
     ways - present in the fd equities catalog AND yfinance returns price
     history - then insert it with fd metadata (name, sector, currency,
     exchange, website) plus numeric market cap / logo from yfinance, and
     backfill its full price history into `prices`.
  5. Re-upsert `etf_holdings` so holdings previously skipped by the
     etf_holdings.ticker -> ticker.id FK constraint now land.

Only columns that already exist in the DB are written - no new columns, no
schema changes, and AUM stays a live-only value (see market_data._compute_aum).

Every write is an upsert keyed on the table's primary key, so re-running is
idempotent: a second run finds 0 new tickers and changes nothing. Newly
inserted tickers get last_fetch stamped, so the next fetch_daily.py run gives
them a normal 5-day top-up (not another full backfill) and takes over their
metadata refresh. If a price backfill fails halfway, last_fetch stays null
and the next daily run re-backfills that ticker automatically.

Run manually with:   python scripts/complete_database.py
                     python scripts/complete_database.py --dry-run
                     python scripts/complete_database.py --etfs SPY QQQ
                     python scripts/complete_database.py --force-etf-metadata
Runs on demand via .github/workflows/complete-database.yml (manual dispatch).
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import financedatabase as fd
import pandas as pd

from scripts.fetch_daily import BACKFILL_PERIOD, fetch_ticker_rows
from services.market_data import (
    _get_etf_info_live,
    _get_etf_holdings_live,
    _get_stock_info_live,
    list_etfs,
)
from services.supabase_client import get_client

PRICE_UPSERT_CHUNK = 5000  # a "max" backfill can exceed 10k rows per ticker


def _clean(v):
    """financedatabase DataFrames hold NaN for missing fields - PostgREST
    payloads need None instead."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return v


def _swap_convention(symbol: str) -> str:
    """Bridge share-class conventions: our canonical ids use dots (BRK.B,
    per market_data.DUPLICATE_TICKERS) while catalogs may use dashes."""
    if "." in symbol:
        return symbol.replace(".", "-")
    return symbol.replace("-", ".")


def fd_lookup(catalog: pd.DataFrame, symbol: str) -> pd.Series | None:
    """Exact symbol lookup in a fd catalog, retrying the dot/dash-swapped
    variant on a miss. Returns None if the symbol isn't in the catalog."""
    for sym in (symbol, _swap_convention(symbol)):
        if sym in catalog.index:
            row = catalog.loc[sym]
            if isinstance(row, pd.DataFrame):  # duplicate index entries
                row = row.iloc[0]
            return row
    return None


def load_fd_catalogs() -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        etfs = fd.ETFs().select()
        equities = fd.Equities().select()
    except Exception as e:
        raise SystemExit(f"Failed to load the financedatabase catalogs: {e}")
    print(f"Loaded financedatabase catalogs: {len(etfs)} ETFs, {len(equities)} equities.")
    return etfs, equities


def complete_etf_metadata(client, fd_etfs, etf_ids, dry_run, force) -> tuple[int, list[str]]:
    """Fill missing name/cat/desc on `etfs` rows from the fd ETF catalog,
    falling back to a live yfinance lookup for ETFs fd doesn't know.

    A field counts as missing when it's null/empty (or, for name, still equal
    to the raw id). --force-etf-metadata overwrites from fd even when set.
    """
    resp = client.table("etfs").select("id,name,cat,desc").in_("id", etf_ids).execute()
    current = {row["id"]: row for row in resp.data}

    updated, failed = 0, []
    for etf_id in etf_ids:
        row = current.get(etf_id, {"id": etf_id, "name": None, "cat": None, "desc": None})
        fd_row = fd_lookup(fd_etfs, etf_id)

        fd_values = {}
        if fd_row is not None:
            fd_values = {
                "name": _clean(fd_row.get("name")),
                "cat": _clean(fd_row.get("category")) or _clean(fd_row.get("category_group")),
                "desc": _clean(fd_row.get("summary")),
            }

        def missing(field):
            value = row.get(field)
            return not value or (field == "name" and value == etf_id)

        payload = {
            field: value
            for field, value in fd_values.items()
            if value and (force or missing(field))
        }

        still_missing = [f for f in ("name", "cat", "desc") if missing(f) and f not in payload]
        if still_missing:
            try:
                live = _get_etf_info_live(etf_id)
                for field in still_missing:
                    if live.get(field):
                        payload[field] = live[field]
            except Exception as e:
                print(f"  FAILED  {etf_id:8s} {e}")
                failed.append(etf_id)
                continue

        if not payload:
            print(f"  {etf_id:8s} already complete")
            continue

        source = "fd" if fd_row is not None else "yfinance"
        if dry_run:
            print(f"  DRY     {etf_id:8s} would set {sorted(payload)} (from {source})")
        else:
            client.table("etfs").update(payload).eq("id", etf_id).execute()
            print(f"  {etf_id:8s} set {sorted(payload)} (from {source})")
        updated += 1

    return updated, failed


def discover_constituents(etf_ids) -> dict[str, list[list]]:
    """Live yfinance top holdings per ETF - deliberately NOT the DB-first
    get_etf_holdings, which would only echo back the already-tracked subset."""
    holdings_by_etf = {}
    for etf_id in etf_ids:
        holdings = _get_etf_holdings_live(etf_id)
        if holdings:
            print(f"  {etf_id:8s} {len(holdings):3d} holdings")
        else:
            print(f"  WARN    {etf_id:8s} no holdings exposed by yfinance")
        holdings_by_etf[etf_id] = holdings
    return holdings_by_etf


def validate_and_build_ticker(sym, fd_equities):
    """Validate a candidate and assemble its `ticker` row + price backfill.

    Returns (row, price_rows, None) on success, (None, None, reason) on
    rejection. The single fetch_ticker_rows call doubles as the "yfinance
    actually has data" validation and the backfill payload.
    """
    fd_row = fd_lookup(fd_equities, sym)
    if fd_row is None:
        return None, None, "not in financedatabase equities (cash/bond/futures line?)"

    price_rows = fetch_ticker_rows(sym, BACKFILL_PERIOD)
    if not price_rows:
        return None, None, "no yfinance price history"

    row = {
        "id": sym,
        "name": _clean(fd_row.get("name")) or sym,
        "active": True,
        "sector": _clean(fd_row.get("sector")),
        "currency": _clean(fd_row.get("currency")),
        "exchange": _clean(fd_row.get("exchange")),
        "website": _clean(fd_row.get("website")),
        "market_cap": None,
        "logo": None,
    }
    # fd's market_cap is a categorical string ("Large Cap") - the numeric
    # value and the logo only exist on the yfinance side.
    try:
        live = _get_stock_info_live(sym)
        row["market_cap"] = live["marketCap"]
        row["logo"] = live["logo"]
    except Exception:
        pass  # left null; the next fetch_daily run repairs them

    return row, price_rows, None


def insert_new_tickers(client, candidates, fd_equities, dry_run):
    """Validate, insert, and backfill each candidate ticker independently -
    one bad symbol shouldn't sink the batch."""
    today = date.today().isoformat()
    inserted, rejected, failed = [], [], []
    total_price_rows = 0

    for sym in sorted(candidates):
        try:
            row, price_rows, reason = validate_and_build_ticker(sym, fd_equities)
        except Exception as e:
            print(f"  FAILED  {sym:8s} {e}")
            failed.append(sym)
            continue

        if row is None:
            print(f"  SKIP    {sym:8s} {reason}")
            rejected.append(sym)
            continue

        if dry_run:
            print(f"  DRY     {sym:8s} would insert ({len(price_rows)} price rows, sector={row['sector']})")
        else:
            try:
                client.table("ticker").upsert(row).execute()
                for i in range(0, len(price_rows), PRICE_UPSERT_CHUNK):
                    client.table("prices").upsert(price_rows[i:i + PRICE_UPSERT_CHUNK]).execute()
                client.table("ticker").update({"last_fetch": today}).eq("id", sym).execute()
            except Exception as e:
                # last_fetch is only stamped after a full backfill, so a
                # partial write self-heals on the next fetch_daily run
                print(f"  FAILED  {sym:8s} {e}")
                failed.append(sym)
                continue
            print(f"  {sym:8s} {len(price_rows):5d} price rows")

        inserted.append(sym)
        total_price_rows += len(price_rows)

    return inserted, rejected, failed, total_price_rows


def upsert_holdings(client, holdings_by_etf, known_tickers, dry_run):
    """Same shape as fetch_daily.sync_etfs' holdings block, but run after the
    new tickers exist so previously FK-skipped holdings now land."""
    for etf_id, holdings in holdings_by_etf.items():
        holding_rows = [
            {"etf_id": etf_id, "ticker": t, "weight": w}
            for t, w in holdings if t in known_tickers
        ]
        skipped = len(holdings) - len(holding_rows)
        if holding_rows and not dry_run:
            client.table("etf_holdings").upsert(holding_rows).execute()

        prefix = "DRY     " if dry_run else ""
        note = f", {skipped} skipped (untracked ticker)" if skipped else ""
        print(f"  {prefix}{etf_id:8s} {len(holding_rows):4d} holdings{note}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read everything (Supabase, financedatabase, yfinance) but write nothing",
    )
    parser.add_argument(
        "--etfs",
        nargs="+",
        metavar="ID",
        help="Restrict completion to these ETF ids (must already be in the `etfs` table)",
    )
    parser.add_argument(
        "--force-etf-metadata",
        action="store_true",
        help="Overwrite etfs.name/cat/desc from financedatabase even when already set",
    )
    args = parser.parse_args()

    client = get_client()
    fd_etfs, fd_equities = load_fd_catalogs()

    etf_ids = list_etfs()
    if args.etfs:
        requested = {e.strip().upper() for e in args.etfs}
        unknown = sorted(requested - set(etf_ids))
        if unknown:
            print(f"Ignoring ETFs not tracked in Supabase: {', '.join(unknown)}")
        etf_ids = [e for e in etf_ids if e in requested]
    if not etf_ids:
        print("No ETFs to complete - insert ids into the `etfs` table first.")
        return

    print(f"Completing {len(etf_ids)} ETF(s): {', '.join(etf_ids)}")

    print("\n1. Completing ETF metadata (financedatabase)...")
    meta_updated, meta_failed = complete_etf_metadata(
        client, fd_etfs, etf_ids, args.dry_run, args.force_etf_metadata
    )

    print("\n2. Retrieving constituents (yfinance top holdings)...")
    holdings_by_etf = discover_constituents(etf_ids)

    existing = {row["id"] for row in client.table("ticker").select("id").execute().data}
    discovered = {t for holdings in holdings_by_etf.values() for t, _ in holdings}
    candidates = discovered - existing

    print(f"\n3. Validating and inserting {len(candidates)} new ticker(s)...")
    inserted, rejected, ticker_failed, price_rows = insert_new_tickers(
        client, candidates, fd_equities, args.dry_run
    )

    print("\n4. Upserting ETF holdings...")
    upsert_holdings(client, holdings_by_etf, existing | set(inserted), args.dry_run)

    label = "would be " if args.dry_run else ""
    print(
        f"\nDone: {meta_updated} ETF(s) metadata {label}updated, "
        f"{len(inserted)} ticker(s) {label}inserted "
        f"({price_rows} price rows), {len(rejected)} rejected."
    )
    failed = meta_failed + ticker_failed
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
