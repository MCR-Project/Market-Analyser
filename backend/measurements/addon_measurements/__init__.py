"""
addon_measurements — custom/experimental measurement plugins, kept
separate from the official set in official_measurement/.

Adding an addon measurement:
  1. Create a new file here (e.g. volatility.py)
  2. Subclass MeasurementBase, fill in metadata + implement
     fetch_inputs/compute/render_cell (see official_measurement/ for examples)
  3. Name the measurements/inputs/* getters it uses in `uses_inputs`
  4. Import it and add the instance to ADDON_MEASUREMENTS below
  5. Copy measurements/DOC_TEMPLATE.mdx to volatility.mdx next to it and
     fill it in

Step 5 is what makes an addon self-contained: the doc ships with the
measurement, so it appears on the /docs page under "Plugged-in
measurements" with no change to the frontend and nothing to register
centrally. See measurements/docs.py for the file format.

measurements/__init__.py combines this list with official_measurement's
to build the full ALL_MEASUREMENTS the registry serves.
"""

ADDON_MEASUREMENTS = []
