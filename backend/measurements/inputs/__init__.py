"""
inputs — one module per distinct piece of fetched data that measurements
need, each exposing a single getter function.

Measurements never call services.market_data directly; they call these
getters instead. This is the layer that lets a measurement "fetch its own
needed inputs" using only an etf_id, with no parameters supplied by the
frontend — each getter picks its own sensible defaults (lookback period,
etc.) internally.

Adding a new input type:
  1. Create a new file here (e.g. stock_info.py)
  2. Wrap the relevant services.market_data function in a getter
  3. Import it from whichever measurement(s) need it
"""
