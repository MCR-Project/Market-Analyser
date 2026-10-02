"""
Input getter: ETF holdings.

The only required parameter is `etf_id` — measurements fetch this
themselves and never need the frontend to supply anything beyond which
ETF they're computing for.
"""

from config import CORRELATION_PERIOD
from services.market_data import deep_fill_exclusions, get_etf_holdings


def get_holdings(etf_id: str) -> list[list]:
    """Fetch top holdings for an ETF as [[ticker, weight%], ...], sorted by weight
    descending - the tracked ones, and, while the fund is deep-filled (issue #171),
    its Untracked ones after them."""
    holdings, _ = get_etf_holdings(etf_id.upper())
    return holdings


def get_tail_reasons(etf_id: str, window: str | None = None) -> dict[str, str]:
    """`{ticker: reason}` for a deep-filled fund's Untracked holdings that cannot
    answer a price read over `window` (the measurement's own, or the one-year
    default every unwindowed price read uses): the ones the Deep-fill failed to
    fetch, and all of them for a window reaching further back than the year it
    fetched. Empty for a fund that is not deep-filled. `MeasurementBase.run`
    puts these beside a null value as its reason, so a dash in the tail says why."""
    return deep_fill_exclusions(etf_id.upper(), window or CORRELATION_PERIOD)


def _sample(etf_id: str, tickers: list[str]):
    """Real value of this input for one ETF, for a doc's worked example."""
    return get_holdings(etf_id)


# Self-description for the documentation page — see inputs/__init__.py.
INPUT_SPEC = {
    "description": (
        "The fund's constituents and their portfolio weights, as "
        "[ticker, weight%] pairs sorted by weight. Only holdings weighing "
        "at least 1% in one of their ETFs are tracked, so the weights do "
        "not sum to 100% - unless the fund has been deep-filled, when its "
        "Untracked holdings are listed after the tracked ones for as long as "
        "that lasts."
    ),
    "defaults": {},
    "sample": _sample,
    # Cost characteristic (issue #115) — one call describes the whole
    # fund, so this does not grow with holding count ("per_request"), and
    # reads no price history at all ("windowed": False). "live": the
    # underlying get_etf_holdings still falls back to a live yfinance
    # call on a cache/DB miss (services/CLAUDE.md's DB-first pattern),
    # which is what the registry's cost model actually cares about.
    "cost": {"scaling": "per_request", "network": "live", "windowed": False},
}
