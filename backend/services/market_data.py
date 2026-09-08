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
from yfinance.exceptions import YFException, YFRateLimitError
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


# ── Upstream failure signalling ───────────────────────────────────────────────

class DataUnavailable(RuntimeError):
    """A live upstream fetch failed, as opposed to answering "nothing here".

    The two must not be collapsed, because the edge has to handle them
    oppositely: an empty answer is a fact about the ticker (404, and safe
    to cache), while an upstream failure is a fact about right now (503,
    and must not be cached). Collapsing them is what made a cold start
    look permanent - the frontend deliberately never auto-retries a 4xx,
    so one Yahoo hiccup while the server was warming up wedged the whole
    dashboard until the page was reloaded by hand. main.py turns this
    into a 503, which useFetch does retry.
    """


class SymbolNotFound(LookupError):
    """Upstream answered, and the answer is that this symbol doesn't exist.

    The counterpart to DataUnavailable above: both arrive here as a failed
    live call, but they are opposite facts. "Yahoo could not be reached"
    is about right now and heals on its own (503, retry); "Yahoo has never
    heard of ZZZZ" is about the symbol and never will (404, stop asking).

    Collapsing this one into DataUnavailable left the frontend retrying a
    typo'd ticker every three seconds forever, behind a panel promising a
    recovery that could not come.
    """


def _upstream_status(exc: BaseException) -> int | None:
    """The HTTP status behind a failed live call, if there is one.

    yfinance raises its transport's own exception, so this reads the
    attached response rather than the type. curl_cffi sets `code` to 0
    even on a real 404, so `response.status_code` is the only trustworthy
    source; urllib-style `code` is accepted as a fallback. The cause chain
    is walked because yfinance sometimes re-raises through its own error.
    """
    seen = 0
    while exc is not None and seen < 5:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if isinstance(status, int) and status:
            return status
        code = getattr(exc, "code", None)
        if isinstance(code, int) and code:
            return code
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return None


def _live(what: str, fn, *args, **kwargs):
    """Run a live-yfinance fallback, converting the failure into whichever
    of SymbolNotFound / DataUnavailable it actually is.

    Only the *fallback* path is wrapped: a DB hit never reaches here, and
    the private _..._live helpers stay exception-transparent for the
    scripts that call them directly (scripts/fetch_daily.py wants the real
    error, not a re-wrapped one).

    Neither outcome is cached. A 404 is stable enough to cache in
    principle, but nothing re-asks for it — the frontend does not retry a
    4xx — so caching would only add a way to pin a spurious 404 in place.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        if _upstream_status(exc) == 404:
            # `what` already reads "holdings for 'ZZZZ'" — quoting it again
            # would double the quotes in the message the frontend shows.
            raise SymbolNotFound(f"{what}: no such symbol upstream") from exc
        raise DataUnavailable(f"{what} is temporarily unavailable upstream") from exc


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
    # AUM is the only live value on this path (see _compute_aum), and
    # nothing the dashboard renders depends on it. Degrade it to 0 rather
    # than letting a Yahoo hiccup fail an endpoint whose real payload -
    # name, category, description - is already in hand from the DB.
    try:
        info = yf.Ticker(etf_id).info or {}
    except Exception:
        info = {}
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

    Raises DataUnavailable if there's no DB row and the live fallback
    can't reach Yahoo - nothing is cached in that case, so the next
    request retries immediately.
    """
    key = f"etf_info:{etf_id}"
    if not force_refresh:
        cached = cache.get(key)
        if cached:
            return cached

    result = _get_etf_info_db(etf_id)
    ttl = CACHE_TTL_HOLDINGS
    if result is None:
        result = _live(f"ETF info for '{etf_id}'", _get_etf_info_live, etf_id)
        ttl = CACHE_TTL_HOLDINGS_FALLBACK

    cache.set(key, result, ttl)
    return result


# ── ETF holdings ──────────────────────────────────────────────────────────────

# Yahoo sometimes returns both share classes of the same company
# (e.g. GOOG + GOOGL for Alphabet). We merge them under the canonical ticker.
DUPLICATE_TICKERS = {"GOOG": "GOOGL", "BRK-B": "BRK.B", "BF-B": "BF.B"}


def _get_etf_holdings_live(etf_id: str) -> list[list]:
    """Returns [] only when Yahoo genuinely has no holdings for this
    symbol (it isn't a fund, or the fund exposes none); raises when Yahoo
    couldn't be reached or refused.

    The distinction matters upstream: [] is a real answer and gets cached,
    while a failure must not be - a blanket `except Exception: return []`
    here is what let one cold-start network blip be cached as "SPY has no
    holdings" for CACHE_TTL_HOLDINGS_FALLBACK, 404-ing every endpoint
    that builds on holdings.
    """
    ticker = yf.Ticker(etf_id)
    try:
        top = ticker.funds_data.top_holdings
    except YFRateLimitError:
        # Rate limiting is a YFException but a temporary one - it means
        # "ask again later", not "this isn't a fund".
        raise
    except YFException:
        return []
    if top is None or top.empty:
        return []

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

    Raises DataUnavailable if there are no DB rows and the live fallback
    can't reach Yahoo. Only a real empty answer is cached below; a failure
    deliberately isn't, so the next request retries at once.
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
        holdings = _live(f"holdings for '{etf_id}'", _get_etf_holdings_live, etf_id)
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
        result = _live(
            f"stock info for '{ticker_symbol}'", _get_stock_info_live, ticker_symbol
        )

    cache.set(key, result, CACHE_TTL_HOLDINGS)
    return result


# ── Date windows ──────────────────────────────────────────────────────────────

# What a read falls back to when it names neither a period nor a window.
DEFAULT_PERIOD = "1y"

# Which `prices` granularity a live row corresponds to, by interval. Anything
# finer than a day is still one row per interval rather than a resampled
# bucket, so it reports 'D' - the field says "this row is at most one trading
# day", not "this row is exactly one trading day".
_INTERVAL_GRANULARITY = {"1wk": "W", "1mo": "M"}


def resolve_window(
    period: str | None, start: str | None, end: str | None
) -> tuple[str | None, str | None, str | None]:
    """Normalise the two ways of asking for a stretch of history into one.

    A read either names a `period` - a lookback from today, in yfinance's
    own vocabulary ("1y", "max") - or an explicit `start`/`end` window.
    The two are mutually exclusive: a period is anchored to today and a
    window is not, so honouring both at once would silently ignore one of
    them. Either bound of a window may be omitted, meaning "from the
    beginning of what's available" / "up to today".

    Returns the period to use (None once a window was given) alongside the
    two bounds normalised to ISO-8601, and raises ValueError - naming the
    offending parameter - for anything unusable.

    Validation lives here rather than at the HTTP edge so that an internal
    caller (the portfolio simulator, a script) gets the same guarantees a
    request does; api/routes.py turns the ValueError into a 400.
    """
    if not start and not end:
        return period or DEFAULT_PERIOD, None, None

    if period:
        raise ValueError(
            "`period` and `start`/`end` are mutually exclusive - a period is a "
            "lookback from today and a window is not; pass one or the other"
        )

    bounds: dict[str, date] = {}
    for name, value in (("start", start), ("end", end)):
        if not value:
            continue
        try:
            bounds[name] = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"`{name}` is not an ISO-8601 date (YYYY-MM-DD): {value!r}"
            ) from exc

    if "end" in bounds and bounds["end"] > date.today():
        raise ValueError(f"`end` is in the future: {end!r}")
    if len(bounds) == 2 and bounds["start"] >= bounds["end"]:
        raise ValueError(f"`start` must be before `end`: {start!r} is not before {end!r}")

    return (
        None,
        bounds["start"].isoformat() if "start" in bounds else None,
        bounds["end"].isoformat() if "end" in bounds else None,
    )


def _exclusive_end(end: str | None) -> str | None:
    """Shift a window's inclusive `end` onto yfinance's exclusive one.

    The DB path filters `date <= end`; yfinance's own `end` stops the day
    before. Left unreconciled, the same request answers differently
    depending on which path served it - a one-day window comes back
    populated from Supabase and empty from yfinance. The two paths have to
    agree by construction, for the same reason auto_adjust=True is passed
    explicitly on both (issue #13).
    """
    if not end:
        return None
    return (date.fromisoformat(end) + timedelta(days=1)).isoformat()


def _window_bounds(
    period: str | None, start: str | None, end: str | None
) -> tuple[str | None, str | None]:
    """The [lower, upper] date bounds a `prices` read filters on, from
    whichever of the two ways of naming a stretch of history the caller
    used: a period is a lookback from today and never has an upper bound
    ("max" has neither), a window is already the answer.
    """
    if period is None:
        return start, end
    days = PERIOD_TO_DAYS.get(period)
    lower = (date.today() - timedelta(days=days)).isoformat() if days is not None else None
    return lower, None


def _window_filtered(query, start: str | None, end: str | None):
    """Apply an inclusive [start, end] date filter to a `prices` query.

    Both bounds are compared against the row's `date`, which for a
    coarse row is its bucket *anchor* (Monday of the ISO week, 1st of the
    month - see sql/001_optimize_prices_storage.sql), not the day the
    bucket ends. A window therefore returns the buckets anchored inside
    it: one starting mid-month begins at the next anchor rather than
    reaching back into the bucket it landed in.
    """
    if start is not None:
        query = query.gte("date", start)
    if end is not None:
        query = query.lte("date", end)
    return query


# ── Price series ──────────────────────────────────────────────────────────────

def _get_price_series_live(
    ticker_symbol: str,
    period: str | None,
    interval: str,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    # auto_adjust=True explicitly, rather than relying on yfinance's default
    # (which happens to also be True today) - `prices` is populated by
    # scripts/fetch_daily.py with the same setting (see issue #13), so this
    # must not silently drift from it if the yfinance default ever changes.
    # Both paths need to agree by construction: split-adjusted OHLC, always.
    ticker = yf.Ticker(ticker_symbol)
    if start or end:
        hist = ticker.history(
            start=start, end=_exclusive_end(end), interval=interval, auto_adjust=True
        )
    else:
        hist = ticker.history(period=period, interval=interval, auto_adjust=True)
    if hist.empty:
        return []

    # Drop rows where close is NaN (prevents JSON serialization crash)
    hist = hist.dropna(subset=["Close"])

    granularity = _INTERVAL_GRANULARITY.get(interval, "D")
    return [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "close": round(float(row["Close"]), 2),
            "volume": int(row.get("Volume", 0) if not np.isnan(row.get("Volume", 0)) else 0),
            "granularity": granularity,
        }
        for idx, row in hist.iterrows()
    ]


def _get_price_series_db(
    ticker_symbol: str,
    period: str | None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict] | None:
    if period is not None and period not in PERIOD_TO_DAYS and period != "max":
        return None
    db = get_client_optional()
    if db is None:
        return None
    lower, upper = _window_bounds(period, start, end)

    def build_query():
        q = (
            db.table("prices")
            .select("date,close,volume,granularity")
            .eq("ticker", ticker_symbol)
            .order("date")
            .order("granularity")
        )
        return _window_filtered(q, lower, upper)

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
            "granularity": row.get("granularity") or "D",
        }
        for row in rows
    ]


def get_price_series(
    ticker_symbol: str,
    period: str | None = None,
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """Fetch historical close prices as a list of
    {date, close, volume, granularity} dicts, oldest first.

    The stretch of history is named either as a `period` (a lookback from
    today) or as an explicit `start`/`end` window - see resolve_window,
    which validates the pair and which this raises ValueError from.
    Naming neither reads DEFAULT_PERIOD.

    Only interval="1d" (the only granularity scripts/fetch_daily.py stores)
    attempts the Supabase path; any other interval goes straight to a live
    yfinance call - not treated as an error. Also falls back live if the
    ticker has no synced rows in the requested stretch, or Supabase is
    unreachable.

    `granularity` is the row's own bucket - 'D' daily, 'W' weekly, 'M'
    monthly - because `prices` tiers history by age (issue #10): a window
    reaching years back legitimately answers in weekly and monthly buckets,
    and a caller treating every row as one trading day would be wrong about
    the older half of it.

    A window is answered from whatever the DB actually holds: a ticker
    backfilled from 2020 answers a window opening in 2015 with its 2020
    rows rather than falling back live, exactly as a period read does.
    Callers that need to know a holding's history starts later than they
    asked should read the first row's date rather than assume the window
    was covered.

    Period and interval map directly to yfinance's history() parameters:
      period:   "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"
      interval: "1d", "1wk", "1mo"
    """
    period, start, end = resolve_window(period, start, end)

    # The window is part of the key: two different stretches of the same
    # ticker's history are different answers, and must not serve each
    # other's rows for the TTL.
    key = f"series:{ticker_symbol}:{period or ''}:{start or ''}:{end or ''}:{interval}"
    cached = cache.get(key)
    if cached:
        return cached

    result = None
    if interval == "1d":
        result = _get_price_series_db(ticker_symbol, period, start=start, end=end)
    if result is None:
        result = _live(
            f"price series for '{ticker_symbol}'",
            _get_price_series_live, ticker_symbol, period, interval,
            start=start, end=end,
        )

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


def _closes_live(
    tickers: list[str],
    period: str | None,
    interval: str,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame | None:
    """yf.download() returns a MultiIndex DataFrame when fetching multiple
    tickers: columns = [("Close", "AAPL"), ("Close", "MSFT"), ...]. We slice
    out the "Close" level to get a flat ticker-indexed DataFrame. auto_adjust
    explicit for the same reason as _get_price_series_live - a raw close
    would make pct_change() read a stock split as a huge one-day return
    (see compute_correlation_matrix, issue #13)."""
    if start or end:
        data = yf.download(
            tickers, start=start, end=_exclusive_end(end), interval=interval,
            progress=False, threads=True, auto_adjust=True,
        )
    else:
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


def _closes_db(
    tickers: list[str],
    period: str | None,
    start: str | None = None,
    end: str | None = None,
    min_tickers: int = 2,
) -> pd.DataFrame | None:
    """Bulk-reads close prices for every requested ticker in one query and
    pivots into the same wide date x ticker shape _closes_live produces.
    A partial hit (some but not all tickers synced) is fine - same
    tolerance the live path already has for tickers yfinance lacks data
    for. Returns None (triggering live fallback) if there's too little data
    to be useful, not just if it's totally empty.

    `min_tickers` is how wide the frame has to be before the DB counts as
    having answered. Correlation needs a pair before there is anything to
    compute, so one synced ticker out of two is a miss worth retrying
    live; a portfolio holding a single ticker is not - it would go live on
    every request for data Supabase has.
    """
    if period is not None and period not in PERIOD_TO_DAYS and period != "max":
        return None
    db = get_client_optional()
    if db is None:
        return None
    lower, upper = _window_bounds(period, start, end)

    def build_query():
        q = (
            db.table("prices")
            .select("ticker,date,close")
            .in_("ticker", tickers)
            .order("date")
            .order("ticker")
            .order("granularity")
        )
        return _window_filtered(q, lower, upper)

    try:
        rows = paginated_select(build_query)
    except Exception:
        return None
    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["close"] = df["close"].astype(float)
    closes = df.pivot(index="date", columns="ticker", values="close")

    if closes.shape[1] < min_tickers or closes.shape[0] < 2:
        return None
    return closes


def tracked_tickers(tickers: list[str]) -> set[str]:
    """Which of `tickers` the `ticker` table knows about.

    The distinction matters wherever an absent row could mean two things.
    A tracked holding with no dividend rows genuinely paid nothing; an
    untracked one - every ETF, since those live in `etfs` and never get a
    `ticker` row, and any symbol resolved live - simply has no record here,
    which is not the same claim at all. Reporting one as the other would
    tell somebody SPY pays no dividend.

    An empty set when Supabase is unreachable: nothing is known to be
    tracked, so nothing is claimed about it.
    """
    if not tickers:
        return set()
    db = get_client_optional()
    if db is None:
        return set()
    try:
        rows = paginated_select(
            lambda: db.table("ticker").select("id").in_("id", tickers).order("id")
        )
    except Exception:
        return set()
    return {row["id"] for row in rows if row.get("id")}


def get_dividends(
    tickers: list[str], start: str | None = None, end: str | None = None
) -> dict[str, list[tuple[str, float]]]:
    """Dividend events per ticker over [start, end], oldest first.

    `dividends` is a sparse event table (sql/001_optimize_prices_storage.sql):
    one row per ex-date per ticker, holding the cash amount per share as it
    was actually declared. It is deliberately *not* adjusted - `prices`
    carries adjusted closes, so the return already includes these, and
    adjusting them again would be counting the same money twice with the
    arithmetic to match.

    There is no live fallback. yfinance could answer for a symbol the DB
    has never seen, but a number that sometimes comes from a record and
    sometimes from a network call is a number nobody can reconcile; a
    caller wanting to know whether the silence is real asks
    `tracked_tickers`. A ticker with no events in the window is absent from
    the result rather than present with an empty list, so a caller has to
    decide what absence means rather than being handed a zero.
    """
    if not tickers:
        return {}
    db = get_client_optional()
    if db is None:
        return {}

    def build_query():
        query = (
            db.table("dividends")
            .select("ticker,date,dividends")
            .in_("ticker", tickers)
            .order("date")
            .order("ticker")
        )
        return _window_filtered(query, start, end)

    try:
        rows = paginated_select(build_query)
    except Exception:
        return {}

    events: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        symbol, when, amount = row.get("ticker"), row.get("date"), row.get("dividends")
        if not symbol or not when or amount is None:
            continue
        amount = float(amount)
        # A zero row is not an event. The table is meant to hold only
        # non-zero ones, but a zero would otherwise read as a payment.
        if amount <= 0:
            continue
        events.setdefault(symbol, []).append((str(when), amount))
    for series in events.values():
        series.sort()
    return events


def get_closes(
    tickers: list[str],
    period: str | None = None,
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    min_tickers: int = 2,
) -> pd.DataFrame | None:
    """Close prices for several tickers as one wide date x ticker frame,
    from Supabase when it can answer and from a single live download when
    it can't - the same two paths, and the same fallback, get_price_series
    uses for one ticker.

    Reading a basket this way is one query for the whole basket rather than
    one per holding, which is what makes it worth sharing between the
    correlation matrix and anything else that needs a set of tickers priced
    over the same stretch of time.

    The index is a tz-naive DatetimeIndex either way. The DB path pivots on
    the `date` column's ISO strings and yfinance hands back timestamps, so
    without normalising here a caller doing date arithmetic - the portfolio
    simulator deciding where a month boundary falls - would be reading a
    different type depending on which path happened to answer.

    Returns None when neither path has usable data. Raises ValueError for
    an unusable period/window pair (see resolve_window), and DataUnavailable
    / SymbolNotFound from the live path.
    """
    period, start, end = resolve_window(period, start, end)

    closes = None
    if interval == "1d":
        closes = _closes_db(
            tickers, period, start=start, end=end, min_tickers=min_tickers
        )
    if closes is None:
        closes = _live(
            "price history for these holdings",
            _closes_live, tickers, period, interval, start=start, end=end,
        )
    if closes is None:
        return None

    closes = closes.copy()
    closes.index = pd.to_datetime(closes.index)
    if closes.index.tz is not None:
        closes.index = closes.index.tz_localize(None)
    return closes.sort_index()


def compute_correlation_matrix(
    tickers: list[str],
    period: str = CORRELATION_PERIOD,
    interval: str = CORRELATION_INTERVAL,
) -> dict:
    """Compute pairwise Pearson correlation of daily returns for a set of tickers.

    Steps:
      1. Get close prices for all tickers via get_closes - from Supabase
         (bulk query, pivoted into a wide DataFrame) when interval="1d"
         and there's enough synced data, else a single yf.download() call.
         Its default min_tickers=2 is what this step needs: a lone synced
         ticker has no peer to correlate against, so it is a miss
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

    closes = get_closes(tickers, period=period, interval=interval)

    if closes is None:
        return {"matrix": {}, "tickers": tickers}

    # Daily returns, drop the first NaN row
    returns = closes.pct_change().dropna()
    result = _correlation_summary(returns, tickers)

    cache.set(key, result, CACHE_TTL_SECONDS)
    return result
