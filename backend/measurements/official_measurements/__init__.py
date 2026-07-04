"""
official_measurement — the built-in, first-party measurement plugins
shipped with the app (correlation, % of ETF, value held).

measurements/__init__.py combines OFFICIAL_MEASUREMENTS with
addon_measurements.ADDON_MEASUREMENTS to build the full ALL_MEASUREMENTS
the registry serves.
"""

from measurements.official_measurements.correlation import CorrelationMeasurement
from measurements.official_measurements.etf_weight import EtfWeightMeasurement
from measurements.official_measurements.value_held import ValueHeldMeasurement

OFFICIAL_MEASUREMENTS = [
    CorrelationMeasurement(),
    EtfWeightMeasurement(),
    ValueHeldMeasurement(),
]
