"""
The tracked universe, and resolving a symbol that is not in it.

Two questions, deliberately answered by two different paths:

  - **"What can I pick?"** is answered from Supabase alone. The tracked
    universe is small - a few dozen ETFs and the constituents weighing at
    least 1% of one of them - so it is read once and cached whole, and
    every subsequent search is a filter over memory. Typing into a picker
    must never cost a network round-trip per keystroke, let alone a
    yfinance call.

  - **"Is this real, and can we price it?"** is answered per symbol, and
    only for a symbol someone has actually chosen. A portfolio may hold
    anything yfinance can price, not just what is tracked, so this is the
    check that stands between a typo and a holding silently simulated as
    a pile of cash.

Resolution reports `firstDate`, the earliest close *this app* can price
the symbol from. That is the operationally useful date: it is what
decides how far back a portfolio holding it can be simulated, and the
simulator holds an allocation in cash until it (see services/portfolio.py).
For a tracked stock it comes from one cheap `prices` read; tracked ETFs
have no price rows of their own - `prices.ticker` references `ticker.id`
and ETFs live in `etfs` - so they, like anything untracked, are answered
from live history.
"""

import re

from config import CACHE_TTL_HOLDINGS, SECTOR_TAG
from services.cache import cache
from services.market_data import SymbolNotFound, get_price_series, get_stock_info
from services.supabase_client import get_client_optional, paginated_select

# The whole tracked universe under one key: it is read as a unit, and a
# per-symbol key would turn one read into one per keystroke.
UNIVERSE_KEY = "tracked_universe"

# How many results a search returns when the caller does not say.
DEFAULT_SEARCH_LIMIT = 20

# What a symbol may look like before it is worth asking upstream about.
# Deliberately permissive enough for the real oddities (BRK.B, RDS-A) and
# no more - this string is about to be interpolated into a query.
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")

# Where one word of a company name ends and the next begins, for
# matching a query against the start of any of them.
WORD_SPLIT = re.compile(r"[^A-Z0-9]+")


def _universe() -> dict[str, dict]:
    """Every tracked ticker and ETF, keyed by symbol.

    Two reads, cached for the same hour holdings and stock metadata are:
    the universe only changes when scripts/complete_database.py adds
    something, which is not something a search should be re-checking. An
    unreachable or unconfigured Supabase yields an empty universe rather
    than an error - searching then finds nothing, and resolution falls
    through to the live path, which is exactly what it does for an
    untracked symbol anyway.
    """
    cached = cache.get(UNIVERSE_KEY)
    if cached is not None:
        return cached

    db = get_client_optional()
    if db is None:
        return {}
    try:
        tickers = paginated_select(
            lambda: db.table("ticker").select("id,name,sector,logo").order("id")
        )
        etfs = paginated_select(lambda: db.table("etfs").select("id,name,cat").order("id"))
    except Exception:
        return {}

    universe: dict[str, dict] = {}
    for row in tickers:
        sector = row.get("sector") or ""
        universe[row["id"]] = {
            "symbol": row["id"],
            "name": row.get("name") or row["id"],
            "kind": "stock",
            "tracked": True,
            "sector": sector,
            "sectorTag": SECTOR_TAG.get(sector, sector[:6].upper()) if sector else "",
            "category": "",
            "logo": row.get("logo") or "",
        }
    # ETFs are written second, so a symbol somehow present in both tables
    # reads as the fund it is rather than as one of its own constituents.
    for row in etfs:
        universe[row["id"]] = {
            "symbol": row["id"],
            "name": row.get("name") or row["id"],
            "kind": "etf",
            "tracked": True,
            "sector": "",
            "sectorTag": "",
            "category": row.get("cat") or "",
            "logo": "",
        }

    cache.set(UNIVERSE_KEY, universe, CACHE_TTL_HOLDINGS)
    return universe


def _rank(entry: dict, query: str) -> int | None:
    """How well an entry matches, lower being better; None means it does
    not.

    Symbol matches outrank name matches: someone typing NV wants NVDA
    before anything merely named after those letters. A name matches only
    where a word in it starts with the query, not anywhere inside one -
    otherwise "NV" pulls up Invesco QQQ, which is a fund about neither
    letter and pure noise two keystrokes into a search.
    """
    symbol = entry["symbol"].upper()
    name = entry["name"].upper()
    if symbol == query:
        return 0
    if symbol.startswith(query):
        return 1
    if query in symbol:
        return 2
    if name.startswith(query):
        return 3
    if any(word.startswith(query) for word in WORD_SPLIT.split(name)):
        return 4
    return None


def search_tickers(query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict]:
    """Tracked tickers and ETFs matching `query` by symbol or name.

    Never calls yfinance: this is the as-you-type path, and it answers
    from the cached universe. A symbol that is real but untracked will not
    appear here - resolve_ticker is what confirms one of those, once
    somebody has actually chosen it.

    An empty query lists the universe from the top rather than returning
    nothing, so a picker opened but not yet typed into still has something
    to show.
    """
    entries = sorted(_universe().values(), key=lambda entry: entry["symbol"])
    normalised = query.strip().upper()
    if not normalised:
        return entries[:limit]

    ranked = [
        (rank, entry["symbol"], entry)
        for entry, rank in ((entry, _rank(entry, normalised)) for entry in entries)
        if rank is not None
    ]
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [entry for _, _, entry in ranked[:limit]]


def _first_price_date_db(symbol: str) -> str | None:
    """The earliest date `prices` holds for a symbol, in one row rather
    than by reading its whole history. None when Supabase has nothing -
    for a tracked ETF that is the normal answer, not a fault."""
    db = get_client_optional()
    if db is None:
        return None
    try:
        resp = (
            db.table("prices")
            .select("date")
            .eq("ticker", symbol)
            .order("date")
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    return resp.data[0]["date"] if resp.data else None


def resolve_ticker(symbol: str) -> dict:
    """Confirm a symbol can be priced, and describe it.

    Returns the same shape search_tickers does, plus `firstDate` - the
    earliest close available for it. `tracked` says whether it came from
    the tracked universe or was resolved live; `kind` is None for a live
    resolution, since nothing in that answer says whether it is a fund or
    a company.

    The test is price history, not a name: yfinance answers a made-up
    ticker's info request with a shell dict rather than an error (the
    quirk api/routes.py's get_etf works around), so a name proves nothing
    while a symbol with no history cannot be simulated whatever it is
    called.

    Raises ValueError for something that is not a symbol at all,
    SymbolNotFound when upstream has no history for it (404), and
    DataUnavailable when upstream could not be reached (503) - the last
    distinction being why this cannot simply return None.
    """
    normalised = (symbol or "").strip().upper()
    if not SYMBOL_PATTERN.match(normalised):
        raise ValueError(f"`{symbol}` is not a ticker symbol")

    key = f"resolve:{normalised}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    entry = _universe().get(normalised)
    first_date = _first_price_date_db(normalised) if entry else None

    if first_date is None:
        # Untracked, or tracked with no rows of its own (every ETF).
        # get_price_series falls back to live by itself, and raises
        # DataUnavailable rather than answering if it could not ask.
        history = get_price_series(normalised, period="max")
        if not history:
            raise SymbolNotFound(
                f"no price history for '{normalised}' - it may not be a real ticker"
            )
        first_date = history[0]["date"]

    if entry is None:
        info = get_stock_info(normalised)
        sector = info.get("sector") or ""
        entry = {
            "symbol": normalised,
            "name": info.get("name") or normalised,
            # Nothing in a live lookup says whether this is a fund or a
            # company, and guessing would be worse than saying so.
            "kind": None,
            "tracked": False,
            "sector": sector,
            "sectorTag": info.get("sectorTag") or "",
            "category": "",
            "logo": info.get("logo") or "",
        }

    resolved = {**entry, "firstDate": first_date}
    cache.set(key, resolved, CACHE_TTL_HOLDINGS)
    return resolved
