"""
official_measurement — the built-in, first-party measurement plugins
shipped with the app (correlation, % of ETF, value held, the
fund-relation family added by issue #107, the holding's-own-price-
history family added by issue #108, and the metadata/income family
added by issue #109).

measurements/__init__.py combines OFFICIAL_MEASUREMENTS with
addon_measurements.ADDON_MEASUREMENTS to build the full ALL_MEASUREMENTS
the registry serves.
"""

from measurements.official_measurements.capture_ratio import CaptureRatioMeasurement
from measurements.official_measurements.cap_weight_tilt import CapWeightTiltMeasurement
from measurements.official_measurements.correlation import CorrelationMeasurement
from measurements.official_measurements.dividend_income import DividendIncomeMeasurement
from measurements.official_measurements.etf_weight import EtfWeightMeasurement
from measurements.official_measurements.fund_relation import FundRelationMeasurement
from measurements.official_measurements.market_cap import MarketCapMeasurement
from measurements.official_measurements.max_drawdown import MaxDrawdownMeasurement
from measurements.official_measurements.return_momentum import ReturnMomentumMeasurement
from measurements.official_measurements.risk_contribution import RiskContributionMeasurement
from measurements.official_measurements.tail_correlation import TailCorrelationMeasurement
from measurements.official_measurements.value_held import ValueHeldMeasurement
from measurements.official_measurements.volatility import VolatilityMeasurement

OFFICIAL_MEASUREMENTS = [
    CorrelationMeasurement(),
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
]
