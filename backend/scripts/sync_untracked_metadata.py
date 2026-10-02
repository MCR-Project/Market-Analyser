"""
Keep one row of descriptive data per Untracked holding, refreshed weekly
(issue #170, docs/adr/0005-an-untracked-holding-stays-listed-with-no-prices.md).

An Untracked stock (issue #168) is listed in `etf_holdings` with its weight and
`tracked = false`, and has no `ticker` row - so nothing says what it is. A
Deep-fill (issue #171) reads a fund's whole basket live, but sector and market cap
would cost one slow yfinance `.info` call per stock, ~450 for SPY, on every
press; they change slowly, so this job stores them once a week in
`untracked_metadata` (sql/007) and a Deep-fill only reads them. Prices, volume
and dividends are not stored here: they are the Deep-fill's own live fetch
(docs/adr/0006-*), and nothing in this file costs a daily fetch.

One run, after complete_database.py (the `untracked-metadata` job of
.github/workflows/fetch-holdings.yml):

  1. Read every distinct symbol that `etf_holdings` flags `tracked = false`.
  2. Look up each one that has no row yet, then each whose last lookup failed, then
     each whose row was checked a week or more ago (oldest first), through
     `_get_stock_info_live`, and upsert one row. A good row checked within the last
     7 calendar days is left alone, so a manual re-run costs nothing for it.
  3. A lookup that fails keeps its row: `checked_at` and the reason are written
     and the descriptive columns are left as they were. The symbol is retried on
     EVERY run, not only after a week - `get_untracked_info` declines to use a row
     that carries a failure, so until it succeeds the symbol is one a Deep-fill
     cannot describe, and a re-run after an outage should fix that at once. One bad symbol never stops the run; it exits 1 at the end
     naming each failure.
  4. Delete the rows of symbols that are not Untracked any more - promoted to
     Tracked, or listed in no fund (a fund dropped it).

This module also owns the two writes complete_database.py makes when a stock
changes standing, so the table's shape lives in one place:

  - `copy_ticker_metadata`: DEMOTION copies the stock's own `ticker` row here
    before that row is deleted, so a stock that had metadata keeps it without a
    new `.info` call. A `ticker` row with a null sector is the "never synced"
    sentinel (see market_data._get_stock_info_db) and is not copied as if it were
    an answer; the weekly lookup picks that symbol up instead.
  - `drop_metadata`: PROMOTION deletes the row, since a Tracked stock's
    descriptive data is `ticker`'s now.

A row's age is counted in calendar days, not hours: GitHub starts a scheduled run
hours late and by a different amount each week (docs/adr/0003-*), so a 7-day
threshold in hours would skip a row last checked at 07:40 on a run starting at
06:30 and push its refresh a whole week out.

Two things about what `_get_stock_info_live` returns shape what is stored:

  - It does not raise for a symbol yfinance has nothing on - it answers an empty
    shell (name = the symbol, sector "Unknown", no market cap, an assumed "USD").
    Storing that would put an "Unknown" sector and a currency nobody looked up
    behind every cash line, future or delisted name a fund lists, and the reader
    would hand them out as fact. So a shell is stored as "looked up, nothing
    there": every descriptive column null, no failure. It is not a failed lookup -
    retrying it every week would leave the job red forever over a symbol that has
    no data to find - and `get_untracked_info` answers it as no data, with a
    reason. A lookup that RAISES (an outage, a rate limit) is the failure.
  - It wants yfinance's spelling, not the repo's. The repo writes share classes
    with a dot (BRK.B, BF.B - `complete_database.normalize_symbol`), yfinance only
    knows the dash (BRK-B), and asked for BRK.B it answers the empty shell above for
    one of the largest companies in the market. `yahoo_symbol` converts a
    trailing single-letter share class and nothing else, so NPN.SJ keeps its dot.
    A single letter is also a real exchange suffix (ABC.L, London), so when the
    dashed spelling comes back a shell the dotted original is asked too, and
    only both coming back empty counts as nothing there. The row is keyed by the
    repo's own symbol either way.

Run with:   python scripts/sync_untracked_metadata.py
            python scripts/sync_untracked_metadata.py --dry-run
"""

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.market_data import _get_stock_info_live, yahoo_symbol
from services.supabase_client import get_client, paginated_select

TABLE = "untracked_metadata"
TICKER_COLUMNS = "id,name,sector,market_cap,currency,exchange,logo,website"

# A row checked fewer than this many calendar days ago is not looked up again.
RECHECK_AFTER_DAYS = 7
ID_CHUNK = 100          # ids per `in` filter - the list rides in the request URL
FAILURE_MAX_LENGTH = 200

# ── Writes shared with complete_database.py ───────────────────────────────────

def copy_ticker_metadata(client, sym: str, now: datetime | None = None) -> bool:
    """Copy `sym`'s `ticker` row into `untracked_metadata`, with no yfinance
    call. Returns whether a row was written.

    Called as a stock is demoted, BEFORE its `ticker` row is deleted. Never
    raises: this metadata can always be looked up again by the weekly step, so
    failing to preserve it must not stop the demotion it is a courtesy to - the
    caller prints a warning instead. A row with no sector is the never-synced
    sentinel and is left for that lookup rather than stored as an answer.
    """
    try:
        rows = client.table("ticker").select(TICKER_COLUMNS).eq("id", sym).execute().data
        if not rows or rows[0].get("sector") is None:
            return False
        row = {k: rows[0].get(k) for k in TICKER_COLUMNS.split(",")}
        row.update(checked_at=(now or datetime.now(timezone.utc)).isoformat(), failure=None)
        client.table(TABLE).upsert(row).execute()
    except Exception as e:
        print(f"  WARN    {sym:8s} metadata not copied, the weekly lookup will fetch it: {e}")
        return False
    return True


def drop_metadata(client, symbols: Iterable[str], dry_run: bool = False) -> None:
    """Delete these symbols' rows. Promotion and "no fund lists it any more" are
    the same write; a symbol with no row is simply not matched."""
    symbols = sorted(symbols)
    if dry_run:
        return
    for i in range(0, len(symbols), ID_CHUNK):
        client.table(TABLE).delete().in_("id", symbols[i:i + ID_CHUNK]).execute()


# ── What to look up ───────────────────────────────────────────────────────────

class LookupPlan(NamedTuple):
    lookup: list[str]   # new symbols, then failed ones, then stale ones - oldest check first
    fresh: int          # Untracked symbols whose row is recent enough to leave alone
    orphans: list[str]  # rows for symbols that are not Untracked any more


def plan_lookups(untracked: set[str], stored: list[dict], today: date) -> LookupPlan:
    """Decide which symbols this run looks up. Pure.

    New symbols go first, then failed ones, then the stale ones, so that a run cut
    short (a rate limit, a timeout) has spent its calls on the symbols a Deep-fill
    cannot describe at all - a new one has no data, and a failed one's data is
    refused by the reader - rather than on refreshing ones it already can.

    A failed row is always due, however recently it failed (it is the one
    exception to "checked in the last 7 days is left alone"). Waiting a week would
    leave the symbol undescribed for that long after a transient outage, and a
    manual re-run is exactly how someone fixes that. The cost is bounded: failures
    are the few symbols that raised, not the ~450 that did not, and a symbol
    yfinance simply has nothing on is stored as "nothing there" and is not a
    failure, so it is not retried every run.
    """
    by_id = {row["id"]: row for row in stored}

    def age(sym: str) -> int:
        return (today - date.fromisoformat(str(by_id[sym]["checked_at"])[:10])).days

    def oldest_first(symbols) -> list[str]:
        return sorted(symbols, key=lambda s: (str(by_id[s]["checked_at"]), s))

    new = sorted(s for s in untracked if s not in by_id)
    failed = oldest_first(s for s in untracked if s in by_id and by_id[s].get("failure"))
    stale = oldest_first(
        s for s in untracked
        if s in by_id and not by_id[s].get("failure") and age(s) >= RECHECK_AFTER_DAYS
    )
    return LookupPlan(
        lookup=new + failed + stale,
        fresh=len(untracked) - len(new) - len(failed) - len(stale),
        orphans=sorted(set(by_id) - untracked),
    )


def untracked_symbols(client) -> set[str]:
    """Every distinct symbol some fund lists as Untracked. Paginated and
    deterministically ordered (invariant 3): a fund like SPY alone lists ~450."""
    rows = paginated_select(
        lambda: client.table("etf_holdings")
        .select("etf_id,ticker")
        .eq("tracked", False)
        .order("etf_id")
        .order("ticker")
    )
    return {row["ticker"] for row in rows}


def stored_rows(client) -> list[dict]:
    return paginated_select(
        lambda: client.table(TABLE).select("id,checked_at,failure").order("id")
    )


# ── The weekly step ───────────────────────────────────────────────────────────

def lookup_row(sym: str, checked_at: str, lookup: Callable[[str], dict]) -> dict:
    """The row to store for one successful lookup of `sym`. Raises whatever the
    lookup raises, which the caller records as the failure.

    An empty shell (see the module docstring) from every spelling tried becomes a
    row of nulls with no failure, rather than the "Unknown" sector and assumed
    currency it carries.
    """
    spellings = list(dict.fromkeys([yahoo_symbol(sym), sym]))
    for asked in spellings:
        info = lookup(asked)
        if not (info["sector"] == "Unknown" and info["marketCap"] is None and info["name"] == asked):
            break
    else:
        return {
            "id": sym, "name": None, "sector": None, "market_cap": None, "currency": None,
            "exchange": None, "logo": None, "website": None, "checked_at": checked_at, "failure": None,
        }
    return {
        "id": sym,
        "name": info["name"],
        "sector": info["sector"],
        "market_cap": info["marketCap"],
        "currency": info["currency"],
        "exchange": info["exchange"],
        "logo": info["logo"],
        "website": info["website"],
        "checked_at": checked_at,
        "failure": None,
    }


class SyncResult(NamedTuple):
    looked_up: list[str]
    skipped: int
    failed: dict[str, str]   # symbol -> reason
    dropped: list[str]


def _reason(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text if len(text) <= FAILURE_MAX_LENGTH else text[:FAILURE_MAX_LENGTH - 1] + "…"


def sync(
    client,
    today: date,
    now: datetime,
    dry_run: bool = False,
    lookup: Callable[[str], dict] = _get_stock_info_live,
) -> SyncResult:
    """One weekly pass: look up what is due, record each outcome, drop the rest.

    Each symbol is looked up and written on its own, so a run that dies or is cut
    off keeps what it finished, and a symbol whose lookup raises - or whose write
    does - is recorded and the loop moves on. Rows are upserted one at a time for
    the reason scripts/add_ticker.py gives: a failed row carries fewer columns than
    a successful one, and PostgREST rejects a bulk payload whose objects do not
    share their keys. A dry run plans and prints but makes no yfinance call and
    writes nothing.
    """
    plan = plan_lookups(untracked_symbols(client), stored_rows(client), today)
    checked_at = now.isoformat()
    looked_up, failed = [], {}

    for sym in plan.lookup:
        if dry_run:
            print(f"  DRY     {sym:8s} would look up")
            looked_up.append(sym)
            continue
        try:
            row = lookup_row(sym, checked_at, lookup)
        except Exception as e:
            reason = _reason(e)
            row = {"id": sym, "checked_at": checked_at, "failure": reason}
        try:
            client.table(TABLE).upsert(row).execute()
        except Exception as e:
            # The outcome could not be recorded, so the symbol is retried next run
            # either way; say so rather than count it as looked up.
            failed[sym] = _reason(e)
            print(f"  FAILED  {sym:8s} {failed[sym]}")
            continue
        if row["failure"]:
            failed[sym] = row["failure"]
            print(f"  FAILED  {sym:8s} {row['failure']}")
        else:
            looked_up.append(sym)
            print(f"  {sym:8s} {row['sector'] or 'no data at yfinance'}")

    if plan.orphans:
        verb = "would delete" if dry_run else "deleting"
        print(f"  {verb} {len(plan.orphans)} row(s) for symbols no fund lists as Untracked: {', '.join(plan.orphans)}")
    try:
        drop_metadata(client, plan.orphans, dry_run)
    except Exception as e:
        # Every lookup above is already written; losing the report of them, and the
        # exit code that names what failed, to a traceback here would be worse.
        failed["orphan sweep"] = _reason(e)
        print(f"  FAILED  orphan sweep {failed['orphan sweep']}")
        return SyncResult(looked_up, plan.fresh, failed, [])
    return SyncResult(looked_up, plan.fresh, failed, plan.orphans)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read Supabase and print what would be looked up or deleted; "
             "make no yfinance call and write nothing",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    result = sync(get_client(), now.date(), now, args.dry_run)

    label = "would be " if args.dry_run else ""
    print(
        f"\nDone: {len(result.looked_up)} symbol(s) {label}looked up, "
        f"{result.skipped} checked within {RECHECK_AFTER_DAYS} days and left alone, "
        f"{len(result.dropped)} row(s) {label}deleted."
    )
    if result.failed:
        print("Failed:")
        for sym, reason in sorted(result.failed.items()):
            print(f"  {sym}: {reason}")
        sys.exit(1)


if __name__ == "__main__":
    main()
