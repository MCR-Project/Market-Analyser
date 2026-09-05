"""
inputs — one module per distinct piece of fetched data that measurements
need, each exposing a single getter function.

Measurements never call services.market_data directly; they call these
getters instead. This is the layer that lets a measurement "fetch its own
needed inputs" using only an etf_id, with no parameters supplied by the
frontend — each getter picks its own sensible defaults (lookback period,
etc.) internally.

Because those defaults are invisible everywhere else — nothing in the UI
says a correlation is a year of daily returns — each module also declares
an INPUT_SPEC describing itself: a one-line description, the internal
defaults it applies, and how to sample its real value for one ETF. The
registry below collects them so a measurement's documentation page can
explain not just which inputs it uses, but what those inputs quietly
assume.

Adding a new input type:
  1. Create a new file here (e.g. stock_info.py)
  2. Wrap the relevant services.market_data function in a getter
  3. Declare an INPUT_SPEC next to it and register it below
  4. Import the getter from whichever measurement(s) need it, and name it
     in their `uses_inputs`
"""

from measurements.inputs import correlation_matrix, etf_info, holdings

# name → INPUT_SPEC. The keys are what a measurement's `uses_inputs`
# names; a name with no entry here is a bug, and the test suite fails on
# it rather than leaving a documentation page quietly missing a section.
INPUT_REGISTRY = {
    "holdings": holdings.INPUT_SPEC,
    "etf_info": etf_info.INPUT_SPEC,
    "correlation_matrix": correlation_matrix.INPUT_SPEC,
}
