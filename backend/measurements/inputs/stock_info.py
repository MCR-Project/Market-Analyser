"""
Input getter: per-holding stock metadata (name, sector, market cap, ...)
for a set of tickers (issue #102).

Like correlation_matrix and price_frame, this getter needs a ticker list
rather than an etf_id directly - measurements first resolve holdings via
inputs.holdings.get_holdings(etf_id), then pass the resulting tickers
here.

There is no bulk service-layer read to widen here the way price_frame's
was: services.market_data.get_stock_info is already cached per ticker
(api/routes.py's own /api/stocks/batch loops the same way), so looping it
costs one cache lookup per holding rather than one query per holding -
the concern the README's data pipeline section reserves for something
that actually hits Supabase or yfinance.
"""

from services.market_data import get_stock_info as _get_stock_info


def get_stock_info(tickers: list[str]) -> dict:
    """Fetch name/sector/market cap/... for every ticker in `tickers`."""
    return {ticker: _get_stock_info(ticker) for ticker in tickers}


def _sample(etf_id: str, tickers: list[str]):
    """Real value of this input for one ETF, for a doc's worked example."""
    return get_stock_info(tickers) if tickers else {}


# Self-description for the documentation page - see inputs/__init__.py.
INPUT_SPEC = {
    "description": (
        "Each holding's own metadata: name, sector, market cap in USD, "
        "currency and exchange. Read from the database per ticker, "
        "falling back to a live lookup for anything not yet synced."
    ),
    "defaults": {},
    "sample": _sample,
    # Cost characteristic (issue #115) — one read per holding
    # ("per_holding": this loops get_stock_info once per ticker, per this
    # module's own docstring, not a single bulk query the way price_frame's
    # is), no price history ("windowed": False), each individual lookup
    # DB-first with a live fallback ("live").
    "cost": {"scaling": "per_holding", "network": "live", "windowed": False},
}
