"""
Input getter: ETF holdings.

The only required parameter is `etf_id` — measurements fetch this
themselves and never need the frontend to supply anything beyond which
ETF they're computing for.
"""

from services.market_data import get_etf_holdings


def get_holdings(etf_id: str) -> list[list]:
    """Fetch top holdings for an ETF as [[ticker, weight%], ...], sorted by weight descending."""
    holdings, _ = get_etf_holdings(etf_id.upper())
    return holdings


def _sample(etf_id: str, tickers: list[str]):
    """Real value of this input for one ETF, for a doc's worked example."""
    return get_holdings(etf_id)


# Self-description for the documentation page — see inputs/__init__.py.
INPUT_SPEC = {
    "description": (
        "The fund's constituents and their portfolio weights, as "
        "[ticker, weight%] pairs sorted by weight. Only holdings weighing "
        "at least 1% in one of their ETFs are tracked, so the weights do "
        "not sum to 100%."
    ),
    "defaults": {},
    "sample": _sample,
}
