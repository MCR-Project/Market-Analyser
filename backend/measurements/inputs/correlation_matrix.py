"""
Input getter: pairwise Pearson correlation matrix (+ derived stats) for a
set of tickers.

Unlike holdings/etf_info, this getter needs a ticker list rather than an
etf_id directly — measurements first resolve holdings via
inputs.holdings.get_holdings(etf_id), then pass the resulting tickers
here. `period` defaults to a fixed lookback baked into the code; it is
never something the frontend supplies.
"""

from config import CORRELATION_INTERVAL
from services.market_data import compute_correlation_matrix

DEFAULT_PERIOD = "1y"


def get_correlation_matrix(tickers: list[str], period: str = DEFAULT_PERIOD) -> dict:
    """Compute the correlation matrix and summary stats (averages, strongest/weakest pair, hub) for `tickers`."""
    return compute_correlation_matrix(tickers, period=period)


def _sample(etf_id: str, tickers: list[str]):
    """Real value of this input for one ETF, for a doc's worked example.

    Unlike the other getters this one takes tickers rather than an
    etf_id — the caller has already resolved the fund's full holdings.
    It must be the full list, not the handful the doc ends up showing:
    the averages and the hub this returns are properties of the whole
    set, and recomputing them over five tickers would contradict the
    measurement's own output. The caller slices the result afterwards.
    """
    return get_correlation_matrix(tickers) if tickers else {}


# Self-description for the documentation page — see inputs/__init__.py.
# The defaults matter to a reader: they are the window the numbers
# describe, and nothing in the UI exposes them.
INPUT_SPEC = {
    "description": (
        "Pairwise Pearson correlation of daily returns across a set of "
        "tickers, plus the summary statistics derived from it: each "
        "ticker's average correlation to its peers, the strongest and "
        "weakest pairs, and the most-connected 'hub' ticker."
    ),
    "defaults": {"period": DEFAULT_PERIOD, "interval": CORRELATION_INTERVAL},
    "sample": _sample,
    # Cost characteristic (issue #115) — a genuine pairwise sweep, every
    # ticker against every other ("pairwise"), over a bounded price
    # history ("windowed": True), through get_closes' own live-merge path
    # ("live"). The heaviest combination any input getter in this package
    # declares, which is the whole reason a correlation-derived column is
    # expected to rate above a plain weight lookup without anyone having
    # to say so by hand.
    "cost": {"scaling": "pairwise", "network": "live", "windowed": True},
}
