"""
Application-wide configuration constants.

Cache TTLs, period-to-days lookback windows, and sector label normalization
map. yfinance and Yahoo Finance use inconsistent sector names across endpoints
(e.g. "Technology" vs "Information Technology"), so SECTOR_TAG maps all
known variants to a short uppercase tag for display.
"""

# How long to cache different data types (in seconds).
# Price data changes intraday; holdings change rarely.
CACHE_TTL_SECONDS = 900      # 15 min — price series, correlations
CACHE_TTL_HOLDINGS = 3600    # 1 hour — ETF holdings, stock metadata

# Short TTL used when an ETF info/holdings fetch fell back to a live
# yfinance call because Supabase returned no row (miss or transient error).
# Caching that fallback for the full hour above would keep serving a
# stale/partial result long after the DB is actually able to answer -
# 10s means the next request naturally retries the DB almost immediately.
CACHE_TTL_HOLDINGS_FALLBACK = 10

# Default parameters for correlation computation
CORRELATION_PERIOD = "1y"    # lookback window for daily returns
CORRELATION_INTERVAL = "1d"  # granularity of return observations

# Maps a yfinance-style `period` string to a lookback window in days, used to
# filter the `prices` table by date when reading price history from Supabase.
# "max" has no entry - it means no lower bound (select all rows).
PERIOD_TO_DAYS = {
    "1d": 1, "5d": 5, "1mo": 30, "3mo": 90,
    "6mo": 182, "1y": 365, "2y": 730, "5y": 1825,
}

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
