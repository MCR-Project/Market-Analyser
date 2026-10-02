"""
Fund-level metrics: properties of a whole basket rather than of any one
holding (issue #105) - how independently a fund's tracked holdings
actually move, how much of the fund's own variance concentrates in its
five largest risk contributors, and how much of the fund's weight those
tracked (>=1%) holdings can even speak for.

Companion to services/portfolio.py, not a fork of it: the shared
arithmetic still lives entirely in services/stats.py
(`diversification_ratio`, `risk_contribution`) - this module only
decides which series to hand it (the fund's own tracked holdings, priced
over one shared window) and assembles the result into the fund's shape,
the same job portfolio.py does for a simulated run. No I/O beyond the
reads it calls.

**Why a holding with any gap in the window is left out, rather than the
window being narrowed to what every holding shares.** The correlation
matrix (services/market_data.py's `_correlation_summary`) can lean on
pandas' own per-pair `min_periods` and let a newly listed holding keep
its own shorter history, because a pairwise correlation is computed one
pair at a time. A basket's variance decomposition cannot: `risk_
contribution`/`diversification_ratio` need one joint covariance matrix
built from every holding's returns aligned to the *same* stretch of
dates at once. Narrowing that stretch to whatever the fund's newest
holding has traded would silently shrink a year-old fund's own window to
a few weeks the moment it added one new position - so instead a holding
missing any close in the window is excluded from these two figures
entirely (it still counts toward `trackedWeightCoverage`, which does not
need a shared window at all).

Cached by `services.cache` like every other derived read in this layer,
keyed on `etf_id` and on whether the fund is deep-filled (issue #171) at
`CACHE_TTL_SECONDS` - the same tier the price series and correlation matrix
this shares its window with already use. The state is part of the key because
the two answers are different funds as far as these figures go: a fund read as
its whole basket has ~450 more holdings in its covariance matrix, and a key on
`etf_id` alone would serve the pruned answer for a deep-filled fund, or the
deep-filled one for the fund after it expires (ADR 0006). The key names the
Deep-fill's own as-of time, so a second Deep-fill of the same fund is not served
the first one's figures either.
Each of the three `computed_from="etf_id"` portfolio-metric classes
(`portfolio_metrics/official_metrics/diversification_ratio.py` and its
two siblings) calls `compute_fund_metrics` once per `value()`/`reason()`
and reads its own key back out - the fund-level counterpart to
`RunMetric` reading a key out of a `simulate_portfolio()` response - so
caching here is what keeps three metric classes reading the same fund
from repeating the same holdings/price read and covariance arithmetic
three times over.
"""

from config import CACHE_TTL_SECONDS, CORRELATION_PERIOD
from services import deep_fill_store
from services.cache import cache
from services.market_data import deep_fill_exclusions, get_closes, get_etf_holdings
from services.stats import diversification_ratio, risk_contribution

# How many of a fund's largest risk contributors sum into "the top five"
# (issue #105's own choice, matching the acceptance criteria literally).
TOP_N = 5

_INCOMPLETE_HISTORY = (
    "fewer than two of the fund's tracked holdings have a complete price "
    "history over the window"
)
_NO_VARIANCE = "no measurable variance across the fund's tracked holdings over this window"


def compute_fund_metrics(etf_id: str) -> dict:
    """The fund-level figures for one ETF: `trackedWeightCoverage`,
    `diversificationRatio`, and `top5VarianceShare`, plus a `reasons`
    entry for whichever of the latter two came back null.

    `trackedWeightCoverage` is answerable from the holdings list alone
    and is never null - a fund with no tracked holdings at all genuinely
    covers 0% of itself, which is a real answer, not a missing one. While
    the fund is deep-filled (issue #171) the list also holds its Untracked
    holdings, and the figure counts every holding the window can price: the
    ones the Deep-fill failed to fetch are not counted as covered, and are
    named, with why, under `deepFill.withoutHistory` (which is present only
    while the fund is deep-filled, with the as-of time and the Untracked
    weight beside it). The
    other two need a joint covariance across the tracked basket; where
    that cannot be built (fewer than two holdings with a complete price
    history over the window, or a basket with no measurable variance at
    all), both report null with the same reason, matching `stats.
    risk_contribution`/`diversification_ratio`'s own `None` cases exactly
    rather than inventing a third condition.
    """
    etf_id = etf_id.upper()
    deep = deep_fill_store.store.fund(etf_id)
    cache_key = f"fund_metrics:{etf_id}:{'deep-' + str(deep.as_of) if deep else 'pruned'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = _compute(etf_id)
    # `_compute` reads the fund's Deep-fill state again of its own, so a Deep-fill
    # that finished or expired between the key above and here would put figures
    # for one state under the other's key, and serve them for the whole TTL. Only
    # a result computed while the state was still the one the key names is kept.
    now = deep_fill_store.store.fund(etf_id)
    if (now.as_of if now else None) == (deep.as_of if deep else None):
        cache.set(cache_key, result, CACHE_TTL_SECONDS)
    return result


def _compute(etf_id: str) -> dict:
    holdings, _ = get_etf_holdings(etf_id)
    weights = {ticker: weight for ticker, weight in holdings}
    tickers = list(weights)

    without_history = deep_fill_exclusions(etf_id, CORRELATION_PERIOD)
    covered = sum(w for t, w in weights.items() if t not in without_history)

    result = {
        "etfId": etf_id,
        "trackedWeightCoverage": round(covered, 2),
        "diversificationRatio": None,
        "top5VarianceShare": None,
        "reasons": {},
    }
    deep = deep_fill_store.store.fund(etf_id)
    if deep is not None:
        result["deepFill"] = {
            "asOf": deep_fill_store.iso(deep.as_of),
            "untrackedWeight": round(sum(w for _, w in deep.tail), 2),
            "withoutHistory": without_history,
        }

    closes = (
        get_closes(tickers, period=CORRELATION_PERIOD, min_tickers=1, deep_fill_tail=True)
        if tickers else None
    )

    # Only a holding priced for every date in the frame can safely join a
    # joint covariance matrix - see the module docstring for why this
    # differs from the correlation matrix's own pairwise approach.
    complete = (
        [t for t in tickers if t in closes.columns and closes[t].notna().all()]
        if closes is not None
        else []
    )

    if len(complete) < 2:
        result["reasons"]["diversificationRatio"] = _INCOMPLETE_HISTORY
        result["reasons"]["top5VarianceShare"] = _INCOMPLETE_HISTORY
        return result

    frame = closes[complete]
    dates = [idx.date().isoformat() for idx in frame.index]
    values_by_ticker = {t: frame[t].tolist() for t in complete}
    used_weights = {t: weights[t] for t in complete}

    ratio = diversification_ratio(values_by_ticker, dates, used_weights)
    contributions = risk_contribution(values_by_ticker, dates, used_weights)
    ranked = sorted((v for v in contributions.values() if v is not None), reverse=True)

    if ratio is None or not ranked:
        result["reasons"]["diversificationRatio"] = _NO_VARIANCE
        result["reasons"]["top5VarianceShare"] = _NO_VARIANCE
        return result

    result["diversificationRatio"] = ratio
    result["top5VarianceShare"] = round(sum(ranked[:TOP_N]), 2)
    return result
