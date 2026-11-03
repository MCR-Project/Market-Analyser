"""
official_measurement — the built-in, first-party measurement plugins
shipped with the app (correlation, % of ETF, value held, the
fund-relation family added by issue #107, the holding's-own-price-
history family added by issue #108, the metadata/income family added by
issue #109, the rolling correlation column added by issue #110, and the
days-to-liquidate column added by issue #111, the weighted correlation
column added by issue #185, and the valuation/ownership/growth family
added by issue #194).

measurements/__init__.py combines OFFICIAL_MEASUREMENTS with
addon_measurements.ADDON_MEASUREMENTS to build the full ALL_MEASUREMENTS
the registry serves.
"""

from measurements.official_measurements.capture_ratio import CaptureRatioMeasurement
from measurements.official_measurements.cap_weight_tilt import CapWeightTiltMeasurement
from measurements.official_measurements.correlation import CorrelationMeasurement
from measurements.official_measurements.days_to_liquidate import DaysToLiquidateMeasurement
from measurements.official_measurements.dividend_income import DividendIncomeMeasurement
from measurements.official_measurements.earnings_quarterly_growth import EarningsQuarterlyGrowthMeasurement
from measurements.official_measurements.etf_weight import EtfWeightMeasurement
from measurements.official_measurements.fund_relation import FundRelationMeasurement
from measurements.official_measurements.market_cap import MarketCapMeasurement
from measurements.official_measurements.max_drawdown import MaxDrawdownMeasurement
from measurements.official_measurements.ownership import OwnershipMeasurement
from measurements.official_measurements.pe_ratio import PeRatioMeasurement
from measurements.official_measurements.profit_margin import ProfitMarginMeasurement
from measurements.official_measurements.return_momentum import ReturnMomentumMeasurement
from measurements.official_measurements.revenue_per_share import RevenuePerShareMeasurement
from measurements.official_measurements.risk_contribution import RiskContributionMeasurement
from measurements.official_measurements.rolling_correlation import RollingCorrelationMeasurement
from measurements.official_measurements.tail_correlation import TailCorrelationMeasurement
from measurements.official_measurements.total_debt import TotalDebtMeasurement
from measurements.official_measurements.value_held import ValueHeldMeasurement
from measurements.official_measurements.volatility import VolatilityMeasurement
from measurements.official_measurements.weighted_correlation import WeightedCorrelationMeasurement

OFFICIAL_MEASUREMENTS = [
    CorrelationMeasurement(),
    # The same matrix, with each peer counting in proportion to its fund
    # weight (issue #185) - a second figure beside the plain average, not a
    # change to it.
    WeightedCorrelationMeasurement(),
    EtfWeightMeasurement(),
    ValueHeldMeasurement(),
    # How a holding relates to its fund (issue #107) - beyond ρ alone.
    RiskContributionMeasurement(),
    FundRelationMeasurement(),
    TailCorrelationMeasurement(),
    CaptureRatioMeasurement(),
    # Computed from a holding's own price history alone (issue #108) -
    # no fund, no benchmark, just the holding.
    VolatilityMeasurement(),
    MaxDrawdownMeasurement(),
    ReturnMomentumMeasurement(),
    # Metadata the database already holds, and the fund-level analogue of
    # how the simulator treats income (issue #109).
    MarketCapMeasurement(),
    CapWeightTiltMeasurement(),
    DividendIncomeMeasurement(),
    # The path a holding's correlation to its fund took, not just its
    # average over the window (issue #110).
    RollingCorrelationMeasurement(),
    # Whether a position could actually be sold, not just what it is
    # worth (issue #111).
    DaysToLiquidateMeasurement(),
    # Valuation, ownership, growth and balance-sheet figures straight from
    # yfinance's own .info, live-only (issue #194).
    PeRatioMeasurement(),
    OwnershipMeasurement(),
    ProfitMarginMeasurement(),
    EarningsQuarterlyGrowthMeasurement(),
    TotalDebtMeasurement(),
    RevenuePerShareMeasurement(),
]
