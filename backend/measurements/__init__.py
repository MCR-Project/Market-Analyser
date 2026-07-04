"""
Measurement plugin barrel — combines official and addon measurements.

Adding a new official measurement:
  1. Create a new file in official_measurement/ (e.g. volatility.py)
  2. Subclass MeasurementBase, fill in metadata + implement
     fetch_inputs/compute/render_cell
  3. Import it and add the instance to OFFICIAL_MEASUREMENTS in
     official_measurement/__init__.py

Adding a custom/addon measurement: same steps, but in addon_measurements/
(add the instance to ADDON_MEASUREMENTS there instead).

The registry reads ALL_MEASUREMENTS to auto-register routes and build the manifest.
"""

from measurements.official_measurements import OFFICIAL_MEASUREMENTS
from measurements.addon_measurements import ADDON_MEASUREMENTS

ALL_MEASUREMENTS = [*OFFICIAL_MEASUREMENTS, *ADDON_MEASUREMENTS]
