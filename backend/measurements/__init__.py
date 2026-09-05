"""
Measurement plugin barrel — combines official and addon measurements.

Adding a new official measurement:
  1. Create a new file in official_measurement/ (e.g. volatility.py)
  2. Subclass MeasurementBase, fill in metadata + implement
     fetch_inputs/compute/render_cell
  3. Import it and add the instance to OFFICIAL_MEASUREMENTS in
     official_measurement/__init__.py
  4. Optionally write volatility.mdx next to it to document what it
     measures — see measurements/docs.py for the file format

Adding a custom/addon measurement: same steps, but in addon_measurements/
(add the instance to ADDON_MEASUREMENTS there instead).

The registry reads ALL_MEASUREMENTS to auto-register routes and build the manifest.
"""

from measurements.official_measurements import OFFICIAL_MEASUREMENTS
from measurements.addon_measurements import ADDON_MEASUREMENTS


def _tag_origin(measurements: list, origin: str) -> list:
    """Stamp each plugin with the set it was registered in.

    This is the only place that knows the difference — a measurement class
    itself has no idea whether it was shipped with the app or plugged in —
    and the documentation page groups its sidebar on the answer.
    """
    for measurement in measurements:
        measurement.origin = origin
    return measurements


ALL_MEASUREMENTS = [
    *_tag_origin(OFFICIAL_MEASUREMENTS, "official"),
    *_tag_origin(ADDON_MEASUREMENTS, "addon"),
]
