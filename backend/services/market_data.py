"""
Market data service — reads ETF/stock/price/correlation data from Supabase
(kept fresh daily by scripts/fetch_daily.py), falling back to a live
yfinance call when a row hasn't been synced yet or Supabase is unreachable.

Every public function follows the same pattern:
  1. Check the TTL cache for a cached result
  2. Try Supabase; on a miss (no row, or a not-yet-synced sentinel) or any
     error, fall back to a live yfinance call
  3. Cache the result (skipping genuinely empty/failed results, so a retry
     isn't blocked for the full TTL) and return it

The private "_..._live" helpers are the original all-yfinance
implementations, unchanged - kept both as the fallback path here and reused
directly by scripts/add_ticker.py and scripts/fetch_daily.py to populate
the DB in the first place.

yfinance is free but has quirks:
  - ETF holdings: only the top ~10 are exposed (not the full portfolio)
  - Ticker.info fields vary by security type (ETF vs stock)
  - Multi-ticker downloads return a MultiIndex DataFrame
  - Some historical rows contain NaN (holidays, delistings)
"""

from datetime import date, timedelta

import yfinance as yf
import pandas as pd
import numpy as np
from services.cache import cache
from services.supabase_client import get_client_optional, paginated_select
from config import (
    CACHE_TTL_SECONDS,
    CACHE_TTL_HOLDINGS,
    CACHE_TTL_HOLDINGS_FALLBACK,
    CORRELATION_PERIOD,
    CORRELATION_INTERVAL,
    PERIOD_TO_DAYS,
    SECTOR_TAG,
)


# ── Tracked ETF universe ──────────────────────────────────────────────────────

def list_etfs() -> list[str]:
    """Return every distinct ETF id currently tracked in Supabase (the
    `etfs` table), sorted for stable ordering.

    This is the source of truth for "which ETFs does this app track" -
    there's no hardcoded list. New ETFs enter the tracked set by being
    inserted into `etfs` (an insert via the Supabase dashboard/SQL), then
    scripts/complete_database.py completes their metadata, constituent
    tickers, and price history, and scripts/fetch_daily.py keeps them
    fresh from then on.

    Returns an empty list if Supabase is unreachable or unconfigured -
    callers should treat that as "nothing to track" rather than crashing.
    """
    db = get_client_optional()
    if db is None:
        return []
    try:
        rows = paginated_select(lambda: db.table("etfs").select("id").order("id"))
    except Exception:
        return []
    return [row["id"] for row in rows]


# ── ETF metadata ──────────────────────────────────────────────────────────────

def _compute_aum(info: dict) -> float:
    """AUM is deliberately never stored in the DB - it's a live snapshot
    value, not something that should sit around going stale. Always
    computed fresh from a yfinance Ticker.info dict."""
    return round((info.get("totalAssets") or 0) / 1e9, 2)


def _get_etf_info_live(etf_id: str) -> dict:
    ticker = yf.Ticker(etf_id)
    info = ticker.info or {}
    return {
        "id": etf_id,
        "name": info.get("longName") or info.get("shortName") or etf_id,
        "cat": info.get("category") or info.get("fundFamily") or "",
        "aum": _compute_aum(info),
        "desc": info.get("longBusinessSummary") or info.get("description") or "",
    }


def _get_etf_info_db(etf_id: str) -> dict | None:
    """name/cat/desc from Supabase; aum is still always a live call (see
    _compute_aum). Returns None if the ETF hasn't been synced or Supabase
    is unreachable."""
    db = get_client_optional()
    if db is None:
        return None
    try:
        resp = db.table("etfs").select("id,name,cat,desc").eq("id", etf_id).limit(1).execute()
    except Exception:
        return None
    if not resp.data:
        return None

    row = resp.data[0]
    info = yf.Ticker(etf_id).info or {}
    return {
        "id": row["id"],
        "name": row["name"],
        "cat": row.get("cat") or "",
        "aum": _compute_aum(info),
        "desc": row.get("desc") or "",
    }


def list_etf_summaries() -> list[dict]:
    """Return id/name/cat/holdingCount for every tracked ETF via two
    Supabase reads total - one for `etfs`, one for `etf_holdings` - instead
    of one round-trip per ETF (a live yfinance call for AUM, plus a
    Supabase query) the way get_etf_info/get_etf_holdings cost when looped.
    Used by GET /api/etfs for the picker list. Each read still goes through
    paginated_select, so a table that grows past PostgREST's page cap costs
    more than one HTTP request - but that request count still doesn't scale
    with the number of tracked ETFs the way the old per-ETF loop did.

    AUM is deliberately not included here: it's a live-only yfinance value
    (see _compute_aum) that no caller reads from the list endpoint - the
    picker's detail preview gets it from GET /api/etf/{id} instead.

    Returns [] if Supabase is unreachable or unconfigured.
    """
    db = get_client_optional()
    if db is None:
        return []

    try:
        etfs = paginated_select(lambda: db.table("etfs").select("id,name,cat").order("id"))
        # Ordered like every other paginated_select call site - without a
        # deterministic ORDER BY, .range() paging can skip or duplicate
        # rows across page boundaries (see paginated_select's docstring),
        # which would silently corrupt holdingCount once etf_holdings grows
        # past one page.
        holding_rows = paginated_select(
            lambda: db.table("etf_holdings").select("etf_id").order("etf_id")
        )
    except Exception:
        return []

    counts: dict[str, int] = {}
    for row in holding_rows:
        etf_id = row["etf_id"]
        counts[etf_id] = counts.get(etf_id, 0) + 1

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "cat": row.get("cat") or "",
            "holdingCount": counts.get(row["id"], 0),
        }
        for row in etfs
    ]


def get_etf_info(etf_id: str, force_refresh: bool = False) -> dict:
    """Fetch ETF name, category, AUM, and description.

    Returns a flat dict; cached for CACHE_TTL_HOLDINGS seconds - unless the
    DB had no row and this fell back to a live call, in which case it's
    cached for just CACHE_TTL_HOLDINGS_FALLBACK seconds so the next request
    retries the DB almost immediately instead of being stuck behind a
    stale/partial live snapshot for a full hour. AUM is converted from raw
    totalAssets (int) to billions (float). force_refresh skips the cache
    read entirely (used by the frontend's manual refresh action).
    """
    key = f"etf_info:{etf_id}"
    if not force_refresh:
        cached = cache.get(key)
        if cached:
            return cached

    result = _get_etf_info_db(etf_id)
    ttl = CACHE_TTL_HOLDINGS
    if result is None:
        result = _get_etf_info_live(etf_id)
        ttl = CACHE_TTL_HOLDINGS_FALLBACK

    cache.set(key, result, ttl)
    return result


# ── ETF holdings ──────────────────────────────────────────────────────────────

# Yahoo sometimes returns both share classes of the same company
# (e.g. GOOG + GOOGL for Alphabet). We merge them under the canonical ticker.
DUPLICATE_TICKERS = {"GOOG": "GOOGL", "BRK-B": "BRK.B", "BF-B": "BF.B"}


def _get_etf_holdings_live(etf_id: str) -> list[list]:
    ticker = yf.Ticker(etf_id)
    try:
        funds = ticker.funds_data
        top = funds.top_holdings
        if top is not None and not top.empty:
            # Merge duplicate share classes into a single entry
            merged: dict[str, float] = {}
            for sym, row in top.iterrows():
                # Weight can be a string "7.89%" or a float 0.0789
                pct = row.get("% Assets") or row.get("Holding Percent") or 0
                if isinstance(pct, str):
                    pct = float(pct.replace("%", ""))
                else:
                    pct = float(pct) * 100  # convert 0.0789 → 7.89
                canonical = DUPLICATE_TICKERS.get(sym, sym)
                merged[canonical] = merged.get(canonical, 0) + pct

            holdings = [[sym, round(w, 2)] for sym, w in merged.items()]
            holdings.sort(key=lambda h: -h[1])
            return holdings
    except Exception:
        pass
    return []


def _get_etf_holdings_db(etf_id: str) -> list[list] | None:
    """Already deduplicated by the daily sync job - no need to reapply
    DUPLICATE_TICKERS merging on read. Returns None if unsynced/unreachable."""
    db = get_client_optional()
    if db is None:
        return None
    try:
        rows = paginated_select(
            lambda: db.table("etf_holdings")
            .select("ticker,weight")
            .eq("etf_id", etf_id)
            .order("weight", desc=True)
            .order("ticker")
        )
    except Exception:
        return None
    if not rows:
        return None
    return [[row["ticker"], round(float(row["weight"]), 2)] for row in rows]


def get_etf_holdings(etf_id: str, force_refresh: bool = False) -> tuple[list[list], bool]:
    """Fetch top holdings for an ETF as [[ticker, weight%], ...].

    Holdings are sorted by weight descending. Read from Supabase when
    available, falling back to a live yfinance fetch otherwise - yfinance
    only exposes the top ~10, so a DB miss/error is a materially worse
    result. That fallback is cached for just CACHE_TTL_HOLDINGS_FALLBACK
    seconds (rather than the full CACHE_TTL_HOLDINGS) so the next request
    retries the DB almost immediately instead of pinning the top-~10 result
    in place for an hour. force_refresh skips the cache read entirely
    (used by the frontend's manual refresh action).

    Returns (holdings, stale), where stale is True when these holdings came
    from the live yfinance fallback (DB miss/error) rather than Supabase -
    i.e. likely an incomplete top-~10 rather than the full constituent
    list. The two are returned together (and cached together) rather than
    stale being a separate lookup keyed by etf_id, so a caller can't ever
    observe one without the other - a sibling cache key relied on the
    caller reading it right after this call, which concurrent requests for
    the same ETF could interleave and get wrong.
    """
    key = f"etf_holdings:{etf_id}"
    if not force_refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached

    holdings = _get_etf_holdings_db(etf_id)
    ttl = CACHE_TTL_HOLDINGS
    stale = False
    if holdings is None:
        holdings = _get_etf_holdings_live(etf_id)
        ttl = CACHE_TTL_HOLDINGS_FALLBACK
        stale = True

    # Cache even an empty result (holdings == []) to avoid re-fetching live
    # on every request - cache.get() distinguishes "not cached" (None) from
    # a cached empty list, so this isn't skipped for a falsy result.
    result = (holdings, stale)
    cache.set(key, result, ttl)
    return result


# ── Stock metadata ────────────────────────────────────────────────────────────

def _get_stock_info_live(ticker_symbol: str) -> dict:
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info or {}
    sector = info.get("sector") or info.get("industry") or "Unknown"
    return {
        "ticker": ticker_symbol,
        "name": info.get("longName") or info.get("shortName") or ticker_symbol,
        "sector": sector,
        "sectorTag": SECTOR_TAG.get(sector, sector[:6].upper()),
        "marketCap": info.get("marketCap"),
        "currency": info.get("currency", "USD"),
        "exchange": info.get("exchange", ""),
        "logo": info.get("logo_url") or "",
        "website": info.get("website") or "",
    }


def _get_stock_info_db(ticker_symbol: str) -> dict | None:
    """sector IS NULL is the not-yet-synced sentinel - all six metadata
    columns are always written together in one live call (by
    scripts/add_ticker.py or scripts/fetch_daily.py), so a NULL sector
    means "never synced." Treat that as a miss rather than returning a
    half-populated response.
    """
    db = get_client_optional()
    if db is None:
        return None
    try:
        resp = (
            db.table("ticker")
            .select("id,name,sector,market_cap,currency,exchange,logo,website")
            .eq("id", ticker_symbol)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    if not resp.data or resp.data[0].get("sector") is None:
        return None

    row = resp.data[0]
    sector = row["sector"]
    return {
        "ticker": row["id"],
        "name": row.get("name") or ticker_symbol,
        "sector": sector,
        "sectorTag": SECTOR_TAG.get(sector, sector[:6].upper()),
        "marketCap": row.get("market_cap"),
        "currency": row.get("currency") or "USD",
        "exchange": row.get("exchange") or "",
        "logo": row.get("logo") or "",
        "website": row.get("website") or "",
    }


def get_stock_info(ticker_symbol: str) -> dict:
    """Fetch stock name, sector, market cap, and other metadata.

    Sector is normalized to a short tag via SECTOR_TAG for display. Fully
    DB-read once a ticker has been synced; falls back to a live yfinance
    call for anything not yet synced or if Supabase is unreachable.
    """
    key = f"stock_info:{ticker_symbol}"
    cached = cache.get(key)
    if cached:
        return cached

    result = _get_stock_info_db(ticker_symbol)
    if result is None:
        result = _get_stock_info_live(ticker_symbol)

    cache.set(key, result, CACHE_TTL_HOLDINGS)
    return result


# ── Price series ──────────────────────────────────────────────────────────────

def _get_price_series_live(ticker_symbol: str, period: str, interval: str) -> list[dict]:
    # auto_adjust=True explicitly, rather than relying on yfinance's default
    # (which happens to also be True today) - `prices` is populated by
    # scripts/fetch_daily.py with the same setting (see issue #13), so this
    # must not silently drift from it if the yfinance default ever changes.
    # Both paths need to agree by construction: split-adjusted OHLC, always.
    ticker = yf.Ticker(ticker_symbol)
    hist = ticker.history(period=period, interval=interval, auto_adjust=True)
    if hist.empty:
        return []

    # Drop rows where close is NaN (prevents JSON serialization crash)
    hist = hist.dropna(subset=["Close"])

    return [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "close": round(float(row["Close"]), 2),
            "volume": int(row.get("Volume", 0) if not np.isnan(row.get("Volume", 0)) else 0),
        }
        for idx, row in hist.iterrows()
    ]


def _get_price_series_db(ticker_symbol: str, period: str) -> list[dict] | None:
    if period not in PERIOD_TO_DAYS and period != "max":
        return None
    db = get_client_optional()
    if db is None:
        return None
    days = PERIOD_TO_DAYS.get(period)
    cutoff = (date.today() - timedelta(days=days)).isoformat() if days is not None else None

    def build_query():
        q = (
            db.table("prices")
            .select("date,close,volume")
            .eq("ticker", ticker_symbol)
            .order("date")
            .order("granularity")
        )
        if cutoff is not None:
            q = q.gte("date", cutoff)
        return q

    try:
        rows = paginated_select(build_query)
    except Exception:
        return None
    if not rows:
        return None

    return [
        {
            "date": row["date"],
            "close": round(float(row["close"]), 2),
            "volume": int(row["volume"] or 0),
        }
        for row in rows
    ]


def get_price_series(
    ticker_symbol: str, period: str = "1y", interval: str = "1d"
) -> list[dict]:
    """Fetch historical close prices as a list of {date, close, volume} dicts.

    Only interval="1d" (the only granularity scripts/fetch_daily.py stores)
    attempts the Supabase path; any other interval goes straight to a live
    yfinance call - not treated as an error. Also falls back live if the
    ticker/period combo has no synced rows yet, or Supabase is unreachable.

    Period and interval map directly to yfinance's history() parameters:
      period:   "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"
      interval: "1d", "1wk", "1mo"
    """
    key = f"series:{ticker_symbol}:{period}:{interval}"
    cached = cache.get(key)
    if cached:
        return cached

    result = None
    if interval == "1d":
        result = _get_price_series_db(ticker_symbol, period)
    if result is None:
        result = _get_price_series_live(ticker_symbol, period, interval)

    # Don't cache an empty result - could be a transient miss, let the next
    # request retry rather than being stuck returning [] for the full TTL.
    if result:
        cache.set(key, result, CACHE_TTL_SECONDS)
    return result


# ── Correlation matrix ────────────────────────────────────────────────────────

def _correlation_summary(returns: pd.DataFrame, tickers: list[str]) -> dict:
    """Given daily returns (date index, ticker columns) and the originally
    requested ticker list, compute the correlation matrix and summary
    stats: per-ticker averages, strongest/weakest pairs, and the "hub"
    ticker (highest average correlation to all peers).

    Shared by both the DB path and the live yfinance path - the only thing
    that differs between them is how `returns` was derived.
    """
    available = [t for t in tickers if t in returns.columns]
    returns = returns[available]

    corr_matrix = returns.corr()

    matrix = {}
    for t in available:
        matrix[t] = {}
        for t2 in available:
            val = corr_matrix.loc[t, t2]
            matrix[t][t2] = round(float(val), 4) if not np.isnan(val) else 0.0

    averages = {}
    # strongest/weakest/hub start unset (None / no ticker) rather than at
    # out-of-range sentinels (-1 / 2 / 0) - with fewer than two available
    # tickers there's no pair to compare, and a hardcoded sentinel used to
    # leak straight into the response unexamined; with an all-negative
    # correlation set, a hardcoded avgCorr=0 could out-rank every real
    # (negative) average and leak too. Tracking "still unset" explicitly
    # means the first real value seen always wins instead of being
    # compared against a fake baseline.
    strongest = None
    weakest = None
    hub = {"ticker": "", "avgCorr": 0}
    best_avg = None

    for i, a in enumerate(available):
        # Average correlation of ticker `a` to all other tickers
        others = [matrix[a].get(b, 0) for b in available if b != a]
        avg = sum(others) / len(others) if others else 0
        averages[a] = round(avg, 4)
        if best_avg is None or avg > best_avg:
            best_avg = avg
            hub = {"ticker": a, "avgCorr": round(avg, 4)}

        # Check upper triangle for strongest/weakest pair
        for j in range(i + 1, len(available)):
            b = available[j]
            v = matrix[a].get(b, 0)
            if strongest is None or v > strongest["value"]:
                strongest = {"a": a, "b": b, "value": v}
            if weakest is None or v < weakest["value"]:
                weakest = {"a": a, "b": b, "value": v}

    return {
        "matrix": matrix,
        "tickers": available,
        "averages": averages,
        "strongest": strongest,
        "weakest": weakest,
        "hub": hub,
    }


def _closes_live(tickers: list[str], period: str, interval: str) -> pd.DataFrame | None:
    """yf.download() returns a MultiIndex DataFrame when fetching multiple
    tickers: columns = [("Close", "AAPL"), ("Close", "MSFT"), ...]. We slice
    out the "Close" level to get a flat ticker-indexed DataFrame. auto_adjust
    explicit for the same reason as _get_price_series_live - a raw close
    would make pct_change() read a stock split as a huge one-day return
    (see compute_correlation_matrix, issue #13)."""
    data = yf.download(
        tickers, period=period, interval=interval, progress=False, threads=True,
        auto_adjust=True,
    )
    if data.empty:
        return None

    if isinstance(data.columns, pd.MultiIndex):
        closes = data["Close"]
    elif "Close" in data.columns:
        # Single ticker: yf.download returns flat columns
        closes = data[["Close"]]
        closes.columns = [tickers[0]]
    else:
        closes = data

    if isinstance(closes, pd.Series):
        closes = closes.to_frame(name=tickers[0])
    return closes


def _closes_db(tickers: list[str], period: str) -> pd.DataFrame | None:
    """Bulk-reads close prices for every requested ticker in one query and
    pivots into the same wide date x ticker shape _closes_live produces.
    A partial hit (some but not all tickers synced) is fine - same
    tolerance the live path already has for tickers yfinance lacks data
    for. Returns None (triggering live fallback) if there's too little data
    to be useful, not just if it's totally empty.
    """
    if period not in PERIOD_TO_DAYS and period != "max":
        return None
    db = get_client_optional()
    if db is None:
        return None
    days = PERIOD_TO_DAYS.get(period)
    cutoff = (date.today() - timedelta(days=days)).isoformat() if days is not None else None

    def build_query():
        q = (
            db.table("prices")
            .select("ticker,date,close")
            .in_("ticker", tickers)
            .order("date")
            .order("ticker")
            .order("granularity")
        )
        if cutoff is not None:
            q = q.gte("date", cutoff)
        return q

    try:
        rows = paginated_select(build_query)
    except Exception:
        return None
    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["close"] = df["close"].astype(float)
    closes = df.pivot(index="date", columns="ticker", values="close")

    if closes.shape[1] < 2 or closes.shape[0] < 2:
        return None
    return closes


def compute_correlation_matrix(
    tickers: list[str],
    period: str = CORRELATION_PERIOD,
    interval: str = CORRELATION_INTERVAL,
) -> dict:
    """Compute pairwise Pearson correlation of daily returns for a set of tickers.

    Steps:
      1. Get close prices for all tickers - from Supabase (bulk query,
         pivoted into a wide DataFrame) when interval="1d" and there's
         enough synced data, else a single yf.download() call
      2. Compute daily percentage returns (pct_change)
      3. Build the NxN Pearson correlation matrix via DataFrame.corr()
      4. Extract summary statistics: per-ticker averages, strongest/weakest
         pairs, and the "hub" ticker (highest average ρ to all peers)

    Returns a dict with: matrix, tickers, averages, strongest, weakest, hub.
    """
    key = f"corr_matrix:{'_'.join(sorted(tickers))}:{period}:{interval}"
    cached = cache.get(key)
    if cached:
        return cached

    closes = _closes_db(tickers, period) if interval == "1d" else None
    if closes is None:
        closes = _closes_live(tickers, period, interval)

    if closes is None:
        return {"matrix": {}, "tickers": tickers}

    # Daily returns, drop the first NaN row
    returns = closes.pct_change().dropna()
    result = _correlation_summary(returns, tickers)

    cache.set(key, result, CACHE_TTL_SECONDS)
    return result
