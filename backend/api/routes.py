"""
API route definitions — all endpoints are mounted under /api.

Each endpoint delegates to a service function in services/market_data.py,
which handles caching and yfinance calls. Routes handle input normalization
(uppercasing tickers), error responses (404 for missing data), and any
post-processing (e.g. counting edges above a threshold).

Endpoints:
  GET /api/etfs                  — list all tracked ETFs (summary)
  GET /api/etf/{etf_id}          — full ETF detail with holdings
  GET /api/stock/{ticker}        — single stock metadata
  GET /api/stocks?tickers=A,B,C  — batch stock metadata
  GET /api/tickers/search?q=     — search the tracked universe
  GET /api/tickers/{symbol}      — resolve one symbol, tracked or not
  GET /api/series/{ticker}       — historical price series, by period or
                                   by explicit start/end window
  GET /api/correlation/{etf_id}  — Pearson correlation matrix for holdings
  GET /api/sectors/{etf_id}      — sector weight breakdown
  POST /api/portfolio/simulate   — value a basket of tickers over a window,
                                   with optional rebalancing and recurring
                                   contributions
  POST /api/portfolio/risk       — average pairwise correlation, effective
                                   bet count and per-holding risk share for
                                   the same basket (issue #113)
"""

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
from services.market_data import (
    get_etf_info,
    get_etf_holdings,
    get_stock_info,
    get_price_series,
    compute_correlation_matrix,
    list_etf_summaries,
)
from services.portfolio import compute_portfolio_risk, simulate_portfolio
from services.tickers import DEFAULT_SEARCH_LIMIT, resolve_ticker, search_tickers
from config import SECTOR_TAG

router = APIRouter(prefix="/api")


# ── ETF endpoints ─────────────────────────────────────────────────────────────

@router.get("/etfs")
def get_etfs():
    """List all tracked ETFs with summary info (no holdings array, no AUM).

    Reads id/name/cat/holdingCount for every tracked ETF via
    list_etf_summaries - two Supabase queries total, no yfinance calls,
    regardless of how many ETFs are tracked. AUM is intentionally omitted:
    it required a live yfinance call per ETF and no caller reads it from
    this endpoint (the picker's preview gets it from GET /api/etf/{id}).
    """
    return list_etf_summaries()


@router.get("/etf/{etf_id}")
def get_etf(
    etf_id: str,
    refresh: bool = Query(False, description="Bypass the cache and re-fetch info/holdings now"),
):
    """Full ETF detail including the holdings array.

    Returns 404 if yfinance returns no meaningful name (indicates the
    ticker doesn't exist or isn't an ETF). `refresh=true` bypasses the
    cache on both underlying fetches - used by the frontend's manual
    refresh action to force a retry rather than waiting out the TTL.
    """
    etf_id = etf_id.upper()
    info = get_etf_info(etf_id, force_refresh=refresh)

    # Decided before holdings are fetched, not after. Yahoo answers a made-up
    # ticker's info request with a shell dict (so `name` falls back to the
    # ticker itself) but 404s the holdings request, so asking for holdings
    # first meant this branch was unreachable for exactly the case it was
    # written for - the ticker that doesn't exist.
    if not info["name"] or info["name"] == etf_id:
        raise HTTPException(404, f"ETF '{etf_id}' not found or no data available")

    holdings, stale = get_etf_holdings(etf_id, force_refresh=refresh)
    # stale is True when holdings came from the live yfinance fallback (DB
    # miss/error) rather than Supabase - flags a likely-incomplete top-~10
    # to the frontend.
    return {**info, "holdings": holdings, "stale": stale}


# ── Stock endpoints ───────────────────────────────────────────────────────────

@router.get("/stock/{ticker}")
def get_stock(ticker: str):
    """Single stock metadata: name, sector, market cap, etc."""
    ticker = ticker.upper()
    return get_stock_info(ticker)


@router.get("/stocks")
def get_stocks(tickers: str = Query(..., description="Comma-separated ticker list")):
    """Batch stock metadata — fetches info for each ticker in parallel-ish.

    Useful for populating the table view after loading an ETF's holdings.
    Each ticker is fetched (or cache-hit) individually.
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    return [get_stock_info(t) for t in ticker_list]


# ── Ticker lookup ─────────────────────────────────────────────────────────────

# Declared before /tickers/{symbol}: FastAPI matches routes in the order
# they are added, so the other way round "search" would be read as a
# symbol and this endpoint would be unreachable.

@router.get("/tickers/search")
def search_universe(
    q: str = Query("", description="Symbol or name fragment; empty lists the universe"),
    limit: int = Query(DEFAULT_SEARCH_LIMIT, ge=1, le=50),
):
    """Search the tracked universe by symbol or name.

    Answers from a cached snapshot of the `ticker` and `etfs` tables, with
    symbol matches ranked above name matches - it is the as-you-type path,
    so it never calls yfinance and never touches the network per keystroke.

    A real but untracked symbol will not appear here; GET /api/tickers/{symbol}
    is what confirms one of those, once somebody has chosen it.
    """
    return search_tickers(q, limit=limit)


@router.get("/tickers/{symbol}")
def resolve_symbol(symbol: str):
    """Confirm one symbol can be priced, and describe it.

    Returns a search result's shape plus `firstDate`, the earliest close
    available for it - which is how far back a portfolio holding it can be
    simulated. `tracked` says whether it came from the tracked universe or
    was resolved live.

    404 when upstream has no history for the symbol (a fact about the
    symbol, which the frontend must not retry), 503 when upstream could
    not be reached (a fact about right now, which it should), and 400 for
    something that is not a symbol at all.
    """
    try:
        return resolve_ticker(symbol)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ── Price series ──────────────────────────────────────────────────────────────

@router.get("/series/{ticker}")
def get_series(
    ticker: str,
    period: str | None = Query(None, description="1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max"),
    interval: str = Query("1d", description="1m, 5m, 15m, 1h, 1d, 1wk, 1mo"),
    start: str | None = Query(None, description="Window start, ISO-8601 (YYYY-MM-DD), inclusive"),
    end: str | None = Query(None, description="Window end, ISO-8601 (YYYY-MM-DD), inclusive"),
):
    """Historical price series for charting and backtesting.

    Returns an array of {date, close, volume, granularity} objects, oldest
    first. The frontend maps the `close` values into the AreaChart
    sparkline; `granularity` says whether a row is a day, a week or a month
    of history, since `prices` tiers older rows into coarser buckets.

    The stretch of history is either a `period` (a lookback from today) or
    an explicit `start`/`end` window - the two are mutually exclusive, and
    naming neither reads the default period. An unusable pair is a 400
    naming the parameter at fault rather than a silently empty array: it is
    a fact about the request, and the frontend must not retry it.
    """
    ticker = ticker.upper()
    try:
        data = get_price_series(ticker, period=period, interval=interval, start=start, end=end)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not data:
        raise HTTPException(404, f"No price data for '{ticker}'")
    return data


# ── Correlation ───────────────────────────────────────────────────────────────

@router.get("/correlation/{etf_id}")
def get_correlation(
    etf_id: str,
    period: str = Query("1y"),
    threshold: float = Query(0.0, ge=0, le=1),
):
    """Correlation matrix for an ETF's top holdings.

    Fetches the ETF's holdings, downloads their price history, and computes
    pairwise Pearson correlation of daily returns.

    When `threshold` > 0, also counts the number of pairs (edges) whose
    correlation exceeds the threshold — used by the network view to show
    "17 links" in the toolbar.
    """
    etf_id = etf_id.upper()
    holdings, _ = get_etf_holdings(etf_id)
    if not holdings:
        raise HTTPException(404, f"No holdings for ETF '{etf_id}'")

    tickers = [h[0] for h in holdings]
    result = compute_correlation_matrix(tickers, period=period)

    # Count edges above threshold for the network view. A null pair (not
    # enough overlapping history to correlate at all - issue #97) is
    # explicitly not an edge, rather than relying on `.get(b, 0)` to turn a
    # missing key into 0 - the key is always present now, holding None,
    # and `None >= threshold` would raise.
    if threshold > 0:
        edge_count = 0
        available = result["tickers"]
        for i, a in enumerate(available):
            for j in range(i + 1, len(available)):
                b = available[j]
                value = result["matrix"].get(a, {}).get(b)
                if value is not None and value >= threshold:
                    edge_count += 1
        result["edgeCount"] = edge_count
        result["threshold"] = threshold

    return result


# ── Sector breakdown ──────────────────────────────────────────────────────────

@router.get("/sectors/{etf_id}")
def get_sectors(etf_id: str):
    """Sector weight breakdown for an ETF's holdings.

    For each holding, fetches its sector via get_stock_info, then aggregates
    weights and counts by sector. Returns a ranked list with the top sector
    highlighted.

    The sector name comes from yfinance's Ticker.info["sector"] field,
    normalized to a short tag via SECTOR_TAG.
    """
    etf_id = etf_id.upper()
    holdings, _ = get_etf_holdings(etf_id)
    if not holdings:
        raise HTTPException(404, f"No holdings for ETF '{etf_id}'")

    tickers = [h[0] for h in holdings]
    weight_map = {h[0]: h[1] for h in holdings}
    total_weight = sum(h[1] for h in holdings)

    # Accumulate weight and count per sector
    sector_weights: dict[str, float] = {}
    sector_counts: dict[str, int] = {}

    for t in tickers:
        info = get_stock_info(t)
        sector = info["sector"]
        w = weight_map.get(t, 0)
        sector_weights[sector] = sector_weights.get(sector, 0) + w
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    # Sort by weight descending
    ranked = sorted(sector_weights.items(), key=lambda x: -x[1])

    sectors = []
    for name, w in ranked:
        tag = SECTOR_TAG.get(name, name[:6].upper())
        sectors.append({
            "name": name,
            "tag": tag,
            "weight": round(w, 2),
            "share": round((w / total_weight) * 100) if total_weight else 0,
            "count": sector_counts.get(name, 0),
        })

    return {
        "sectors": sectors,
        "topSector": sectors[0] if sectors else None,
        "sectorLabel": "TOP SECTOR",
    }


# ── Portfolio simulation ──────────────────────────────────────────────────────

class HoldingIn(BaseModel):
    """One line of a portfolio: a ticker and how much of the portfolio it
    is. Weights are relative - the simulation normalises them - so any
    non-negative numbers describe the same basket by their ratio."""

    ticker: str
    weight: float = 0


class ContributionIn(BaseModel):
    """Money paid in on a schedule, rather than only at the start.

    Optional on the request and off by default: absent, null, or an amount
    of zero all mean the same thing, and all three simulate exactly as a
    run with no contributions (issue #67).
    """

    amount: float = Field(0, description="Paid in each time, in USD; 0 is off")
    frequency: str | None = Field(None, description="monthly, quarterly, yearly")


class PortfolioIn(BaseModel):
    """A whole portfolio, sent with every request.

    Nothing about it is stored: there are no accounts here, portfolios live
    in the browser that authored them, and this endpoint is the arithmetic
    they ask for. That is also why it is a POST with a body rather than a
    GET - a basket of holdings does not belong in a URL - even though it
    reads nothing and changes nothing.
    """

    holdings: list[HoldingIn]
    value: float = Field(10_000, description="Total invested at the start date, in USD")
    period: str | None = Field(None, description="Lookback from today: 1y, 5y, max… (excludes start/end)")
    start: str | None = Field(None, description="Window start, ISO-8601 (YYYY-MM-DD), inclusive")
    end: str | None = Field(None, description="Window end, ISO-8601 (YYYY-MM-DD), inclusive")
    rebalance: str = Field("none", description="none, monthly, quarterly, yearly")
    contribution: ContributionIn | None = Field(
        None, description="Optional recurring contribution; omit for a single lump sum"
    )
    rate: float | None = Field(
        None,
        description=(
            "Risk-free rate override, percent per annum (e.g. 4.2), for "
            "Sharpe and Sortino (issue #112). Omit to use the tracked "
            "series' own average over the run's window instead."
        ),
    )


@router.post("/portfolio/simulate")
def post_portfolio_simulate(portfolio: PortfolioIn):
    """Value a basket of tickers over a window, day by day.

    Returns the run in columnar form - `dates`, `total`, `cash`,
    `invested`, and a `values` array per holding - alongside `metrics`
    (final value, total return, CAGR, annualised volatility, deepest
    drawdown with the dates of both ends, time under water, pain index,
    Calmar, Sharpe, Sortino - issue #112 - what was paid in, what was
    gained, and the money-weighted return) and, per holding, its own price
    return, final value, share of the finished portfolio and dollar
    contribution to its gain.

    Sharpe and Sortino are scored against `metrics.riskFreeRate` - an
    explicit `rate` override on the request, or the tracked risk-free
    series' own average over this run's window - echoed alongside
    `metrics.riskFreeRateSource` ("override" or "tracked") so a reader can
    tell which one actually produced them. Null, with both ratios, when
    neither is available.

    Dividend income is reported and never added: `prices` holds adjusted
    closes (issue #13), so every return here is already a total return and
    the income is inside the value. `metrics.dividendIncome`,
    `metrics.dividendYield` and each holding's `income` answer the separate
    question of how much came from being paid rather than from the price
    moving. A holding the `dividends` table has no record of - every ETF,
    and anything resolved live - reports null rather than zero, and is
    named in `metrics.incomeUnknownFor`.

    An optional `contribution` of `{amount, frequency}` pays money in on
    the first row of every new month, quarter or year after the start.
    Omit it for a single lump sum, which is the default. Once money keeps
    arriving the two families of number stop agreeing on purpose: total
    return, CAGR, volatility and drawdown describe the portfolio and are
    time-weighted, while `moneyWeightedReturn` describes the account.

    See services/portfolio.py for the model and for what every number
    means: buy and hold unless a rebalance frequency is named, weights
    normalised, an allocation held as cash until its holding lists, and
    the annualisation read off the run's own calendar rather than assumed.

    The window is named as a `period` counting back from today or as an
    explicit `start`/`end`, never both. "max" reaches as far back as the
    holdings go, which only the data knows: the response's own `start` and
    `end` are the window actually simulated.

    A request that cannot be simulated is a 400 naming what is wrong, and
    a holding that does not exist is a 404 naming the ticker (via
    SymbolNotFound) - both facts about the request rather than about right
    now, so neither is worth retrying. A failure to reach the price source
    stays a retryable 503, like everywhere else.
    """
    try:
        return simulate_portfolio(
            [holding.model_dump() for holding in portfolio.holdings],
            value=portfolio.value,
            period=portfolio.period,
            start=portfolio.start,
            end=portfolio.end,
            rebalance=portfolio.rebalance,
            contribution=(
                portfolio.contribution.model_dump() if portfolio.contribution else None
            ),
            rate=portfolio.rate,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/portfolio/risk")
def post_portfolio_risk(portfolio: PortfolioIn):
    """How independently a basket's own holdings actually move (issue
    #113) - the same body `POST /api/portfolio/simulate` takes (`value`,
    `rebalance`, `contribution` and `rate` are accepted for shape parity
    but unused: this question is about the basket's price history, not
    about a value simulated over it), read from its own endpoint rather
    than folded into every run.

    Returns `averageCorrelation` (the basket's holdings' average pairwise
    correlation - lower means more diversified), `effectiveBets` (the
    number of equally weighted holdings that would concentrate risk the
    way the basket's actual risk contributions do - between 1 and the
    holding count, exactly 1 for a basket of one) and `riskShare` (each
    holding's own share of the basket's variance, a percentage per ticker
    summing to 100 - see services/portfolio.py's `compute_portfolio_risk`
    for the full model). All three are null, with a `reasons` entry each,
    wherever the basket cannot support them: fewer than two holdings with
    a complete price history over the window, or no measurable variance
    once aligned.

    Reads nothing and stores nothing, exactly as `simulate` does, and is
    bounded by the same `MAX_HOLDINGS`. A request that cannot be answered
    is a 400 naming what is wrong, a holding that does not exist is a 404
    naming the ticker, and a failure to reach the price source is a
    retryable 503 - the same contract `simulate` honours, so a caller
    already handling that response handles this one too.
    """
    try:
        return compute_portfolio_risk(
            [holding.model_dump() for holding in portfolio.holdings],
            period=portfolio.period,
            start=portfolio.start,
            end=portfolio.end,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
