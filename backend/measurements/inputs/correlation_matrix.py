"""
Input getter: pairwise Pearson correlation matrix (+ derived stats) for a
set of tickers.

Unlike holdings/etf_info, this getter needs a ticker list rather than an
etf_id directly — measurements first resolve holdings via
inputs.holdings.get_holdings(etf_id), then pass the resulting tickers
here. `period` defaults to a fixed lookback baked into the code; it is
never something the frontend supplies.
"""

from services.market_data import compute_correlation_matrix

DEFAULT_PERIOD = "1y"


def get_correlation_matrix(tickers: list[str], period: str = DEFAULT_PERIOD) -> dict:
    """Compute the correlation matrix and summary stats (averages, strongest/weakest pair, hub) for `tickers`."""
    return compute_correlation_matrix(tickers, period=period)
