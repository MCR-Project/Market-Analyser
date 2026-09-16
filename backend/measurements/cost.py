"""
Cost rating — how expensive a measurement is to compute, derived from
what it declares rather than hand-set anywhere (issue #115).

The metrics in this app differ enormously in cost. A weight column is a
dictionary lookup over data already fetched; a correlation-derived one is
a pairwise sweep over a price frame for every holding; days to liquidate
needs volume for the whole basket. Widening the shared window multiplies
all of it, against upstream sources that are themselves rate-limited
(issue #92). Nothing on screen used to distinguish them, so enabling ten
heavy columns on a sixty-holding fund looked like the same action as
enabling one light one.

**The rating is derived, never hand-declared.** A plugin cannot mislabel
its own cost, on purpose: `rate()` below reads only two things a plugin
already has to state for other reasons - `uses_inputs` (already required
for the documentation page to say where its numbers came from, issue
#98) and each named input's own `cost` characteristic (measurements/
inputs/*.py's own INPUT_SPEC, issue #115's own addition to it). There is
no `cost_rating` attribute on `MeasurementBase` for a class to set, and
grep finding none anywhere is the acceptance criterion this module
exists to satisfy.

Three axes, each already declared per input rather than invented here:

  - **scaling** - how an input's own read grows with the fund's holding
    count. "per_request" describes the whole fund in one call regardless
    of size (holdings, etf_info); "per_holding" grows with the basket,
    whether that is one bulk query sized by however many tickers are in
    it (price_frame, fund_index) or a genuine loop of one read per ticker
    (stock_info, dividend_events) - this model does not distinguish the
    two, since "per_holding" is as fine-grained a distinction as the
    issue itself asks for; "pairwise" sweeps every ticker against every
    other (correlation_matrix), which is what makes a correlation-derived
    column rate heavier than a weight-derived one without anyone saying
    so by hand (the acceptance criterion this exists to satisfy).
  - **network** - whether the getter behind an input can ever need a live
    upstream call (services.market_data's DB-first, live-fallback
    pattern - the norm here) or is answered from Supabase alone with
    genuinely no live fallback at all (dividend_events, the one input in
    this package that can make that claim - see services/CLAUDE.md).
  - **windowed** - whether an input reads a bounded stretch of price
    history at all. Holdings, ETF info, stock info and dividend events do
    not; price_frame, fund_index and correlation_matrix do, and it is
    *how much* history - `window` for a window-aware plugin (issue #101),
    each input's own fixed default otherwise - that lets the same column
    move from Short to Long by widening the shared window control.

`rate(measurement, window=None)` sums each declared input's own
(scaling + network) weight, once each, and - if any input the plugin
uses is windowed - adds one more weight for how long a stretch of history
that window actually asks for. Summing rather than taking the worst
input alone is deliberate: a plugin touching three inputs really does
cost more than one touching a single cheap one, which is exactly the
"widening the window multiplies all of it" reasoning stated above -
taking a maximum would hide that a plugin reads three separate things.
`window=None` falls back to the plugin's own `window_default` (`None`
again for a plugin with none at all), the identical fallback rule
`MeasurementBase.run()` already applies to a missing or unrecognised
window - this module never invents a second one.

The four labels and the score each starts at are documented here, once,
rather than as folklore repeated at every call site - `backend/
measurements/CLAUDE.md` and `README.md` restate them for a reader who
does not want to open this file, but this is the source of truth either
one would need to be corrected against.
"""

from config import PERIOD_TO_DAYS
from measurements.inputs import INPUT_REGISTRY

# How much an input's own read grows with the fund's holding count -
# see the module docstring for what each tier actually means.
_SCALING_WEIGHT = {"per_request": 1, "per_holding": 3, "pairwise": 6}

# Whether an input can ever need a live upstream call. Flat, not scaled
# by anything else, because the risk this represents - joining the
# traffic issue #92 exists because of - does not depend on how large the
# read is, only on whether it can reach upstream at all.
_NETWORK_WEIGHT = {"db": 0, "live": 2}

# How much price history a windowed input's own read actually spans,
# bucketed from config.PERIOD_TO_DAYS - the same day-count vocabulary
# the shared window control already uses, not a second one invented
# here. Thresholds are inclusive upper bounds: a period whose day count
# is at or under one is scored at that tier.
_WINDOW_THRESHOLDS = [(90, 1), (182, 2), (365, 3), (1825, 5)]
# "max" has no entry in PERIOD_TO_DAYS at all (config.py's own comment:
# it means no lower bound, i.e. every row), so it is scored as this
# heaviest tier directly rather than as an unbounded day count - and any
# other value this model has never heard of degrades to the same, safer
# side rather than silently under-counting an unrecognised window.
_WINDOW_WEIGHT_UNBOUNDED = 8


def _window_weight(period: str | None) -> int:
    if not period:
        return 0
    if period == "max":
        return _WINDOW_WEIGHT_UNBOUNDED
    days = PERIOD_TO_DAYS.get(period)
    if days is None:
        return _WINDOW_WEIGHT_UNBOUNDED
    for threshold, weight in _WINDOW_THRESHOLDS:
        if days <= threshold:
            return weight
    return _WINDOW_WEIGHT_UNBOUNDED


# The four labels, and the score each begins at - the one place these
# thresholds are decided; everything else (the badge, the docs) reads
# this table rather than restating the numbers. Checked from the
# heaviest threshold down, so a score meeting several thresholds gets
# the highest one it qualifies for.
RATING_THRESHOLDS = [
    (18, "Extremely long"),
    (12, "Long"),
    (7, "Medium"),
    (0, "Short"),
]


def _label(score: int) -> str:
    for threshold, name in RATING_THRESHOLDS:
        if score >= threshold:
            return name
    return RATING_THRESHOLDS[-1][1]  # unreachable: the last threshold is 0


def rate(measurement, window: str | None = None) -> dict:
    """How expensive `measurement` is to compute, as `{"score", "rating"}`.

    `score` is the sum, not a maximum, of every input named in
    `uses_inputs`' own (scaling + network) weight, plus one further
    weight for how much history the shared window asks for if any of
    those inputs reads one at all - see the module docstring for why
    summing is the deliberate choice. `window` is the actual value this
    call is being rated for; omitted, a window-aware plugin (issue #101)
    is rated at its own `window_default` (the same value a doc page's
    worked example is always computed against - examples.py never wires
    a doc to the table's live control either).

    A plugin that is *not* window-aware at all - correlation.py, days_
    to_liquidate.py, dividend_income.py - has no `window_default` of its
    own to fall back to (`""`, base.py's class default), but a windowed
    input it uses still reads a real, bounded stretch of history: its own
    INPUT_SPEC `defaults["period"]` (correlation_matrix's and price_
    frame's own `DEFAULT_PERIOD`) is what such a plugin's `fetch_inputs`
    actually passes when it calls the getter with no `period` of its own,
    so that is what this falls back to next, rather than reading a
    windowed input no measurement ever leaves genuinely unbounded as
    though it cost nothing. The first windowed input encountered decides
    it - every windowed input in this package shares the same "1y"
    default today, so this tie-break is never actually exercised, but a
    single, stated rule beats leaving the case undefined.

    An input name `uses_inputs` lists but INPUT_REGISTRY has never heard
    of is skipped rather than raised on - the same "a doc page should
    degrade rather than 500 on a stale name" rule examples.py's own
    `_sample_inputs` already follows, since a typo there is caught by the
    test suite (issue #98), not by a request at runtime.
    """
    resolved_window = window if window is not None else (measurement.window_default or None)

    score = 0
    needs_window = False
    fallback_period = None
    for name in measurement.uses_inputs:
        spec = INPUT_REGISTRY.get(name)
        if spec is None:
            continue
        cost = spec.get("cost", {})
        score += _SCALING_WEIGHT.get(cost.get("scaling"), 0)
        score += _NETWORK_WEIGHT.get(cost.get("network"), 0)
        if cost.get("windowed"):
            needs_window = True
            if fallback_period is None:
                fallback_period = spec.get("defaults", {}).get("period")

    if needs_window:
        score += _window_weight(resolved_window or fallback_period)

    return {"score": score, "rating": _label(score)}
