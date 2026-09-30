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
     `prices`. Lighter holdings get no `ticker` row and no prices.
  6. Upsert `etf_holdings` from the JSON weights - full constituent lists,
     not just the top ~10 that yfinance exposes - EVERY constituent, the light
     ones too. Each row carries `tracked`, a fact about the STOCK: true when
     its highest weight across every fund holding it (DB-wide, not just this
     run's files) is at least the threshold and it has a `ticker` row, false
     otherwise. It is written on all of that stock's rows in one pass (issue
     #168, docs/adr/0005-*), so a stock at 0.4% in fund A and 2% in fund B is
     tracked in both. An untracked holding is the fund's real weight and
     nothing else - the fund still holds it; the app just is not watching it.
  7. Demote: a stock that is now under the threshold in ALL the ETFs holding it
     has its `ticker`, `prices`, `dividends` and `splits` rows deleted and
     keeps its `etf_holdings` rows, flagged untracked. This replaced pruning,
     which deleted the holding row too and so threw away the only record of
     what the fund contained. Stocks that belong to no ETF (hand-added
     watchlist entries) have no holding row to judge them by and are never
     demoted. Promotion needs no stage of its own: it is stage 5's
     insert-and-backfill followed by stage 6's flag.

Only columns that already exist in the DB are written (`tracked` arrives with
sql/006_keep_untracked_holdings.sql, which has to be applied first), and AUM
stays a live-only value (see market_data._compute_aum).

Every write is an upsert keyed on the table's primary key, so re-running is
idempotent: a second run finds 0 new tickers, demotes nothing and changes
nothing. Newly inserted tickers get last_fetch stamped, so the next
fetch_daily.py run gives them a normal 5-day top-up (not another full
backfill) and takes over their metadata refresh. If a price backfill fails
halfway, last_fetch stays null and the next daily run re-backfills that
ticker automatically.

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
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.fetch_daily import BACKFILL_PERIOD, bucket_by_age, fetch_ticker_rows
from services.market_data import (
    DUPLICATE_TICKERS,
    _get_etf_info_live,
    _get_stock_info_live,
    list_etfs,
)
from services.supabase_client import get_client, paginated_select

PRICE_UPSERT_CHUNK = 5000  # a "max" backfill can exceed 10k rows per ticker
HOLDING_UPSERT_CHUNK = 1000  # a total-market fund lists thousands of constituents

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
    rows = paginated_select(
        lambda: client.table("etfs").select("id,name,cat,desc").in_("id", etf_ids).order("id")
    )
    current = {row["id"]: row for row in rows}

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


class TrackingPlan(NamedTuple):
    """What one run decides about which stocks are Tracked (see plan_tracking)."""

    tracked: dict[str, bool]   # every stock either side knows -> the flag its rows get
    retag: dict[str, bool]     # stocks whose rows OUTSIDE this run's files need a new flag
    demote: list[str]          # stocks whose ticker/prices/dividends/splits must go


def plan_tracking(
    stored_rows: list[dict],
    normalized_by_etf: dict[str, dict[str, float | None]],
    tickers: set[str],
    min_weight: float,
) -> TrackingPlan:
    """Decide, for every stock any fund holds, whether it is Tracked - a fact
    about the STOCK, not about one fund's holding of it (issue #168, ADR 0005).

    `stored_rows` is what `etf_holdings` held before this run
    ({etf_id, ticker, weight, tracked}); `normalized_by_etf` is what this run's
    files say, and where a pair appears in both the file wins, since it is the
    newer weight. `tickers` is every id that has a `ticker` row once the insert
    stage is done.

    A stock's weight is its highest across every fund holding it, so 0.4% in
    one fund and 2% in another is Tracked in both, and stays in the first fund's
    view exactly as it did under pruning. It is flagged tracked only if it ALSO
    has a `ticker` row: `tracked = true` is a promise that prices exist, and a
    heavy stock yfinance had no history for (or whose backfill failed) would
    otherwise be listed in every reader with nothing to price it by. Such a
    stock is flagged untracked but not demoted - `demote` is decided by weight
    alone, so a half-written `ticker` row is never deleted here; the next
    daily run finishes its backfill and the next completion flags it.

    A stock in nobody's holdings (a hand-added watchlist entry) is in neither
    map, so it is neither flagged nor demoted. A null weight counts as 0, the
    way `upsert_holdings` stores it.
    """
    weights: dict[tuple[str, str], float] = {}
    for row in stored_rows:
        weights[(row["etf_id"], row["ticker"])] = float(row["weight"] or 0)
    run_pairs = set()
    for etf_id, held in normalized_by_etf.items():
        for ticker, weight in held.items():
            weights[(etf_id, ticker)] = float(weight or 0)
            run_pairs.add((etf_id, ticker))

    heaviest: dict[str, float] = {}
    for (_, ticker), weight in weights.items():
        heaviest[ticker] = max(heaviest.get(ticker, 0.0), weight)

    tracked = {t: w >= min_weight and t in tickers for t, w in heaviest.items()}
    retag = {
        row["ticker"]: tracked[row["ticker"]]
        for row in stored_rows
        if (row["etf_id"], row["ticker"]) not in run_pairs
        and bool(row["tracked"]) != tracked[row["ticker"]]
    }
    demote = sorted(t for t, w in heaviest.items() if w < min_weight and t in tickers)
    return TrackingPlan(tracked, retag, demote)


def upsert_holdings(
    client, normalized_by_etf: dict[str, dict[str, float | None]], tracked: dict[str, bool], dry_run: bool
) -> None:
    """Upsert the full constituent lists from the holdings JSON, every
    constituent - an untracked one is written as a weight-only row with
    `tracked = false` (issue #168), no `ticker` row needed now that
    etf_holdings.ticker has no foreign key.

    A null weight is stored as 0 rather than null (readers do float(weight))
    or dropped - the holding stays visible either way.
    """
    for etf_id, weights in normalized_by_etf.items():
        holding_rows = [
            {"etf_id": etf_id, "ticker": t, "weight": w if w is not None else 0, "tracked": tracked[t]}
            for t, w in weights.items()
        ]
        if not dry_run:
            for i in range(0, len(holding_rows), HOLDING_UPSERT_CHUNK):
                client.table("etf_holdings").upsert(holding_rows[i:i + HOLDING_UPSERT_CHUNK]).execute()

        prefix = "DRY     " if dry_run else ""
        untracked = sum(1 for row in holding_rows if not row["tracked"])
        note = f" ({untracked} untracked)" if untracked else ""
        print(f"  {prefix}{etf_id:8s} {len(holding_rows):4d} holdings{note}")


def retag_stocks(client, retag: dict[str, bool], dry_run: bool) -> list[str]:
    """Write a changed `tracked` flag onto every row of each stock - all of a
    stock's rows in one statement, never one row, because the flag is
    denormalised and two rows of one stock disagreeing is the failure ADR 0005
    names. Returns the ids that failed; one bad stock never sinks the batch."""
    failed = []
    for sym, value in sorted(retag.items()):
        if dry_run:
            print(f"  DRY     {sym:8s} would flag tracked={value} in the other funds too")
            continue
        try:
            client.table("etf_holdings").update({"tracked": value}).eq("ticker", sym).execute()
        except Exception as e:
            print(f"  FAILED  {sym:8s} {e}")
            failed.append(sym)
    return failed


def demote_stocks(client, to_demote: list[str], dry_run: bool) -> tuple[list[str], list[str]]:
    """Take a stock out of the tracked universe without taking it out of its
    funds: delete its dividends, splits, prices and finally `ticker` row (in
    FK order - `ticker.id` cannot go while any of them references it) and leave
    its `etf_holdings` rows, already flagged untracked by then.

    That order is deliberate. A run that dies between the flag and this leaves an
    untracked holding with a leftover `ticker` row, which the next run demotes
    again; the other order would leave a tracked holding with nothing behind it.
    Prices are re-fetchable, so a stock crossing back over the threshold later
    is simply re-inserted and re-backfilled. Returns (demoted, failed).
    """
    demoted, failed = [], []
    for sym in to_demote:
        if dry_run:
            print(f"  DRY     {sym:8s} would demote (keeps its holding rows)")
            demoted.append(sym)
            continue
        try:
            client.table("dividends").delete().eq("ticker", sym).execute()
            client.table("splits").delete().eq("ticker", sym).execute()
            client.table("prices").delete().eq("ticker", sym).execute()
            client.table("ticker").delete().eq("id", sym).execute()
        except Exception as e:
            print(f"  FAILED  {sym:8s} {e}")
            failed.append(sym)
            continue
        print(f"  {sym:8s} demoted")
        demoted.append(sym)
    return demoted, failed


def complete_holdings(
    client,
    normalized_by_etf: dict[str, dict[str, float | None]],
    tickers: set[str],
    min_weight: float,
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    """Everything after the insert stage: write the holdings with their flags,
    retag the stock's rows in funds this run did not cover, then demote what
    fell under the threshold. `tickers` is every id with a `ticker` row now
    (the ones that already existed plus the ones just inserted).

    The stored rows are read once, before any write, with a deterministic
    ORDER BY and through paginated_select (invariant 3): a stock's flag is
    decided by its heaviest row, and PostgREST truncating that read at 1000 rows
    would demote a stock whose heavy row sorted past the cap - and delete its
    whole price history (issue #14).

    Returns (demoted, failed).
    """
    stored = paginated_select(
        lambda: client.table("etf_holdings").select("etf_id,ticker,weight,tracked").order("etf_id").order("ticker")
    )
    plan = plan_tracking(stored, normalized_by_etf, tickers, min_weight)

    print("\n4. Upserting ETF holdings...")
    upsert_holdings(client, normalized_by_etf, plan.tracked, dry_run)

    print(f"\n5. Flagging stocks whose weight elsewhere changed, and demoting those under {min_weight:g}% everywhere...")
    retag_failed = retag_stocks(client, plan.retag, dry_run)
    if not plan.demote:
        print("  nothing to demote")
    demoted, demote_failed = demote_stocks(client, plan.demote, dry_run)
    return demoted, retag_failed + demote_failed


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

    existing = {
        row["id"]
        for row in paginated_select(lambda: client.table("ticker").select("id").order("id"))
    }
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
        f"({below} below the {args.min_weight:g}% weight threshold, listed untracked)..."
    )
    inserted, rejected, ticker_failed, price_rows = insert_new_tickers(
        client, candidates, holding_names, args.dry_run
    )

    demoted, demote_failed = complete_holdings(
        client, normalized_by_etf, existing | set(inserted), args.min_weight, args.dry_run
    )

    label = "would be " if args.dry_run else ""
    print(
        f"\nDone: {meta_updated} ETF(s) metadata {label}updated, "
        f"{len(inserted)} ticker(s) {label}inserted "
        f"({price_rows} price rows), {len(rejected)} rejected, "
        f"{len(demoted)} {label}demoted."
    )
    failed = meta_failed + ticker_failed + demote_failed
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
