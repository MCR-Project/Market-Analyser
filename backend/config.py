"""
Application-wide configuration constants.

Cache TTLs, default ETF universe, and sector label normalization map.
yfinance and Yahoo Finance use inconsistent sector names across endpoints
(e.g. "Technology" vs "Information Technology"), so SECTOR_TAG maps all
known variants to a short uppercase tag for display.
"""

# How long to cache different data types (in seconds).
# Price data changes intraday; holdings change rarely.
CACHE_TTL_SECONDS = 900      # 15 min — price series, correlations
CACHE_TTL_HOLDINGS = 3600    # 1 hour — ETF holdings, stock metadata

# Default parameters for correlation computation
CORRELATION_PERIOD = "1y"    # lookback window for daily returns
CORRELATION_INTERVAL = "1d"  # granularity of return observations

# ETFs shown in the picker and loaded on startup.
# Fixed list, manually maintained - a placeholder until automatic ETF/ticker
# discovery lands (see the "Find a way to automatically fetch tickers and
# etfs" issue). Also the list scripts/fetch_daily.py syncs into Supabase.
DEFAULT_ETFS = ["SPY", "QQQ", "VTI", "URTH", "SMH", "XLK", "SOXX", "ARKK"]

# Normalize sector names from yfinance → short display tags.
# Yahoo returns different strings depending on the endpoint
# (e.g. Ticker.info vs funds_data), so we map all known variants.
SECTOR_TAG = {
    "Technology": "TECH",
    "Information Technology": "TECH",
    "Communication Services": "COMMS",
    "Consumer Cyclical": "CONS",
    "Consumer Discretionary": "CONS",
    "Consumer Defensive": "STAPLES",
    "Consumer Staples": "STAPLES",
    "Financial Services": "FIN",
    "Financials": "FIN",
    "Healthcare": "HEALTH",
    "Health Care": "HEALTH",
    "Industrials": "IND",
    "Energy": "ENERGY",
    "Utilities": "UTIL",
    "Real Estate": "RE",
    "Basic Materials": "MATL",
}
