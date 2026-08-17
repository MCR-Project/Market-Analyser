"""
Daily data-refresh job:
  - Fetches OHLCV history for every active ticker from yfinance and upserts
    it into Supabase, then stamps ticker.last_fetch. An inactive ticker
    whose last_fetch is still null - just added via add_ticker.py
    --inactive, or reset by a prices-convention migration like
    sql/003_store_adjusted_prices.sql - also gets this one-time backfill;
    "active" only starts excluding a ticker from the sync loop once it has
    a last_fetch. Metadata refresh (below) stays active-only regardless.
    Dividend/split events go into their own sparse `dividends`/`splits`
    tables, not `prices`.
  - `prices` stores split/dividend-ADJUSTED OHLC (fetch_ticker_rows calls
    yfinance with auto_adjust=True), not raw closes - see issue #13. This
    matches the live fallback in services.market_data._get_price_series_live,
    so a ticker returns identical values whether Supabase or the live path
    answers, and pct_change()-based correlation math never mistakes a stock
    split for a real return. dividends/splits stay populated as a sparse
    event record even though prices are pre-adjusted.
  - Compacts aged price rows for every known ticker (active or not) into
    coarser granularity, so `prices` doesn't grow unbounded with history
    the product never displays past 5 years (see issue #10).
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
    any ticker scripts/add_ticker.py has just added). This applies
    regardless of active status - an inactive ticker still needs its data
    stored under the current adjustment convention even though it won't
    get further top-ups afterward (see main()'s tickers_needing_sync). The
    fetched history is immediately tiered by age (see bucket_by_age) rather
    than stored flat, so a long-lived ticker's backfill never even
    transiently holds years of raw daily rows.
  - A ticker that's already been fetched gets a 5-day top-up, which covers
    weekends, holidays, and the odd missed run - always within the daily
    tier. (ticker, date, granularity) is the primary key on `prices`, so
    upserting is idempotent - re-fetched days just overwrite the same rows.
  - Exception: if a top-up's fetch reports a new split and/or dividend
    event (checked against `splits`/`dividends` so a date still merely
    sitting inside the 5-day window isn't re-escalated every run), the
    ticker is escalated to a full backfill on the spot instead. Prices are
    stored adjusted, and yfinance's adjustment factor incorporates both
    splits and dividends - either one changes the adjustment factor for the
    ticker's entire history, not just the days the top-up covers.

Tiered price storage (see sql/001_optimize_prices_storage.sql and
bucket_by_age's docstring for the exact rules):
  - Younger than 1 year: individual daily ('D') rows, as before.
  - 1-5 years: OHLC-resampled into one weekly ('W') row per fully-elapsed
    ISO week.
  - 5+ years: OHLC-resampled into one monthly ('M') row per fully-elapsed
    calendar month.
  compact_ticker sweeps every known ticker's already-stored rows on each
  run, promoting buckets to a coarser tier as they age past a cutoff -
  this is what keeps `prices` from re-growing back to its pre-migration
  size as time passes.

Which ETFs/stocks are tracked is entirely DB-driven, not a hardcoded list -
see market_data.list_etfs for ETFs, scripts/add_ticker.py for adding stocks
by hand, and scripts/complete_database.py for completing tracked ETFs
(metadata, constituent tickers, and their price history) in bulk.
"""

import sys
from datetime import date, timedelta
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
from services.supabase_client import assert_not_truncated, get_client, paginated_select

BACKFILL_PERIOD = "max"  # first-ever fetch for a ticker - full available history
TOPUP_PERIOD = "5d"      # every subsequent daily run

# Age tiers for `prices` granularity (see sql/001_optimize_prices_storage.sql):
# rows younger than WEEKLY_TIER_START_DAYS stay daily ('D'); rows between
# that and MONTHLY_TIER_START_DAYS get compacted into weekly ('W') OHLC
# candles; older rows get compacted into monthly ('M') candles.
WEEKLY_TIER_START_DAYS = 365
MONTHLY_TIER_START_DAYS = 5 * 365


def _safe_float(v):
    if v is None:
        return None
    f = float(v)
    return round(f, 4) if not np.isnan(f) else None


def fetch_ticker_rows(ticker_id: str, period: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Fetch OHLCV history for a ticker, split into three upsert-ready
    payloads: price rows (open/high/low/close/volume only - dividends and
    splits live in their own sparse `dividends`/`splits` tables now, see
    sql/001_optimize_prices_storage.sql), and dividend/split events (only
    non-zero occurrences - most rows have neither).

    auto_adjust=True so `prices` stores split/dividend-adjusted OHLC, the
    same convention services.market_data's live fallback uses (see issue
    #13) - a raw close makes a stock split look like a ~-90% one-day return
    to any pct_change()-based reader (compute_correlation_matrix)."""
    hist = yf.Ticker(ticker_id).history(period=period, auto_adjust=True)
    if hist.empty:
        return [], [], []

    hist = hist.dropna(subset=["Close"])

    rows = []
    dividend_events = []
    split_events = []
    for idx, r in hist.iterrows():
        date_str = idx.strftime("%Y-%m-%d")
        volume = r.get("Volume", 0)
        rows.append({
            "ticker": ticker_id,
            "date": date_str,
            "open": _safe_float(r.get("Open")),
            "high": _safe_float(r.get("High")),
            "low": _safe_float(r.get("Low")),
            "close": _safe_float(r.get("Close")),
            "volume": int(volume) if volume is not None and not np.isnan(volume) else 0,
        })

        dividend = _safe_float(r.get("Dividends")) or 0
        if dividend:
            dividend_events.append({"ticker": ticker_id, "date": date_str, "dividends": dividend})

        split = _safe_float(r.get("Stock Splits")) or 0
        if split:
            split_events.append({"ticker": ticker_id, "date": date_str, "splits": split})

    return rows, dividend_events, split_events


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday of d's ISO week


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_end(d: date) -> date:
    next_month = d.replace(day=28) + timedelta(days=4)  # jump into next month
    return _month_start(next_month) - timedelta(days=1)


def _agg(bucket_rows: list[dict], key: str, fn) -> float | None:
    values = [r[key] for r in bucket_rows if r[key] is not None]
    return fn(values) if values else None


def _resample(bucket_rows: list[dict], bucket_date: date, granularity: str) -> dict:
    """Collapse same-ticker daily rows sharing a bucket into one OHLCV row:
    open = the bucket's first open, high = max of the bucket's highs,
    low = min of the bucket's lows, close = the bucket's last close,
    volume = summed daily volume."""
    bucket_rows = sorted(bucket_rows, key=lambda r: r["date"])
    return {
        "ticker": bucket_rows[0]["ticker"],
        "date": bucket_date.isoformat(),
        "granularity": granularity,
        "open": bucket_rows[0]["open"],
        "high": _agg(bucket_rows, "high", max),
        "low": _agg(bucket_rows, "low", min),
        "close": bucket_rows[-1]["close"],
        "volume": sum(r["volume"] for r in bucket_rows),
    }


def bucket_by_age(rows: list[dict], today: date) -> list[dict]:
    """Classify daily {ticker,date,open,high,low,close,volume} rows into
    tiered `prices` granularity based on age relative to `today`:
      - Younger than WEEKLY_TIER_START_DAYS: kept as individual daily
        ('D') rows.
      - Fully-elapsed ISO weeks between the weekly and monthly cutoffs:
        OHLC-resampled into one weekly ('W') row per week.
      - Fully-elapsed calendar months past the monthly cutoff: resampled
        into one monthly ('M') row per month.

    A week/month is only ever compacted once it has FULLY elapsed past its
    cutoff (every one of its days is already older than the cutoff) - so
    each bucket gets aggregated exactly once, from complete data, whether
    it's compacted here (on a fresh backfill fetch) or later by
    compact_ticker (sweeping rows already sitting in the DB as they age).
    A day whose week/month hasn't fully elapsed yet is left daily for now;
    a later run's compact_ticker sweep will catch it once it has.
    """
    weekly_cutoff = today - timedelta(days=WEEKLY_TIER_START_DAYS)
    monthly_cutoff = today - timedelta(days=MONTHLY_TIER_START_DAYS)

    daily_rows = []
    week_buckets: dict[date, list[dict]] = {}
    month_buckets: dict[date, list[dict]] = {}

    for row in rows:
        d = date.fromisoformat(row["date"])
        if d >= weekly_cutoff:
            daily_rows.append({**row, "granularity": "D"})
            continue

        if _month_end(d) < monthly_cutoff:
            month_buckets.setdefault(_month_start(d), []).append(row)
            continue

        week_end = _week_start(d) + timedelta(days=6)
        if week_end < weekly_cutoff:
            week_buckets.setdefault(_week_start(d), []).append(row)
        else:
            daily_rows.append({**row, "granularity": "D"})

    result = daily_rows
    result += [_resample(rs, d, "W") for d, rs in week_buckets.items()]
    result += [_resample(rs, d, "M") for d, rs in month_buckets.items()]
    return result


def compact_ticker(client, ticker_id: str, today: date) -> tuple[int, int, int, int]:
    """Sweep rows already stored for one ticker, compacting any bucket that
    has fully elapsed past its cutoff since the last run: daily rows into
    weekly candles once their ISO week is fully past WEEKLY_TIER_START_DAYS,
    and daily/weekly rows into monthly candles once their calendar month is
    fully past MONTHLY_TIER_START_DAYS (see bucket_by_age's docstring for
    why "fully elapsed" matters). A bucket with no matching source rows
    left - already compacted by a prior run - is naturally skipped, so this
    is safe to call for every known ticker on every daily job run.

    A bucket can also be left half-finished: a prior run upserted the coarse
    W/M row but died (timeout, failed Action, network drop) before deleting
    the daily/weekly sources it was built from. Re-aggregating those
    leftover sources here would silently overwrite the correct candle with
    one built from only a fraction of the period, so each pass first reads
    which coarse rows already exist and, for a bucket that already has one,
    only deletes the leftover sources instead of re-aggregating.

    Returns (weeks_compacted, months_compacted, weeks_skipped_cleaned,
    months_skipped_cleaned) - the skipped-cleaned counts are buckets that
    already had a coarse row and only got their leftover sources deleted.
    """
    weekly_cutoff = today - timedelta(days=WEEKLY_TIER_START_DAYS)
    monthly_cutoff = today - timedelta(days=MONTHLY_TIER_START_DAYS)

    # ── Daily -> weekly ──
    daily_rows = paginated_select(
        lambda: client.table("prices")
        .select("ticker,date,open,high,low,close,volume")
        .eq("ticker", ticker_id)
        .eq("granularity", "D")
        .lt("date", weekly_cutoff.isoformat())
        .order("date")
    )

    week_groups: dict[date, list[dict]] = {}
    for row in daily_rows:
        d = date.fromisoformat(row["date"])
        week_start = _week_start(d)
        if week_start + timedelta(days=6) < weekly_cutoff:
            week_groups.setdefault(week_start, []).append(row)

    # Read existing W rows for just these candidate bucket dates so a
    # half-finished bucket (coarse row already upserted, sources not yet
    # deleted by a prior interrupted run) can be told apart from a fresh one
    # before any aggregation happens. Scoped with .in_() rather than a bare
    # per-ticker read - W rows are already bounded (~208/ticker) but this
    # keeps the round trip small and gives paginated_select's .order("date")
    # a small, single-page result to page over deterministically, so a
    # skipped/duplicated row at a page boundary can't misread an
    # already-compacted bucket as fresh and re-trigger the exact overwrite
    # this function exists to prevent.
    existing_weekly_dates = set()
    if week_groups:
        existing_weekly_dates = {
            row["date"]
            for row in paginated_select(
                lambda: client.table("prices")
                .select("date")
                .eq("ticker", ticker_id)
                .eq("granularity", "W")
                .in_("date", [ws.isoformat() for ws in week_groups.keys()])
                .order("date")
            )
        }

    weeks_compacted = 0
    weeks_skipped = 0
    for week_start, bucket_rows in week_groups.items():
        if week_start.isoformat() in existing_weekly_dates:
            # Already compacted by a prior run that died before cleaning up
            # its sources - don't re-aggregate over a partial bucket, just
            # finish the cleanup.
            weeks_skipped += 1
        else:
            client.table("prices").upsert(_resample(bucket_rows, week_start, "W")).execute()
            weeks_compacted += 1
        client.table("prices").delete().eq("ticker", ticker_id).eq("granularity", "D").in_(
            "date", [r["date"] for r in bucket_rows]
        ).execute()

    # ── Daily/weekly -> monthly ──
    coarse_rows = paginated_select(
        lambda: client.table("prices")
        .select("ticker,date,open,high,low,close,volume,granularity")
        .eq("ticker", ticker_id)
        .in_("granularity", ["D", "W"])
        .lt("date", monthly_cutoff.isoformat())
        .order("date")
        .order("granularity")
    )

    month_groups: dict[date, list[dict]] = {}
    for row in coarse_rows:
        d = date.fromisoformat(row["date"])
        if _month_end(d) < monthly_cutoff:
            month_groups.setdefault(_month_start(d), []).append(row)

    # Same half-finished-bucket check as the weekly pass above, scoped to
    # just these candidate months - the monthly pass reads both D and W
    # sources, and a partially compacted month can hold a mix of both. M
    # rows are unbounded (BACKFILL_PERIOD="max" means a long-history ticker
    # can plausibly cross the page size over time), so scoping this one
    # matters even more than for existing_weekly_dates above.
    existing_monthly_dates = set()
    if month_groups:
        existing_monthly_dates = {
            row["date"]
            for row in paginated_select(
                lambda: client.table("prices")
                .select("date")
                .eq("ticker", ticker_id)
                .eq("granularity", "M")
                .in_("date", [ms.isoformat() for ms in month_groups.keys()])
                .order("date")
            )
        }

    months_compacted = 0
    months_skipped = 0
    for month_start, bucket_rows in month_groups.items():
        if month_start.isoformat() in existing_monthly_dates:
            months_skipped += 1
        else:
            client.table("prices").upsert(_resample(bucket_rows, month_start, "M")).execute()
            months_compacted += 1
        for granularity in ("D", "W"):
            dates = [r["date"] for r in bucket_rows if r["granularity"] == granularity]
            if dates:
                client.table("prices").delete().eq("ticker", ticker_id).eq(
                    "granularity", granularity
                ).in_("date", dates).execute()

    return weeks_compacted, months_compacted, weeks_skipped, months_skipped


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

        db_rows = paginated_select(
            lambda: client.table("etf_holdings").select("ticker").eq("etf_id", etf_id).order("ticker")
        )
        db_tickers = {row["ticker"] for row in db_rows}

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


def _has_new_events(client, table: str, ticker_id: str, events: list[dict]) -> bool:
    """True if any of `events` (each a {"ticker", "date", ...} dict from
    fetch_ticker_rows) isn't already present in the sparse `dividends`/
    `splits` table for this ticker - i.e. a genuinely new corporate action
    this run hasn't already escalated to a full backfill for, not one whose
    date is merely still inside the 5-day top-up window from a prior run."""
    if not events:
        return False
    dates = [e["date"] for e in events]
    # Left unpaginated: `dates` is caller-bounded (currently the handful of
    # events inside a 5-day top-up window), never a whole-table scan - but
    # assert_not_truncated still guards against that assumption silently
    # breaking later (e.g. if this is ever called with a "max"-period event
    # list) instead of quietly acting on a partial `existing_dates` set.
    existing = assert_not_truncated(
        client.table(table)
        .select("date")
        .eq("ticker", ticker_id)
        .in_("date", dates)
        .execute()
        .data
    )
    existing_dates = {row["date"] for row in existing}
    return any(d not in existing_dates for d in dates)


def _needs_full_backfill(
    client, ticker_id: str, split_events: list[dict], dividend_events: list[dict]
) -> str | None:
    """Returns "split", "dividend", "split+dividend", or None, describing
    which kind of genuinely-new corporate action (not already recorded in
    `splits`/`dividends`) a top-up fetch turned up for this ticker.

    Both kinds force escalation to a full backfill: `prices` stores
    adjusted OHLC (fetch_ticker_rows's auto_adjust=True), and yfinance's
    adjustment factor is Adj Close / Close, which incorporates BOTH splits
    AND dividends - a new dividend retroactively rescales every prior
    stored close exactly like a split does, just by a smaller amount. A
    5-day top-up only refreshes the days it covers, so either event type
    needs the ticker's entire history re-fetched and re-tiered.
    """
    has_new_split = _has_new_events(client, "splits", ticker_id, split_events)
    has_new_dividend = _has_new_events(client, "dividends", ticker_id, dividend_events)
    if has_new_split and has_new_dividend:
        return "split+dividend"
    if has_new_split:
        return "split"
    if has_new_dividend:
        return "dividend"
    return None


def _select_tickers_needing_sync(tickers: list[dict]) -> list[dict]:
    """Which `ticker` rows this run's price-sync loop should touch: every
    active ticker, plus any inactive one that has never been fetched
    (last_fetch is null) - either a brand-new ticker added via
    add_ticker.py --inactive, or ANY ticker (active or not) whose
    last_fetch was reset by a prices-convention migration like
    sql/003_store_adjusted_prices.sql.

    Without the inactive-and-never-fetched half of this, an inactive
    ticker's `prices` rows would stay on the old convention forever, since
    active=False otherwise excludes it from every future run - only the
    one-time backfill is unconditional; metadata refresh in main() stays
    active-only, and once last_fetch is set an inactive ticker goes back
    to being skipped, same as before.
    """
    return sorted(
        (row for row in tickers if row["active"] or not row["last_fetch"]),
        key=lambda row: row["id"],
    )


def main():
    client = get_client()

    ticker_rows = paginated_select(
        lambda: client.table("ticker").select("id,last_fetch,active").order("id")
    )
    all_ticker_ids = {row["id"] for row in ticker_rows}
    tickers_needing_sync = _select_tickers_needing_sync(ticker_rows)

    print("Syncing ETFs (market_data.list_etfs)...")
    etf_failures = sync_etfs(client, all_ticker_ids)

    if not tickers_needing_sync:
        print("\nNo tickers to sync - add some with scripts/add_ticker.py first.")
        if etf_failures:
            sys.exit(1)
        return

    print("\nSyncing stock prices...")
    today_date = date.today()
    total_rows = 0
    failed = list(etf_failures)

    for ticker in tickers_needing_sync:
        ticker_id = ticker["id"]
        is_active = ticker["active"]
        period = BACKFILL_PERIOD if not ticker["last_fetch"] else TOPUP_PERIOD
        try:
            rows, dividend_events, split_events = fetch_ticker_rows(ticker_id, period)
        except Exception as e:
            print(f"  FAILED  {ticker_id:8s} {e}")
            failed.append(ticker_id)
            continue

        resplit_note = ""
        if period == TOPUP_PERIOD and (split_events or dividend_events):
            # A split and/or dividend inside the top-up window may be new -
            # check against what's already recorded so a date that's simply
            # still inside the rolling 5-day window (already escalated on a
            # prior run) doesn't force a full re-backfill every single run
            # until it ages out of that window.
            reason = _needs_full_backfill(client, ticker_id, split_events, dividend_events)
            if reason:
                try:
                    rows, dividend_events, split_events = fetch_ticker_rows(ticker_id, BACKFILL_PERIOD)
                except Exception as e:
                    print(f"  FAILED  {ticker_id:8s} re-backfill after {reason}: {e}")
                    failed.append(ticker_id)
                    continue
                period = BACKFILL_PERIOD
                resplit_note = f", new {reason} detected -> full re-backfill"

        if period == BACKFILL_PERIOD:
            # Full history - tier it by age so a brand-new ticker never
            # even transiently stores years of raw daily rows.
            price_rows = bucket_by_age(rows, today_date)
        else:
            # Top-up fetches only ever cover the last few days, always
            # within the daily tier.
            price_rows = [{**row, "granularity": "D"} for row in rows]

        if price_rows:
            client.table("prices").upsert(price_rows).execute()
            total_rows += len(price_rows)
        if dividend_events:
            client.table("dividends").upsert(dividend_events).execute()
        if split_events:
            client.table("splits").upsert(split_events).execute()

        client.table("ticker").update({"last_fetch": today_date.isoformat()}).eq("id", ticker_id).execute()

        metadata_note = ""
        if is_active:
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
        else:
            metadata_note = ", inactive: metadata skipped"

        print(f"  {ticker_id:8s} {len(rows):5d} fetched -> {len(price_rows):4d} stored  ({period}){resplit_note}{metadata_note}")

    print(f"\nDone: {len(tickers_needing_sync)} tickers, {total_rows} price rows upserted.")

    # Compact aged rows for every known ticker, not just active ones -
    # inactive tickers stop getting top-ups but their old data still needs
    # to shrink over time.
    print("\nCompacting aged price rows...")
    weeks_compacted = months_compacted = 0
    weeks_skipped_cleaned = months_skipped_cleaned = 0
    for ticker_id in sorted(all_ticker_ids):
        try:
            weeks, months, weeks_skipped, months_skipped = compact_ticker(client, ticker_id, today_date)
        except Exception as e:
            print(f"  FAILED  {ticker_id:8s} {e}")
            failed.append(ticker_id)
            continue
        weeks_compacted += weeks
        months_compacted += months
        weeks_skipped_cleaned += weeks_skipped
        months_skipped_cleaned += months_skipped
        if weeks or months or weeks_skipped or months_skipped:
            skipped_note = (
                f", {weeks_skipped} week(s), {months_skipped} month(s) skipped (already compacted, sources cleaned up)"
                if weeks_skipped or months_skipped
                else ""
            )
            print(f"  {ticker_id:8s} {weeks} week(s), {months} month(s) compacted{skipped_note}")
    print(f"Done: {weeks_compacted} week(s), {months_compacted} month(s) compacted overall.")
    if weeks_skipped_cleaned or months_skipped_cleaned:
        # A recurring nonzero count here across runs signals a job that keeps
        # dying mid-compaction (timeout, failed Action, network drop) rather
        # than one-off leftovers - worth investigating if it persists.
        print(
            f"  {weeks_skipped_cleaned} week(s), {months_skipped_cleaned} month(s) already "
            "compacted by a prior interrupted run - leftover sources cleaned up."
        )

    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
