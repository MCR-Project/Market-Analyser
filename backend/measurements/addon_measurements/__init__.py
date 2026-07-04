"""
addon_measurements — custom/experimental measurement plugins, kept
separate from the official set in official_measurement/.

Adding an addon measurement:
  1. Create a new file here (e.g. volatility.py)
  2. Subclass MeasurementBase, fill in metadata + implement
     fetch_inputs/compute/render_cell (see official_measurement/ for examples)
  3. Import it and add the instance to ADDON_MEASUREMENTS below

measurements/__init__.py combines this list with official_measurement's
to build the full ALL_MEASUREMENTS the registry serves.
"""

ADDON_MEASUREMENTS = []
