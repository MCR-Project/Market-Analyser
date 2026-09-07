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
  GET /api/series/{ticker}       — historical price series, by period or
                                   by explicit start/end window
  GET /api/correlation/{etf_id}  — Pearson correlation matrix for holdings
  GET /api/sectors/{etf_id}      — sector weight breakdown
  POST /api/portfolio/simulate   — value a basket of tickers over a window
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
from services.portfolio import simulate_portfolio
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

    # Count edges above threshold for the network view
    if threshold > 0:
        edge_count = 0
        available = result["tickers"]
        for i, a in enumerate(available):
            for j in range(i + 1, len(available)):
                b = available[j]
                if result["matrix"].get(a, {}).get(b, 0) >= threshold:
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
    start: str | None = Field(None, description="Window start, ISO-8601 (YYYY-MM-DD), inclusive")
    end: str | None = Field(None, description="Window end, ISO-8601 (YYYY-MM-DD), inclusive")
    rebalance: str = Field("none", description="none, monthly, quarterly, yearly")


@router.post("/portfolio/simulate")
def post_portfolio_simulate(portfolio: PortfolioIn):
    """Value a basket of tickers over a window, day by day.

    Returns the run in columnar form - `dates`, `total`, `cash`, and a
    `values` array per holding - plus the normalised weight and first
    priced date of each holding. See services/portfolio.py for the model
    itself: buy and hold unless a rebalance frequency is named, weights
    normalised, and an allocation held as cash until its holding lists.

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
            start=portfolio.start,
            end=portfolio.end,
            rebalance=portfolio.rebalance,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
