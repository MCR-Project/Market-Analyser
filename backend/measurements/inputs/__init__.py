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
defaults it applies, how to sample its real value for one ETF, and (issue
#115) a `cost` characteristic - how this getter's own read scales with
holding count ("per_request", "per_holding" or "pairwise"), whether it
reads a bounded price window at all ("windowed"), and whether it can ever
need a live upstream call or is answered from Supabase alone with no live
fallback ("network": "live" | "db"). The registry below collects both so
a measurement's documentation page can explain not just which inputs it
uses and what they quietly assume, but - via measurements/cost.py, which
reads this same `cost` field - how expensive using them actually is.

Adding a new input type:
  1. Create a new file here (e.g. stock_info.py)
  2. Wrap the relevant services.market_data function in a getter
  3. Declare an INPUT_SPEC next to it - including its own `cost`
     characteristic, honestly stated rather than copied from a neighbour -
     and register it below
  4. Import the getter from whichever measurement(s) need it, and name it
     in their `uses_inputs`
"""

from measurements.inputs import (
    correlation_matrix,
    dividend_events,
    etf_info,
    fund_index,
    holdings,
    price_frame,
    stock_info,
)

# name → INPUT_SPEC. The keys are what a measurement's `uses_inputs`
# names; a name with no entry here is a bug, and the test suite fails on
# it rather than leaving a documentation page quietly missing a section.
INPUT_REGISTRY = {
    "holdings": holdings.INPUT_SPEC,
    "etf_info": etf_info.INPUT_SPEC,
    "correlation_matrix": correlation_matrix.INPUT_SPEC,
    "price_frame": price_frame.INPUT_SPEC,
    "stock_info": stock_info.INPUT_SPEC,
    "dividend_events": dividend_events.INPUT_SPEC,
    "fund_index": fund_index.INPUT_SPEC,
}
