"""
Input getter: a fund's own weighted-return index, built from its tracked
holdings (issue #107).

Every column answering "how does this holding relate to its fund" -
beta, R-squared, idiosyncratic volatility, tail correlation, the two
capture ratios - needs the same thing: a single "r_fund" series to
compare each holding against. This getter builds it once so five
different measurements read the identical benchmark rather than each
constructing (and potentially disagreeing about) their own.

Like correlation_matrix and price_frame, this takes a ticker list rather
than an etf_id directly - measurements first resolve holdings via
inputs.holdings.get_holdings(etf_id), then pass the resulting tickers
and their weights here.
"""

from measurements.inputs.price_frame import DEFAULT_PERIOD, get_aligned_closes
from services.stats import weighted_index


def get_fund_index(tickers: list[str], weights: dict[str, float], period: str = DEFAULT_PERIOD) -> dict:
    """The fund's own weighted-return index over `period`, plus the
    aligned per-ticker closes it was built from.

    Returns `{"dates": [...], "values_by_ticker": {t: [...], ...},
    "fund_values": [...] | None}` - `values_by_ticker` only carries a
    ticker priced for every date in the window (see `get_aligned_closes`
    for why a ragged one is excluded rather than narrowing the window to
    fit it); `fund_values` is `None` when fewer than two tickers made
    that cut, since `weighted_index` itself has nothing to build an index
    from at that point.
    """
    dates, values_by_ticker = get_aligned_closes(tickers, period=period)
    if len(values_by_ticker) < 2:
        return {"dates": dates, "values_by_ticker": values_by_ticker, "fund_values": None}

    used_weights = {t: weights.get(t, 0.0) for t in values_by_ticker}
    fund_values = weighted_index(values_by_ticker, used_weights, dates)
    return {"dates": dates, "values_by_ticker": values_by_ticker, "fund_values": fund_values}


def _sample(etf_id: str, tickers: list[str]):
    """Real value of this input for one ETF, for a doc's worked example.

    Unlike holdings/etf_info this one takes tickers rather than an
    etf_id - the caller has already resolved the fund's full holdings -
    and, like correlation_matrix, needs the weight of each one too, so it
    resolves holdings itself rather than accepting weights as a second
    parameter no other sampler in this package takes.
    """
    if not tickers:
        return {"dates": [], "values_by_ticker": {}, "fund_values": None}
    from measurements.inputs.holdings import get_holdings
    weights = {t: w for t, w in get_holdings(etf_id)}
    return get_fund_index(tickers, weights)


# Self-description for the documentation page - see inputs/__init__.py.
INPUT_SPEC = {
    "description": (
        "The fund's own weighted-return index: the weighted average "
        "return of every tracked holding with a complete price history "
        "over the window, compounded into a single series starting at "
        "100 - the common benchmark every per-holding relation-to-fund "
        "column (beta, R-squared, idiosyncratic volatility, tail "
        "correlation, upside/downside capture) is computed against."
    ),
    "defaults": {"period": DEFAULT_PERIOD},
    "sample": _sample,
}
