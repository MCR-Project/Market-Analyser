"""
Input getter: per-holding valuation, ownership, growth and balance-sheet
figures (trailing/forward P/E, profit margin, held % insiders/institutions,
earnings quarterly growth, total debt, revenue per share) for a set of
tickers (issue #194).

Like stock_info, this getter needs a ticker list rather than an etf_id
directly - measurements first resolve holdings via
inputs.holdings.get_holdings(etf_id), then pass the resulting tickers here.

No bulk service-layer read to widen here either, for the same reason
stock_info's own docstring gives: services.market_data.get_stock_fundamentals
is already cached per ticker, so looping it costs one cache lookup per
holding rather than a query per holding.
"""

from services.market_data import get_stock_fundamentals


def get_fundamentals(tickers: list[str]) -> dict:
    """Fetch trailing/forward P/E, profit margin, held % insiders/
    institutions, earnings quarterly growth, total debt and revenue per
    share for every ticker in `tickers`."""
    return {ticker: get_stock_fundamentals(ticker) for ticker in tickers}


def _sample(etf_id: str, tickers: list[str]):
    """Real value of this input for one ETF, for a doc's worked example."""
    return get_fundamentals(tickers) if tickers else {}


# Self-description for the documentation page - see inputs/__init__.py.
INPUT_SPEC = {
    "description": (
        "Each holding's own trailing and forward P/E, profit margin, held "
        "% insiders, held % institutions, earnings quarterly growth, total "
        "debt and revenue per share, straight from yfinance's own `.info`. "
        "Live only - there is no database column for any of these - and "
        "null wherever Yahoo has nothing for that ticker (an ETF held "
        "inside another ETF, a security of a type .info doesn't cover it "
        "for)."
    ),
    "defaults": {},
    "sample": _sample,
    # Cost characteristic (issue #115) - one live read per holding
    # ("per_holding", the same loop stock_info's own cost states), no price
    # history ("windowed": False), and always live - there is no DB path at
    # all for this input, per get_stock_fundamentals' own docstring.
    "cost": {"scaling": "per_holding", "network": "live", "windowed": False},
}
