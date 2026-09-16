"""
Official portfolio metrics — one instance per class, in the order
PortfolioSummary's default tile grid shows them (issue #104).

Migrated from services/portfolio.py's `_metrics()` dict with unchanged
arithmetic, keys and rounding — this list only adds a label, a family, a
formula, a null rule and a doc pointer to each one; every value still
comes from the same response `_metrics()` has always built. Time under
water, share under water, pain index, Calmar, Sharpe and Sortino (issue
#112) followed the same rule once `_metrics()` grew them: the arithmetic
lives in services/stats.py and services/portfolio.py, not here.

The last three (issue #105) are the odd ones out: `computed_from
="etf_id"`, not "run" — a fund's own diversification ratio, its variance
concentration and its tracked-weight coverage, read via
services/fund_metrics.py rather than services/portfolio.py. They share
this registry, this manifest endpoint and this doc/example machinery
with the run-based metrics above rather than standing up a parallel one,
per issue #105's own decision ("different metrics, one mechanism") — the
frontend's own fund-metrics card only ever asks for the entries whose
`computed_from` is "etf_id".
"""

from portfolio_metrics.official_metrics.cagr import CagrMetric
from portfolio_metrics.official_metrics.calmar import CalmarMetric
from portfolio_metrics.official_metrics.contributed import ContributedMetric
from portfolio_metrics.official_metrics.diversification_ratio import DiversificationRatioMetric
from portfolio_metrics.official_metrics.dividend_income import DividendIncomeMetric
from portfolio_metrics.official_metrics.dividend_yield import DividendYieldMetric
from portfolio_metrics.official_metrics.final_value import FinalValueMetric
from portfolio_metrics.official_metrics.gain import GainMetric
from portfolio_metrics.official_metrics.income_unknown_for import IncomeUnknownForMetric
from portfolio_metrics.official_metrics.max_drawdown import MaxDrawdownMetric
from portfolio_metrics.official_metrics.money_weighted_return import MoneyWeightedReturnMetric
from portfolio_metrics.official_metrics.pain_index import PainIndexMetric
from portfolio_metrics.official_metrics.share_under_water import ShareUnderWaterMetric
from portfolio_metrics.official_metrics.sharpe import SharpeMetric
from portfolio_metrics.official_metrics.sortino import SortinoMetric
from portfolio_metrics.official_metrics.time_under_water import TimeUnderWaterMetric
from portfolio_metrics.official_metrics.top5_variance_share import Top5VarianceShareMetric
from portfolio_metrics.official_metrics.total_invested import TotalInvestedMetric
from portfolio_metrics.official_metrics.total_return import TotalReturnMetric
from portfolio_metrics.official_metrics.tracked_weight_coverage import TrackedWeightCoverageMetric
from portfolio_metrics.official_metrics.volatility import VolatilityMetric

OFFICIAL_METRICS = [
    # The portfolio family — time-weighted, today's default five tiles.
    FinalValueMetric(),
    TotalReturnMetric(),
    CagrMetric(),
    VolatilityMetric(),
    MaxDrawdownMetric(),
    # Time under water, pain index and the three risk-adjusted ratios
    # (issue #112) - also portfolio-family, but optional rather than
    # among the default five, so an already-busy grid doesn't suddenly
    # grow by half on an existing view.
    TimeUnderWaterMetric(),
    ShareUnderWaterMetric(),
    PainIndexMetric(),
    CalmarMetric(),
    SharpeMetric(),
    SortinoMetric(),
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
    # The fund-level families (issue #105) — computed_from="etf_id",
    # shown on the fund metrics card rather than the portfolio summary.
    DiversificationRatioMetric(),
    Top5VarianceShareMetric(),
    TrackedWeightCoverageMetric(),
]
