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
see market_data.list_etfs for ETFs and scripts/add_ticker.py for stocks -
placeholders until automatic discovery lands (see the "Find a way to
automatically fetch tickers and etfs" issue).
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import yfinance as yf

from services.market_data import get_etf_info, get_etf_holdings, list_etfs, _get_stock_info_live
from services.supabase_client import get_client

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
    non-zero occurrences - most rows have neither)."""
    hist = yf.Ticker(ticker_id).history(period=period, auto_adjust=False)
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


def sync_etfs(client, known_tickers: set[str]) -> list[str]:
    """Refresh etfs/etf_holdings for every ETF already tracked in Supabase
    (market_data.list_etfs) - this only ever refreshes existing rows, it
    doesn't add new ETFs (there's no add_etf.py script yet).

    aum is deliberately not stored here - it's a live snapshot value, not
    something that should sit in the DB going stale between daily runs.
    Callers that need current AUM should call get_etf_info directly.

    Holdings for tickers we don't track yet are skipped (etf_holdings.ticker
    has an FK to ticker.id) rather than failing the whole ETF - they'll show
    up once that ticker is added via scripts/add_ticker.py.
    """
    failed = []
    for etf_id in list_etfs():
        try:
            info = get_etf_info(etf_id)
            holdings = get_etf_holdings(etf_id)
        except Exception as e:
            print(f"  FAILED  {etf_id:8s} {e}")
            failed.append(etf_id)
            continue

        client.table("etfs").upsert({
            "id": etf_id,
            "name": info["name"],
            "cat": info["cat"],
            "desc": info["desc"],
        }).execute()

        holding_rows = [
            {"etf_id": etf_id, "ticker": t, "weight": w}
            for t, w in holdings if t in known_tickers
        ]
        skipped = len(holdings) - len(holding_rows)
        if holding_rows:
            client.table("etf_holdings").upsert(holding_rows).execute()

        note = f", {skipped} skipped (untracked ticker)" if skipped else ""
        print(f"  {etf_id:8s} {len(holding_rows):4d} holdings{note}")

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
            rows, dividend_events, split_events = fetch_ticker_rows(ticker_id, period)
        except Exception as e:
            print(f"  FAILED  {ticker_id:8s} {e}")
            failed.append(ticker_id)
            continue

        if rows:
            client.table("prices").upsert(rows).execute()
            total_rows += len(rows)
        if dividend_events:
            client.table("dividends").upsert(dividend_events).execute()
        if split_events:
            client.table("splits").upsert(split_events).execute()

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
