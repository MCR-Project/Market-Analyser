"""
Input getter: ETF holdings.

The only required parameter is `etf_id` — measurements fetch this
themselves and never need the frontend to supply anything beyond which
ETF they're computing for.
"""

from services.market_data import get_etf_holdings


def get_holdings(etf_id: str) -> list[list]:
    """Fetch top holdings for an ETF as [[ticker, weight%], ...], sorted by weight descending."""
    return get_etf_holdings(etf_id.upper())
