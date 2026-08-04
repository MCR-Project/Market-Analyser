"""
Complete the tracked universe in Supabase from provider holdings JSON files.

Where scripts/add_ticker.py adds one ticker by hand and scripts/fetch_daily.py
only refreshes rows that already exist, this script fills the gaps around the
ETFs already tracked in the `etfs` table, using the full holdings scraped
from provider websites by the fetchers in fetcher/ (schema documented in
fetcher/common.py):

  1. Load one or more holdings JSON files (--holdings-json), skipping ETF
     entries the fetcher flagged with an error or that carry no holdings
     (e.g. fixed-income funds).
  2. Intersect the JSON's ETFs with the ids tracked in the `etfs` table -
     the DB stays the source of truth for WHICH ETFs are tracked; the JSON
     only completes them. Uncovered DB ETFs are reported and left to the
     daily job's yfinance top-10 sync.
  3. Complete ETF metadata: fill missing etfs.name from the JSON, missing
     cat/desc from a live yfinance lookup.
  4. Normalize each ETF's holdings tickers: non-US listings (Bloomberg-style
     ids containing a space, e.g. "NPN SJ") are skipped upfront; slash
     share classes are dotted (BRK/B -> BRK.B); duplicate share classes are
     merged via market_data.DUPLICATE_TICKERS.
  5. For every holding not yet in the `ticker` table that weighs at least
     MIN_HOLDING_WEIGHT_PCT (1%) in one of the covered ETFs, validate that
     yfinance actually returns price history for it, then insert it with
     live yfinance metadata and backfill its full price history into
     `prices`. Lighter holdings are never added to the tracked universe.
  6. Upsert `etf_holdings` from the JSON weights - full constituent lists,
     not just the top ~10 that yfinance exposes.
  7. Prune: remove every tracked stock whose weight is below the threshold
     in ALL the ETFs that hold it (DB-wide, not just this run's files),
     along with its price history and holdings rows. Stocks that belong to
     no ETF (hand-added watchlist entries) are never pruned.

Only columns that already exist in the DB are written - no new columns, no
schema changes, and AUM stays a live-only value (see market_data._compute_aum).

Every write is an upsert keyed on the table's primary key, so re-running is
idempotent: a second run finds 0 new tickers and changes nothing. Newly
inserted tickers get last_fetch stamped, so the next fetch_daily.py run gives
them a normal 5-day top-up (not another full backfill) and takes over their
metadata refresh. If a price backfill fails halfway, last_fetch stays null
and the next daily run re-backfills that ticker automatically.

Run manually with:   python scripts/complete_database.py --holdings-json ../vaneck_holdings.json
                     python scripts/complete_database.py --holdings-json ../vaneck_holdings.json --dry-run
                     python scripts/complete_database.py --holdings-json ../vaneck_holdings.json --etfs SMH
Runs end-to-end (fetch + complete) via .github/workflows/fetch-holdings.yml
(manual dispatch).
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.fetch_daily import BACKFILL_PERIOD, bucket_by_age, fetch_ticker_rows
from services.market_data import (
    DUPLICATE_TICKERS,
    _get_etf_info_live,
    _get_stock_info_live,
    list_etfs,
)
from services.supabase_client import get_client

PRICE_UPSERT_CHUNK = 5000  # a "max" backfill can exceed 10k rows per ticker

# A stock is only worth tracking if it carries at least this weight (%) in
# one of the ETFs that hold it - below that it barely moves the fund and
# would bloat the daily fetch job for nothing.
MIN_HOLDING_WEIGHT_PCT = 1.0


def load_holdings_files(paths: list[str]) -> dict[str, dict]:
    """Merge fetcher JSON files into {ETF_ID: {"name", "holdings"}}.

    Skips entries the fetcher flagged with an error and entries without
    holdings (their note says why - typically non-equity funds). If the same
    ETF appears in several files, the first occurrence with holdings wins.
    """
    holdings_by_etf: dict[str, dict] = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for entry in data["etfs"]:
            etf_id = (entry.get("ticker") or "").strip().upper()
            if not etf_id:
                continue
            if entry.get("error"):
                print(f"  SKIP    {etf_id:8s} fetch error: {entry['error']}")
                continue
            if not entry.get("holdings"):
                note = entry.get("note") or "no holdings in file"
                print(f"  SKIP    {etf_id:8s} {note}")
                continue
            if etf_id in holdings_by_etf:
                print(f"  WARN    {etf_id:8s} already loaded from an earlier file - keeping the first")
                continue
            holdings_by_etf[etf_id] = {
                "name": (entry.get("name") or "").strip(),
                "holdings": entry["holdings"],
            }
    return holdings_by_etf


def normalize_symbol(sym: str) -> tuple[str | None, str | None]:
    """Return (canonical_symbol, None) or (None, skip_reason).

    Bloomberg-style ids with an exchange qualifier ("NPN SJ") are non-US
    listings yfinance won't resolve - skipped without burning a call.
    Slash share classes become the repo's canonical dot form (BRK/B ->
    BRK.B), then DUPLICATE_TICKERS merges known share-class aliases.
    """
    sym = sym.strip().upper()
    if " " in sym:
        return None, "non-US listing (Bloomberg-style ticker)"
    sym = sym.replace("/", ".")
    canonical = DUPLICATE_TICKERS.get(sym) or DUPLICATE_TICKERS.get(sym.replace(".", "-")) or sym
    return canonical, None


def normalize_holdings(holdings_by_etf, etf_ids) -> tuple[dict, dict]:
    """Normalize holdings tickers for the given ETFs.

    Returns ({etf_id: {canonical: weight_pct | None}}, {canonical: name}).
    Duplicate canonical tickers within an ETF get their weights summed;
    skipped symbols are logged once each across all ETFs.
    """
    normalized: dict[str, dict] = {}
    names: dict[str, str] = {}
    skipped_logged: set[str] = set()

    for etf_id in etf_ids:
        weights: dict[str, float | None] = {}
        for holding in holdings_by_etf[etf_id]["holdings"]:
            raw = holding.get("ticker") or ""
            canonical, reason = normalize_symbol(raw)
            if canonical is None:
                if raw not in skipped_logged:
                    print(f"  SKIP    {raw:12s} {reason}")
                    skipped_logged.add(raw)
                continue
            weight = holding.get("weight_pct")
            if canonical in weights:
                if weight is not None:
                    weights[canonical] = (weights[canonical] or 0) + weight
            else:
                weights[canonical] = weight
            if holding.get("name") and canonical not in names:
                names[canonical] = holding["name"].strip()
        normalized[etf_id] = weights
        note = f" ({len(holdings_by_etf[etf_id]['holdings']) - len(weights)} skipped/merged)" if len(weights) != len(holdings_by_etf[etf_id]["holdings"]) else ""
        print(f"  {etf_id:8s} {len(weights):4d} holdings{note}")

    return normalized, names


def complete_etf_metadata(client, holdings_by_etf, etf_ids, dry_run) -> tuple[int, list[str]]:
    """Fill missing name/cat/desc on `etfs` rows - name from the holdings
    JSON, cat/desc from a live yfinance lookup.

    A field counts as missing when it's null/empty (or, for name, still equal
    to the raw id).
    """
    resp = client.table("etfs").select("id,name,cat,desc").in_("id", etf_ids).execute()
    current = {row["id"]: row for row in resp.data}

    updated, failed = 0, []
    for etf_id in etf_ids:
        row = current.get(etf_id, {"id": etf_id, "name": None, "cat": None, "desc": None})

        def missing(field):
            value = row.get(field)
            return not value or (field == "name" and value == etf_id)

        payload = {}
        json_name = holdings_by_etf[etf_id]["name"]
        if missing("name") and json_name:
            payload["name"] = json_name

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

        if dry_run:
            print(f"  DRY     {etf_id:8s} would set {sorted(payload)}")
        else:
            client.table("etfs").update(payload).eq("id", etf_id).execute()
            print(f"  {etf_id:8s} set {sorted(payload)}")
        updated += 1

    return updated, failed


def validate_and_build_ticker(sym, holding_names):
    """Validate a candidate and assemble its `ticker` row + backfill payloads.

    Returns (row, price_rows, dividend_events, split_events, None) on
    success, (None, None, None, None, reason) on rejection. The single
    fetch_ticker_rows call doubles as the "yfinance actually has data"
    validation and the backfill payload; price rows are tiered by age via
    bucket_by_age, same as fetch_daily's own backfill path, so a long
    history is never stored flat.
    """
    rows, dividend_events, split_events = fetch_ticker_rows(sym, BACKFILL_PERIOD)
    if not rows:
        return None, None, None, None, "no yfinance price history"
    price_rows = bucket_by_age(rows, date.today())

    try:
        live = _get_stock_info_live(sym)
        row = {
            "id": sym,
            "name": live["name"],
            "active": True,
            "sector": live["sector"],
            "market_cap": live["marketCap"],
            "currency": live["currency"],
            "exchange": live["exchange"],
            "logo": live["logo"],
            "website": live["website"],
        }
    except Exception:
        # Insert with the name from the holdings file and null metadata -
        # the null sector sentinel makes the next fetch_daily run repair it.
        row = {
            "id": sym,
            "name": holding_names.get(sym) or sym,
            "active": True,
            "sector": None,
            "market_cap": None,
            "currency": None,
            "exchange": None,
            "logo": None,
            "website": None,
        }

    return row, price_rows, dividend_events, split_events, None


def insert_new_tickers(client, candidates, holding_names, dry_run):
    """Validate, insert, and backfill each candidate ticker independently -
    one bad symbol shouldn't sink the batch."""
    today = date.today().isoformat()
    inserted, rejected, failed = [], [], []
    total_price_rows = 0

    for sym in sorted(candidates):
        try:
            row, price_rows, dividend_events, split_events, reason = validate_and_build_ticker(sym, holding_names)
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
                if dividend_events:
                    client.table("dividends").upsert(dividend_events).execute()
                if split_events:
                    client.table("splits").upsert(split_events).execute()
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


def prune_below_threshold(client, min_weight, dry_run):
    """Remove every tracked stock whose weight is below min_weight in ALL
    the ETFs that hold it - the mirror of the insert gate, applied DB-wide.

    Stocks held by no ETF at all (hand-added via scripts/add_ticker.py) are
    never pruned. Deletion follows the FK order: etf_holdings, prices,
    dividends, and splits rows first (ticker.id can't be deleted while any
    of them still reference it), then the ticker row itself. Prices are
    re-fetchable, so a stock crossing back above the threshold later is
    simply re-inserted and re-backfilled by a future run.
    """
    resp = client.table("etf_holdings").select("ticker,weight").execute()
    max_weight: dict[str, float] = {}
    for row in resp.data:
        w = float(row["weight"] or 0)
        t = row["ticker"]
        max_weight[t] = max(max_weight.get(t, 0.0), w)

    to_remove = sorted(t for t, w in max_weight.items() if w < min_weight)
    if not to_remove:
        print("  nothing to prune")
        return [], []

    pruned, failed = [], []
    for sym in to_remove:
        if dry_run:
            print(f"  DRY     {sym:8s} would remove (max weight {max_weight[sym]:.2f}%)")
            pruned.append(sym)
            continue
        try:
            client.table("etf_holdings").delete().eq("ticker", sym).execute()
            client.table("prices").delete().eq("ticker", sym).execute()
            client.table("dividends").delete().eq("ticker", sym).execute()
            client.table("splits").delete().eq("ticker", sym).execute()
            client.table("ticker").delete().eq("id", sym).execute()
        except Exception as e:
            print(f"  FAILED  {sym:8s} {e}")
            failed.append(sym)
            continue
        print(f"  {sym:8s} removed (max weight {max_weight[sym]:.2f}%)")
        pruned.append(sym)

    return pruned, failed


def upsert_holdings(client, normalized_by_etf, known_tickers, dry_run):
    """Upsert the full constituent lists from the holdings JSON - run after
    the new tickers exist so the etf_holdings.ticker FK is satisfiable.

    A null weight is stored as 0 rather than null (readers do float(weight))
    or dropped - the holding stays visible either way.
    """
    for etf_id, weights in normalized_by_etf.items():
        holding_rows = [
            {"etf_id": etf_id, "ticker": t, "weight": w if w is not None else 0}
            for t, w in weights.items() if t in known_tickers
        ]
        skipped = len(weights) - len(holding_rows)
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
        "--holdings-json",
        nargs="+",
        required=True,
        metavar="PATH",
        help="One or more holdings JSON files produced by the fetchers in fetcher/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read everything (Supabase, holdings files, yfinance) but write nothing",
    )
    parser.add_argument(
        "--etfs",
        nargs="+",
        metavar="ID",
        help="Restrict completion to these ETF ids (must already be in the `etfs` table)",
    )
    parser.add_argument(
        "--min-weight",
        type=float,
        default=MIN_HOLDING_WEIGHT_PCT,
        metavar="PCT",
        help="Minimum weight (%%) a stock must have in one of its ETFs to be tracked "
             f"(default {MIN_HOLDING_WEIGHT_PCT})",
    )
    args = parser.parse_args()

    client = get_client()

    print("Loading holdings files...")
    holdings_by_etf = load_holdings_files(args.holdings_json)
    print(f"{len(holdings_by_etf)} ETF(s) with holdings loaded.")

    etf_ids = list_etfs()
    if args.etfs:
        requested = {e.strip().upper() for e in args.etfs}
        unknown = sorted(requested - set(etf_ids))
        if unknown:
            print(f"Ignoring ETFs not tracked in Supabase: {', '.join(unknown)}")
        etf_ids = [e for e in etf_ids if e in requested]

    covered = [e for e in etf_ids if e in holdings_by_etf]
    uncovered = [e for e in etf_ids if e not in holdings_by_etf]
    if uncovered:
        print(f"DB ETFs not covered by any holdings file (left to the daily sync): {', '.join(uncovered)}")
    if not covered:
        print("No tracked ETF is covered by the holdings file(s) - nothing to do.")
        return

    print(f"\nCompleting {len(covered)} ETF(s): {', '.join(covered)}")

    print("\n1. Completing ETF metadata...")
    meta_updated, meta_failed = complete_etf_metadata(client, holdings_by_etf, covered, args.dry_run)

    print("\n2. Normalizing holdings tickers...")
    normalized_by_etf, holding_names = normalize_holdings(holdings_by_etf, covered)

    existing = {row["id"] for row in client.table("ticker").select("id").execute().data}
    max_weight: dict[str, float] = {}
    for weights in normalized_by_etf.values():
        for t, w in weights.items():
            max_weight[t] = max(max_weight.get(t, 0.0), w or 0.0)
    discovered = set(max_weight)
    heavy_enough = {t for t, w in max_weight.items() if w >= args.min_weight}
    below = len((discovered - existing) - heavy_enough)
    candidates = heavy_enough - existing

    print(
        f"\n3. Validating and inserting {len(candidates)} new ticker(s) "
        f"({below} below the {args.min_weight:g}% weight threshold, skipped)..."
    )
    inserted, rejected, ticker_failed, price_rows = insert_new_tickers(
        client, candidates, holding_names, args.dry_run
    )

    print("\n4. Upserting ETF holdings...")
    upsert_holdings(client, normalized_by_etf, existing | set(inserted), args.dry_run)

    print(f"\n5. Pruning stocks below {args.min_weight:g}% in every ETF holding them...")
    pruned, prune_failed = prune_below_threshold(client, args.min_weight, args.dry_run)

    label = "would be " if args.dry_run else ""
    print(
        f"\nDone: {meta_updated} ETF(s) metadata {label}updated, "
        f"{len(inserted)} ticker(s) {label}inserted "
        f"({price_rows} price rows), {len(rejected)} rejected, "
        f"{len(pruned)} {label}pruned."
    )
    failed = meta_failed + ticker_failed + prune_failed
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
