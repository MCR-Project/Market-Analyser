"""
The tracked universe, and resolving a symbol that is not in it.

Three questions, deliberately answered by three different paths:

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

  - **"What does this code point to?"** is answered per ISIN, once, by
    Yahoo's own search (issue #190). An ISIN identifies a security wherever
    it trades, so it can lead to several tickers - each with its own
    exchange and currency - or to none even when it is genuine. It is a way
    to *find* a ticker and nothing else: it is not stored, and a holding
    stays a ticker. It lives apart from the as-you-type search because it
    necessarily leaves the process, and that search never does.

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

from config import CACHE_TTL_HOLDINGS, CACHE_TTL_ISIN_MISS, SECTOR_TAG
from services.cache import cache
from services.market_data import (
    SymbolNotFound,
    get_listing_currency,
    get_price_series,
    get_stock_info,
    search_listings,
)
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

# What an ISIN looks like before its check digit is worth computing: a
# two-letter country prefix, nine letters or digits, one final digit.
ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# How many listings of one ISIN are described. Each one costs a currency
# read upstream (once, then cached), and a code that survives the filtering
# with more than a few is a code nobody can choose between at a glance.
MAX_ISIN_LISTINGS = 3


def _isin_check_digit_holds(isin: str) -> bool:
    """Whether an ISIN's final digit is the one its other characters imply.

    The Luhn check over the code with each letter written as its two-digit
    value (A=10 … Z=35). It catches every single mistyped digit and most
    swapped neighbours, which is exactly the mistake a pasted or retyped
    code carries - and it is what lets a typo be named as one rather than
    answered with "no listing found".
    """
    digits = "".join(str(int(char, 36)) for char in isin)
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def normalise_isin(text: str) -> str:
    """The canonical (upper-case, trimmed) form of an ISIN, or ValueError.

    The message says which way it failed - the wrong shape, or a check digit
    that does not add up - because the reader's next move differs: one is
    "that is not an ISIN at all", the other is "you are one character off".
    Raised before anything is asked upstream, so a typo costs no call.
    """
    isin = (text or "").strip().upper()
    if not ISIN_PATTERN.match(isin):
        raise ValueError(
            f"`{(text or '').strip()}` is not an ISIN: expected 12 characters - a "
            "two-letter country code, nine letters or digits and a final digit"
        )
    if not _isin_check_digit_holds(isin):
        raise ValueError(
            f"`{isin}` is not a valid ISIN: its check digit does not match, "
            "so a character was probably mistyped"
        )
    return isin


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


def resolve_isin(isin: str) -> dict:
    """The listings an ISIN leads to: `{"isin", "listings": [...]}`.

    Each listing is a search result's shape (a tracked symbol is described
    from the tracked universe, anything else from Yahoo's own hit, with
    `kind: None` - nothing in a hit is a promise about what an instrument
    is, ADR 0004) plus `exchange` and `currency`.

    What is kept of Yahoo's answer: a hit whose symbol is the ISIN itself,
    with or without an exchange suffix (it lists IE00BK5BQT80.SG for a
    Stuttgart line), or that SYMBOL_PATTERN would refuse is dropped, Yahoo's order stands, a symbol
    seen twice counts once, and at most MAX_ISIN_LISTINGS are described.

    Raises ValueError for something that is not an ISIN (400), SymbolNotFound
    when nothing usable is left (404 - worded so as not to call a genuine
    code invalid: Yahoo not indexing it is a fact about Yahoo), and
    DataUnavailable when Yahoo could not be asked, for the search or for a
    currency read (503). Neither failure is cached. An answer with a listing
    whose currency is unknown is cached only for CACHE_TTL_ISIN_MISS: Yahoo
    can hand back a thin `.info` without raising, and a blank that is a
    hiccup must not be kept for the hour as though it were the fact.
    """
    normalised = normalise_isin(isin)

    key = f"isin:{normalised}"
    cached = cache.get(key)
    if cached is not None:
        if not cached["listings"]:
            raise SymbolNotFound(_no_listing_message(normalised))
        return cached

    universe = _universe()
    listings: list[dict] = []
    seen: set[str] = set()
    for hit in search_listings(normalised):
        symbol = (hit.get("symbol") or "").strip().upper()
        if (
            not symbol
            or symbol in seen
            or symbol.startswith(normalised)
            or not SYMBOL_PATTERN.match(symbol)
        ):
            continue
        seen.add(symbol)

        entry = universe.get(symbol) or {
            "symbol": symbol,
            "name": hit.get("name") or symbol,
            "kind": None,
            "tracked": False,
            "sector": "",
            "sectorTag": "",
            "category": "",
            "logo": "",
        }
        try:
            currency = get_listing_currency(symbol)
        except SymbolNotFound:
            # Upstream answered, and has nothing on this symbol: the
            # currency is genuinely unknown, which is a null, not a 503.
            currency = None
        listings.append({**entry, "exchange": hit.get("exchange"), "currency": currency})
        if len(listings) == MAX_ISIN_LISTINGS:
            break

    result = {"isin": normalised, "listings": listings}
    if not listings:
        cache.set(key, result, CACHE_TTL_ISIN_MISS)
        raise SymbolNotFound(_no_listing_message(normalised))
    complete = all(listing["currency"] is not None for listing in listings)
    cache.set(key, result, CACHE_TTL_HOLDINGS if complete else CACHE_TTL_ISIN_MISS)
    return result


def _no_listing_message(isin: str) -> str:
    return (
        f"no usable listing found for ISIN {isin} - the price source has none "
        "indexed under that code that this app can price, which does not mean "
        "the code is wrong; try the ticker symbol"
    )


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
