"""
official_measurement — the built-in, first-party measurement plugins
shipped with the app (correlation, % of ETF, value held, and the
fund-relation family added by issue #107).

measurements/__init__.py combines OFFICIAL_MEASUREMENTS with
addon_measurements.ADDON_MEASUREMENTS to build the full ALL_MEASUREMENTS
the registry serves.
"""

from measurements.official_measurements.capture_ratio import CaptureRatioMeasurement
from measurements.official_measurements.correlation import CorrelationMeasurement
from measurements.official_measurements.etf_weight import EtfWeightMeasurement
from measurements.official_measurements.fund_relation import FundRelationMeasurement
from measurements.official_measurements.risk_contribution import RiskContributionMeasurement
from measurements.official_measurements.tail_correlation import TailCorrelationMeasurement
from measurements.official_measurements.value_held import ValueHeldMeasurement

OFFICIAL_MEASUREMENTS = [
    CorrelationMeasurement(),
    EtfWeightMeasurement(),
    ValueHeldMeasurement(),
    # How a holding relates to its fund (issue #107) - beyond ρ alone.
    RiskContributionMeasurement(),
    FundRelationMeasurement(),
    TailCorrelationMeasurement(),
    CaptureRatioMeasurement(),
]
