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

# How long market_data._live() stops calling yfinance at all once Yahoo has
# answered a live call with a 429 (issue #92). Not a cache TTL - it is not
# keyed to any one request, and it never serves a cached answer, only a
# fresh 503 - but it lives alongside the other durations for the same
# reason: retrying a rate limit every few seconds is exactly the traffic
# that keeps it in place, so every request pays the same cooldown instead
# of each one re-discovering the 429 for itself.
RATE_LIMIT_COOLDOWN_SECONDS = 60

# How often a `refresh=true` request may actually bypass the cache for one
# ETF (issue #93). Anyone can trigger GET /api/etf/{id}?refresh=true, so
# without this, an anonymous client could force an upstream fetch for the
# same fund as often as it likes. Per-ETF rather than per-client: the cost
# this guards against is an upstream call for that fund, whoever asks for
# it. A request that arrives inside the window is served exactly like a
# normal request rather than refused - it still gets an answer, just not
# a freshly-fetched one.
FORCE_REFRESH_THROTTLE_SECONDS = 300

# Default parameters for correlation computation
CORRELATION_PERIOD = "1y"    # lookback window for daily returns
CORRELATION_INTERVAL = "1d"  # granularity of return observations

# Fewer overlapping daily returns than this and a pair's correlation is
# unknown, not zero (issue #97) - a Pearson r computed on a handful of rows
# is mostly noise, and reporting one at all invites reading it as a real
# measurement. 30 is about six trading weeks: short enough that a holding
# priced for a full quarter still gets a real number, long enough to
# exclude a holding that listed only two or three weeks ago.
MIN_OVERLAPPING_RETURNS = 30

# Which fund/ticker a measurement's documentation computes its worked
# example against, when neither the measurement class nor its doc's
# frontmatter names one of its own. A fixed default (rather than whatever
# the reader happens to have open) keeps a doc page reproducible: the same
# URL shows the same numbers to everyone.
DOCS_EXAMPLE_ETF = "SPY"
DOCS_EXAMPLE_STOCK = "AAPL"

# Which basket a portfolio metric's documentation simulates for its worked
# example, when the metric class names no `example_portfolio` of its own
# (issue #104) - the run-based counterpart to DOCS_EXAMPLE_ETF above, same
# reasoning: a fixed default keeps a doc page reproducible rather than
# depending on whatever portfolio the reader happens to have open.
#
# Carries a recurring contribution on purpose. Metrics split into two
# families - portfolio (time-weighted: total return, CAGR, volatility,
# drawdown) and account (money-weighted: paid in, contributed, gain,
# money-weighted return) - and the second family is only ever non-trivial
# once something has actually been contributed. A single lump sum would
# leave every account-family metric's worked example equal to its
# portfolio-family sibling, illustrating nothing about the split the two
# families exist to make. $200/month over 5y is enough elapsed time for
# CAGR, volatility and the money-weighted return to all be real numbers
# rather than a null this particular example happens to hit.
DOCS_EXAMPLE_PORTFOLIO = {
    "holdings": [{"ticker": "SPY", "weight": 60}, {"ticker": "AGG", "weight": 40}],
    "value": 10_000,
    "period": "5y",
    "rebalance": "none",
    "contribution": {"amount": 200, "frequency": "monthly"},
}

# Shared window vocabulary for window-aware measurement columns (issue
# #101). A plugin opts in to a table-wide window control by setting its own
# window_options/window_default to these - or occasionally a narrower
# subset, if a particular metric genuinely cannot answer over the whole
# range - rather than leaving window_options empty, which is what tells
# the registry not to generate a window query parameter for it at all.
# Values are the same vocabulary PERIOD_TO_DAYS already uses, so a plugin
# can pass one straight through to get_price_series/get_closes as `period`
# without translating it first.
MEASUREMENT_WINDOW_OPTIONS = [
    {"value": "3mo", "label": "3M"},
    {"value": "6mo", "label": "6M"},
    {"value": "1y", "label": "1Y"},
    {"value": "5y", "label": "5Y"},
    {"value": "max", "label": "Max"},
]
MEASUREMENT_WINDOW_DEFAULT = "1y"

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
