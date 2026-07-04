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
  GET /api/series/{ticker}       — historical price series
  GET /api/correlation/{etf_id}  — Pearson correlation matrix for holdings
  GET /api/sectors/{etf_id}      — sector weight breakdown
"""

from fastapi import APIRouter, Query, HTTPException
from services.market_data import (
    get_etf_info,
    get_etf_holdings,
    get_stock_info,
    get_price_series,
    compute_correlation_matrix,
)
from config import DEFAULT_ETFS, SECTOR_TAG

router = APIRouter(prefix="/api")


# ── ETF endpoints ─────────────────────────────────────────────────────────────

@router.get("/etfs")
def list_etfs():
    """List all tracked ETFs with summary info (no holdings array).

    Iterates DEFAULT_ETFS from config, fetches info + holding count for each.
    The holding count comes from get_etf_holdings length, not from the info dict.
    """
    results = []
    for etf_id in DEFAULT_ETFS:
        info = get_etf_info(etf_id)
        holdings = get_etf_holdings(etf_id)
        results.append({**info, "holdingCount": len(holdings)})
    return results


@router.get("/etf/{etf_id}")
def get_etf(etf_id: str):
    """Full ETF detail including the holdings array.

    Returns 404 if yfinance returns no meaningful name (indicates the
    ticker doesn't exist or isn't an ETF).
    """
    etf_id = etf_id.upper()
    info = get_etf_info(etf_id)
    holdings = get_etf_holdings(etf_id)
    if not info["name"] or info["name"] == etf_id:
        raise HTTPException(404, f"ETF '{etf_id}' not found or no data available")
    return {**info, "holdings": holdings}


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
    period: str = Query("1y", description="1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max"),
    interval: str = Query("1d", description="1m, 5m, 15m, 1h, 1d, 1wk, 1mo"),
):
    """Historical price series for charting.

    Returns an array of {date, close, volume} objects. The frontend
    maps the `close` values into the AreaChart sparkline.
    """
    ticker = ticker.upper()
    data = get_price_series(ticker, period=period, interval=interval)
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
    holdings = get_etf_holdings(etf_id)
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
    holdings = get_etf_holdings(etf_id)
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
