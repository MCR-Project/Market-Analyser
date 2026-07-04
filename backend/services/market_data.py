"""
Market data service — fetches and transforms data from Yahoo Finance via yfinance.

All functions follow the same pattern:
  1. Check the TTL cache for a cached result
  2. If miss, call yfinance, transform the response into a plain dict/list
  3. Cache the result and return it

yfinance is free but has quirks:
  - ETF holdings: only the top ~10 are exposed (not the full portfolio)
  - Ticker.info fields vary by security type (ETF vs stock)
  - Multi-ticker downloads return a MultiIndex DataFrame
  - Some historical rows contain NaN (holidays, delistings)
"""

import yfinance as yf
import pandas as pd
import numpy as np
from services.cache import cache
from config import (
    CACHE_TTL_SECONDS,
    CACHE_TTL_HOLDINGS,
    CORRELATION_PERIOD,
    CORRELATION_INTERVAL,
    SECTOR_TAG,
)


# ── ETF metadata ──────────────────────────────────────────────────────────────

def get_etf_info(etf_id: str) -> dict:
    """Fetch ETF name, category, AUM, and description.

    Returns a flat dict; cached for CACHE_TTL_HOLDINGS seconds.
    AUM is converted from raw totalAssets (int) to billions (float).
    """
    key = f"etf_info:{etf_id}"
    cached = cache.get(key)
    if cached:
        return cached

    ticker = yf.Ticker(etf_id)
    info = ticker.info or {}

    result = {
        "id": etf_id,
        "name": info.get("longName") or info.get("shortName") or etf_id,
        "cat": info.get("category") or info.get("fundFamily") or "",
        "aum": round((info.get("totalAssets") or 0) / 1e9, 2),
        "desc": info.get("longBusinessSummary") or info.get("description") or "",
    }

    cache.set(key, result, CACHE_TTL_HOLDINGS)
    return result


# ── ETF holdings ──────────────────────────────────────────────────────────────

# Yahoo sometimes returns both share classes of the same company
# (e.g. GOOG + GOOGL for Alphabet). We merge them under the canonical ticker.
DUPLICATE_TICKERS = {"GOOG": "GOOGL", "BRK-B": "BRK.B", "BF-B": "BF.B"}


def get_etf_holdings(etf_id: str) -> list[list]:
    """Fetch top holdings for an ETF as [[ticker, weight%], ...].

    Holdings are sorted by weight descending. Duplicate share classes
    (e.g. GOOG/GOOGL) are merged under the canonical ticker.

    yfinance exposes holdings via Ticker.funds_data.top_holdings, which
    returns a DataFrame with ticker as index and "% Assets" or
    "Holding Percent" as the weight column (format varies by fund).
    """
    key = f"etf_holdings:{etf_id}"
    cached = cache.get(key)
    if cached:
        return cached

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
            cache.set(key, holdings, CACHE_TTL_HOLDINGS)
            return holdings
    except Exception:
        pass

    # Cache empty result to avoid re-fetching on every request
    cache.set(key, [], CACHE_TTL_HOLDINGS)
    return []


# ── Stock metadata ────────────────────────────────────────────────────────────

def get_stock_info(ticker_symbol: str) -> dict:
    """Fetch stock name, sector, market cap, and other metadata.

    Sector is normalized to a short tag via SECTOR_TAG for display.
    Falls back to the raw sector string (truncated) if not in the map.
    """
    key = f"stock_info:{ticker_symbol}"
    cached = cache.get(key)
    if cached:
        return cached

    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info or {}

    sector = info.get("sector") or info.get("industry") or "Unknown"

    result = {
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

    cache.set(key, result, CACHE_TTL_HOLDINGS)
    return result


# ── Price series ──────────────────────────────────────────────────────────────

def get_price_series(
    ticker_symbol: str, period: str = "1y", interval: str = "1d"
) -> list[dict]:
    """Fetch historical close prices as a list of {date, close, volume} dicts.

    Rows with NaN close prices are dropped (can happen on holidays or
    around corporate actions). Volume NaNs are replaced with 0.

    Period and interval map directly to yfinance's history() parameters:
      period:   "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"
      interval: "1d", "1wk", "1mo"
    """
    key = f"series:{ticker_symbol}:{period}:{interval}"
    cached = cache.get(key)
    if cached:
        return cached

    ticker = yf.Ticker(ticker_symbol)
    hist = ticker.history(period=period, interval=interval)

    if hist.empty:
        return []

    # Drop rows where close is NaN (prevents JSON serialization crash)
    hist = hist.dropna(subset=["Close"])

    result = [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "close": round(float(row["Close"]), 2),
            "volume": int(row.get("Volume", 0) if not np.isnan(row.get("Volume", 0)) else 0),
        }
        for idx, row in hist.iterrows()
    ]

    cache.set(key, result, CACHE_TTL_SECONDS)
    return result


# ── Correlation matrix ────────────────────────────────────────────────────────

def compute_correlation_matrix(
    tickers: list[str],
    period: str = CORRELATION_PERIOD,
    interval: str = CORRELATION_INTERVAL,
) -> dict:
    """Compute pairwise Pearson correlation of daily returns for a set of tickers.

    Steps:
      1. Download close prices for all tickers in a single yf.download() call
      2. Compute daily percentage returns (pct_change)
      3. Build the NxN Pearson correlation matrix via DataFrame.corr()
      4. Extract summary statistics: per-ticker averages, strongest/weakest
         pairs, and the "hub" ticker (highest average ρ to all peers)

    yf.download() returns a MultiIndex DataFrame when fetching multiple tickers:
      columns = [("Close", "AAPL"), ("Close", "MSFT"), ...]
    We slice out the "Close" level to get a flat ticker-indexed DataFrame.

    Returns a dict with: matrix, tickers, averages, strongest, weakest, hub.
    """
    key = f"corr_matrix:{'_'.join(sorted(tickers))}:{period}:{interval}"
    cached = cache.get(key)
    if cached:
        return cached

    data = yf.download(
        tickers, period=period, interval=interval, progress=False, threads=True
    )

    if data.empty:
        return {"matrix": {}, "tickers": tickers}

    # Extract close prices — handle both MultiIndex and flat column layouts
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

    # Daily returns, drop the first NaN row
    returns = closes.pct_change().dropna()

    # Only keep tickers that actually have data
    available = [t for t in tickers if t in returns.columns]
    returns = returns[available]

    # NxN Pearson correlation
    corr_matrix = returns.corr()

    # Convert to nested dict, replacing any NaN with 0.0
    matrix = {}
    for t in available:
        matrix[t] = {}
        for t2 in available:
            val = corr_matrix.loc[t, t2]
            matrix[t][t2] = round(float(val), 4) if not np.isnan(val) else 0.0

    # ── Summary statistics ──
    averages = {}
    strongest = {"a": "", "b": "", "value": -1}
    weakest = {"a": "", "b": "", "value": 2}
    hub = {"ticker": available[0] if available else "", "avgCorr": 0}

    for i, a in enumerate(available):
        # Average correlation of ticker `a` to all other tickers
        others = [matrix[a].get(b, 0) for b in available if b != a]
        avg = sum(others) / len(others) if others else 0
        averages[a] = round(avg, 4)
        if avg > hub["avgCorr"]:
            hub = {"ticker": a, "avgCorr": round(avg, 4)}

        # Check upper triangle for strongest/weakest pair
        for j in range(i + 1, len(available)):
            b = available[j]
            v = matrix[a].get(b, 0)
            if v > strongest["value"]:
                strongest = {"a": a, "b": b, "value": v}
            if v < weakest["value"]:
                weakest = {"a": a, "b": b, "value": v}

    result = {
        "matrix": matrix,
        "tickers": available,
        "averages": averages,
        "strongest": strongest,
        "weakest": weakest,
        "hub": hub,
    }

    cache.set(key, result, CACHE_TTL_SECONDS)
    return result
