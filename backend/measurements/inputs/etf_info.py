"""
Input getter: ETF metadata (name, category, AUM, description, sector focus).

The only required parameter is `etf_id` — measurements fetch this
themselves and never need the frontend to supply anything beyond which
ETF they're computing for.
"""

from services.market_data import get_etf_info as _get_etf_info


def get_etf_info(etf_id: str) -> dict:
    """Fetch ETF name, category, AUM (in billions USD), description, and sector focus override."""
    return _get_etf_info(etf_id.upper())
