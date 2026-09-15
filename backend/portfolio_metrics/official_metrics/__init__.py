"""
Official portfolio metrics — one instance per class, in the order
PortfolioSummary's default tile grid shows them (issue #104).

Migrated from services/portfolio.py's `_metrics()` dict with unchanged
arithmetic, keys and rounding — this list only adds a label, a family, a
formula, a null rule and a doc pointer to each one; every value still
comes from the same response `_metrics()` has always built.
"""

from portfolio_metrics.official_metrics.cagr import CagrMetric
from portfolio_metrics.official_metrics.contributed import ContributedMetric
from portfolio_metrics.official_metrics.dividend_income import DividendIncomeMetric
from portfolio_metrics.official_metrics.dividend_yield import DividendYieldMetric
from portfolio_metrics.official_metrics.final_value import FinalValueMetric
from portfolio_metrics.official_metrics.gain import GainMetric
from portfolio_metrics.official_metrics.income_unknown_for import IncomeUnknownForMetric
from portfolio_metrics.official_metrics.max_drawdown import MaxDrawdownMetric
from portfolio_metrics.official_metrics.money_weighted_return import MoneyWeightedReturnMetric
from portfolio_metrics.official_metrics.total_invested import TotalInvestedMetric
from portfolio_metrics.official_metrics.total_return import TotalReturnMetric
from portfolio_metrics.official_metrics.volatility import VolatilityMetric

OFFICIAL_METRICS = [
    # The portfolio family — time-weighted, today's default five tiles.
    FinalValueMetric(),
    TotalReturnMetric(),
    CagrMetric(),
    VolatilityMetric(),
    MaxDrawdownMetric(),
    # The account family — money-weighted, shown once something is
    # actually contributed.
    TotalInvestedMetric(),
    ContributedMetric(),
    GainMetric(),
    MoneyWeightedReturnMetric(),
    # The dividend family — prose, never tiles (issue #68).
    DividendIncomeMetric(),
    DividendYieldMetric(),
    IncomeUnknownForMetric(),
]
