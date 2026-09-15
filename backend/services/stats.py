"""
Return and risk arithmetic - the pure arithmetic layer shared by the
portfolio simulator (services/portfolio.py) and every metric that will
need the same arithmetic applied to a single holding rather than to a
whole portfolio (issue #98).

No I/O of any kind. Every function here takes a plain series - a list of
values and, wherever time matters, a list of ISO-8601 dates the same
length - and returns a number, a small dict, or `None` when the series
cannot support the question being asked of it. This module imports
nothing from `services.market_data`, `services.supabase_client` or
`yfinance`, and never will: that is what lets `measurements/*` call it
directly, the way `backend/CLAUDE.md`'s layering table forbids it from
reaching into `services.market_data` for anything else.

Conventions, stated once here and referenced rather than restated at
every call site that depends on them:

  - **Returns are simple, not logarithmic**, taken between consecutive
    rows of whatever calendar the caller passes in.

  - **A year is 365.25 days.** CAGR - and anything else in this module or
    built on top of it that compounds over calendar time - uses this one
    constant, so that a window answered in daily rows and the same window
    answered in coarser buckets agree about how long a year is.

  - **Volatility, and anything built from the same scaled returns
    (downside deviation, beta, idiosyncratic volatility), annualises to
    252 trading days**, with each return first divided by the square root
    of the trading time its own gap covers. `trading_days` is where that
    scaling lives: consecutive daily rows are always one trading day
    apart - a weekend between them is not three days of risk - and a
    coarser gap is converted in proportion. This is not a refinement: a
    real 2019-2026 basket reported 54% volatility annualised as though
    every gap were a trading day, against a true 35% once each gap was
    scaled by the trading time it actually covers (see `volatility`'s own
    docstring for the full account).

  - **A coarse row is a bucket, not a day.** `prices` tiers history by age
    (issue #10): under a year old, daily; one to five years, weekly;
    older, monthly (see scripts/fetch_daily.py's `_resample`). A bucket's
    `date` is its anchor, not the day it was struck, so a return spanning
    a bucket boundary already covers the bucket's full width by
    construction - nothing here needs to know which tier a date came
    from, only how many calendar days separate it from the row before it.
    `granularity_of` names the coarsest gap a computation actually saw
    ('D' / 'W' / 'M', the same letters a `prices` row's own granularity
    uses), so a caller can label a result computed partly or wholly from
    bucketed history rather than presenting every figure as though it
    came from daily closes. This is the one place that policy is stated;
    nothing downstream should restate it.

  - **A figure a series cannot support is `None`, never zero.** Too few
    rows, no elapsed time, or nothing to divide by all report `None`
    rather than a number that would be read as a real, if unremarkable,
    measurement - a two-row series has a return but no volatility, and 0%
    would claim it was riskless instead of simply short.
"""

import math

import pandas as pd

# Annualisation constants - the single source every consumer of this
# module (services/portfolio.py's CAGR and IRR, and every function below)
# must share, or "a year" stops meaning the same thing in two different
# numbers.
TRADING_DAYS_PER_YEAR = 252
DAYS_PER_YEAR = 365.25

# Percentages (and ratios reported alongside them, like beta) are rounded
# here, once, to more precision than any of them will ever be displayed
# at - so a caller can round again for display without having rounded
# twice.
PERCENT_DP = 4


# ── Trading time and granularity ──────────────────────────────────────────────

def trading_days(gap_days: int) -> float:
    """How much trading time one gap between rows covers.

    Consecutive rows of the daily tier are one trading day apart whether
    or not a weekend sits between them - Friday to Monday is one day of
    market, not three. A coarser bucket is converted in proportion: a
    weekly row spans about 4.8 trading days, a monthly one about 21.
    """
    if gap_days <= 4:
        return 1.0
    return gap_days * TRADING_DAYS_PER_YEAR / DAYS_PER_YEAR


def granularity_of(dates: list[str]) -> str:
    """The coarsest gap between consecutive rows, named the way a
    `prices` row's own bucket is: 'D' daily, 'W' weekly, 'M' monthly.

    This module never receives that label directly - it takes dates and
    values, not a `prices` row - so it infers the same distinction from
    the gaps themselves, using the same thresholds `trading_days` treats
    as "still a single trading day" versus "a bucket wider than one". A
    window spanning tiers (issue #10) reports its coarsest stretch,
    because that is the part that limits what any figure computed across
    the whole of it can actually resolve - a volatility computed partly
    from monthly buckets is no finer than its monthly rows, however many
    daily ones sit beside them.

    A series with fewer than two rows has no gap to measure and reports
    'D': there is nothing coarse about a single point.
    """
    if len(dates) < 2:
        return "D"
    parsed = [pd.Timestamp(d) for d in dates]
    worst = max((parsed[i] - parsed[i - 1]).days for i in range(1, len(parsed)))
    if worst <= 4:
        return "D"
    if worst <= 10:
        return "W"
    return "M"


def _returns_with_gaps(values: list[float], dates: list[str]) -> list[tuple[float, float]]:
    """(raw return, trading days covered) for each consecutive pair, the
    shared walk every single-series function below takes. A row preceded
    by a non-positive value contributes nothing - there is no return to
    divide into it."""
    parsed = [pd.Timestamp(d) for d in dates]
    out = []
    for i in range(1, len(values)):
        if values[i - 1] <= 0:
            continue
        gap = trading_days((parsed[i] - parsed[i - 1]).days)
        out.append((values[i] / values[i - 1] - 1, gap))
    return out


def period_returns(values: list[float], dates: list[str]) -> list[float]:
    """Simple, unscaled returns between consecutive rows - the raw series
    a caller wants for its own sake (a chart, or a capture ratio that
    compares like return to like return over an identical stretch) rather
    than the annualisation-ready one `scaled_returns` produces. A row
    preceded by a non-positive value contributes no return."""
    return [r for r, _ in _returns_with_gaps(values, dates)]


def scaled_returns(values: list[float], dates: list[str]) -> list[float]:
    """Simple returns between consecutive rows, each divided by the square
    root of the trading time its own gap covers - the shared building
    block behind every statistic in this module that annualises a
    dispersion (volatility, downside deviation, beta, idiosyncratic
    volatility). Putting a weekly bucket's return and a daily row's return
    into the same units before either is compared or annualised is what
    keeps a window spanning storage tiers from reading a week's movement
    as a day's."""
    return [r / math.sqrt(gap) for r, gap in _returns_with_gaps(values, dates)]


def _paired_returns(
    a_values: list[float], b_values: list[float], dates: list[str], *, scaled: bool
) -> list[tuple[float, float]]:
    """Two series' returns over the same gaps, paired index for index -
    the shared alignment step behind beta, R-squared, idiosyncratic
    volatility and the capture ratios, all of which need a return of `a`
    and a return of `b` computed over the identical stretch, not just the
    identical count of them. A gap where either side's previous value was
    non-positive is dropped from both, so a real return on one side is
    never paired with nothing on the other.
    """
    parsed = [pd.Timestamp(d) for d in dates]
    pairs = []
    for i in range(1, len(a_values)):
        if a_values[i - 1] <= 0 or b_values[i - 1] <= 0:
            continue
        ra = a_values[i] / a_values[i - 1] - 1
        rb = b_values[i] / b_values[i - 1] - 1
        if scaled:
            divisor = math.sqrt(trading_days((parsed[i] - parsed[i - 1]).days))
            ra, rb = ra / divisor, rb / divisor
        pairs.append((ra, rb))
    return pairs


# ── Single-series statistics ──────────────────────────────────────────────────

def volatility(values: list[float], dates: list[str]) -> dict:
    """Annualised standard deviation of the series' returns, as a
    percentage.

    Each return is first divided by the square root of the trading time
    it covers, which puts a weekly bucket's return and a daily row's
    return into the same units before either is annualised by the usual
    252. For a window answered entirely from the daily tier this is
    exactly the textbook "standard deviation of daily returns, times root
    252"; the scaling only starts to matter when the underlying rows are
    coarser (issue #10).

    That is not a refinement. A real 2019-2026 basket comes back as 198
    daily gaps, 207 weekly ones and 27 monthly: annualising every one of
    them by 252 reads a week's movement as a day's and reported 54%
    volatility where the same basket's true daily history gives 35% and
    its weekly 31%. Picking one factor for the whole window instead only
    moves which half of it is wrong. Scaling each return by its own gap is
    what makes the number mean one thing across a window spanning tiers.

    `{"value": None, ...}` rather than 0 when there are fewer than two
    scaled returns: a single return has no dispersion to measure, and
    reporting 0 would claim a series held for two days was riskless.
    """
    scaled = scaled_returns(values, dates)
    granularity = granularity_of(dates)
    if len(scaled) < 2:
        return {"value": None, "granularity": granularity}
    mean = sum(scaled) / len(scaled)
    variance = sum((r - mean) ** 2 for r in scaled) / (len(scaled) - 1)
    value = round(math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100, PERCENT_DP)
    return {"value": value, "granularity": granularity}


def downside_deviation(values: list[float], dates: list[str], target: float = 0.0) -> dict:
    """Annualised standard deviation of only the shortfall below `target`
    (a per-period rate; 0 by default), computed the same way `volatility`
    is - each return scaled by the trading time its own gap covers before
    being annualised - so the two are directly comparable and a
    downside-only figure does not conflate a coarse bucket's return with a
    daily one either.

    A return at or above `target` contributes zero rather than being
    dropped from the sample, matching the standard Sortino-ratio
    denominator: the deviation is measured over every period, not only
    the losing ones, or a series with one large loss among many flat days
    would report the same downside risk as one with frequent, similarly
    sized ones.

    `{"value": None, ...}` with fewer than two scaled returns, for the
    same reason `volatility` is.
    """
    scaled = scaled_returns(values, dates)
    granularity = granularity_of(dates)
    if len(scaled) < 2:
        return {"value": None, "granularity": granularity}
    shortfalls = [min(r - target, 0.0) ** 2 for r in scaled]
    value = round(
        math.sqrt(sum(shortfalls) / len(shortfalls)) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100,
        PERCENT_DP,
    )
    return {"value": value, "granularity": granularity}


def cagr(values: list[float], dates: list[str]) -> float | None:
    """Compound annual growth rate, as a percentage, over the calendar
    time the series actually covers.

    Elapsed calendar days rather than a row count, so a window answered in
    twelve monthly buckets and one answered in 250 daily rows over the
    same year annualise to the same rate - which is also why, unlike
    `volatility`, this never carries a `granularity`: the whole point of
    counting days instead of rows is that the answer does not depend on
    how finely the window happened to be sampled.

    None when there is no elapsed time to compound over - a single row,
    or every row on one date.
    """
    if len(values) < 2 or values[0] <= 0:
        return None
    days = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days
    if days <= 0:
        return None
    growth = values[-1] / values[0]
    return round((growth ** (DAYS_PER_YEAR / days) - 1) * 100, PERCENT_DP)


def total_return(values: list[float]) -> float | None:
    """Total return over the series, first row to last, as a percentage -
    `last / first - 1`, on whatever values are passed in (issue #108
    expects already-adjusted closes, so income is already inside it, the
    same rule every other price-derived figure in this app follows).

    No `dates` argument and no `granularity`, unlike most of this module:
    a return between two endpoints is exactly that ratio regardless of how
    many rows sit between them or how coarsely they are bucketed - nothing
    about the path between first and last changes the answer, the same
    reasoning `cagr` above states for why it carries no granularity either.

    `None` when there are fewer than two rows, or the series opens at or
    below zero - a return needs a real opening value to be a fraction of.
    """
    if len(values) < 2 or values[0] <= 0:
        return None
    return round((values[-1] / values[0] - 1) * 100, PERCENT_DP)


def momentum(values: list[float], dates: list[str]) -> dict:
    """The window's own return with the most recent month skipped - from
    the window's first row to whichever row falls one calendar month
    before its last (issue #108). For the default 1-year window this is
    the standard "12-minus-1-month" momentum factor; skipping the most
    recent month is the point, not an oversight - it is what keeps this
    column from simply restating `total_return`, since the most recent
    month is the one most prone to reversing itself.

    Unlike `total_return`, this carries a `granularity`: which row counts
    as "one month before the end" depends on how coarsely the window is
    bucketed (issue #10) - a monthly-bucketed tail can only place that cut
    to the nearest whole bucket, not the nearest day, so the answer's own
    precision is a property of the window's granularity the way
    `volatility`'s or `max_drawdown`'s already are.

    `None` when there are fewer than two rows, the series opens at or
    below zero, or the window itself spans less than a month - a holding
    priced for only a few weeks has no "one month before the end" row to
    measure to.
    """
    granularity = granularity_of(dates)
    if len(values) < 2 or values[0] <= 0:
        return {"value": None, "granularity": granularity}
    parsed = [pd.Timestamp(d) for d in dates]
    cutoff = parsed[-1] - pd.DateOffset(months=1)
    idx = next((i for i in range(len(parsed) - 1, -1, -1) if parsed[i] <= cutoff), None)
    if idx is None:
        return {"value": None, "granularity": granularity}
    value = round((values[idx] / values[0] - 1) * 100, PERCENT_DP)
    return {"value": value, "granularity": granularity}


def max_drawdown(values: list[float], dates: list[str]) -> dict:
    """The deepest peak-to-trough fall in the series, as a negative
    percentage, with the dates of both ends.

    A series that never falls reports 0 and no dates: there is no peak
    and no trough to point at, and naming the first date would invent a
    drawdown that did not happen.
    """
    worst, peak_at, trough_at = 0.0, None, None
    peak, peak_date = values[0], dates[0]
    for date_str, value in zip(dates, values):
        if value > peak:
            peak, peak_date = value, date_str
        if peak > 0:
            drawdown = value / peak - 1
            if drawdown < worst:
                worst, peak_at, trough_at = drawdown, peak_date, date_str
    return {
        "value": round(worst * 100, PERCENT_DP),
        "peakDate": peak_at,
        "troughDate": trough_at,
        "granularity": granularity_of(dates),
    }


def underwater_stretches(values: list[float], dates: list[str]) -> dict:
    """Every distinct stretch during which the series sat below its
    running peak, deepest point first out of no particular ordering
    (insertion order - the caller sorts if it wants a ranking).

    Each stretch is `{"start", "trough", "end", "depth"}`: `start` is the
    first row below the peak, `trough` is the row that fell furthest,
    `end` is the first row that recovers back to (or past) the peak it
    fell from, and `depth` is that trough's fall as a negative percentage.
    A stretch still open at the series' last row - it has not, as of the
    last thing observed, made the peak back - reports `end: None` rather
    than inventing a recovery that has not happened.

    This is `max_drawdown`'s single worst episode generalised to every
    episode, which is what a pain index or an "average time to recover"
    figure is built from.
    """
    stretches: list[dict] = []
    current: dict | None = None
    peak = values[0]
    for date_str, value in zip(dates, values):
        if value >= peak:
            if current is not None:
                current["end"] = date_str
                stretches.append(current)
                current = None
            peak = value
            continue
        if current is None:
            current = {
                "start": date_str,
                "trough": date_str,
                "trough_value": value,
                "peak": peak,
            }
        elif value < current["trough_value"]:
            current["trough"], current["trough_value"] = date_str, value
    if current is not None:
        current["end"] = None
        stretches.append(current)

    return {
        "stretches": [
            {
                "start": s["start"],
                "trough": s["trough"],
                "end": s["end"],
                "depth": round((s["trough_value"] / s["peak"] - 1) * 100, PERCENT_DP)
                if s["peak"] > 0
                else None,
            }
            for s in stretches
        ],
        "granularity": granularity_of(dates),
    }


def pain_index(values: list[float], dates: list[str]) -> dict:
    """Time-weighted average drawdown depth over the whole series, as a
    positive percentage - the "how much, and for how long" companion to
    `max_drawdown`'s "how much, once".

    Each row's drawdown from the running peak is weighted by how many
    calendar days it persisted before the next observation, rather than
    averaged one-row-one-vote: a window spanning storage tiers (issue #10)
    has far fewer rows in its oldest, coarsest stretch, however long that
    stretch actually lasted, and an unweighted average of drawdown-per-row
    would under-count exactly the years that answer in monthly buckets.

    `{"value": None, ...}` for a series too short to have an elapsed day
    between any two rows.
    """
    granularity = granularity_of(dates)
    if len(values) < 2:
        return {"value": None, "granularity": granularity}
    parsed = [pd.Timestamp(d) for d in dates]
    peak = values[0]
    weighted = 0.0
    total_days = 0
    for i in range(len(values) - 1):
        if values[i] > peak:
            peak = values[i]
        drawdown = abs(values[i] / peak - 1) if peak > 0 else 0.0
        gap = (parsed[i + 1] - parsed[i]).days
        weighted += drawdown * gap
        total_days += gap
    if total_days == 0:
        return {"value": None, "granularity": granularity}
    return {"value": round(weighted / total_days * 100, PERCENT_DP), "granularity": granularity}


def unit_values(values: list[float], inflows: list[float]) -> list[float]:
    """The total with the deposits taken back out of it.

    A contribution is not a gain. Paying $100 into a $1,000 portfolio
    takes the total to $1,100 on a day the market did nothing, and any
    metric read straight off the total records that as a 10% day - which
    then lands in the volatility, in the drawdown, and in the return.

    So each step is measured against the money that was actually working
    before it: the row's total less whatever arrived that day, over the
    previous row's total. Chaining those steps gives a series that starts
    where the series started and only ever moves because prices did - the
    standard time-weighted construction, in the one place every return
    and risk figure in this module should be read from when its caller
    has any inflows to account for.

    Returned as `values` itself when nothing was ever paid in, so a run
    without contributions is not merely close to the old result but the
    same object.
    """
    if not any(inflows):
        return values

    units = [values[0]]
    for i in range(1, len(values)):
        previous = values[i - 1]
        # A series worth nothing has no proportion left to grow by, and
        # dividing by it would invent one. It stays where it is.
        if previous <= 0:
            units.append(units[-1])
            continue
        units.append(units[-1] * (values[i] - inflows[i]) / previous)
    return units


# ── Two-series statistics (a holding or a portfolio, against a benchmark) ─────

def beta(asset_values: list[float], benchmark_values: list[float], dates: list[str]) -> dict:
    """How much the asset moved for each unit the benchmark moved:
    Cov(asset, benchmark) / Var(benchmark), the standard single-factor
    slope.

    Both series' returns are scaled by the trading time their shared gap
    covers before the covariance and variance are taken, the same way
    `volatility`'s are - without it, a handful of monthly-sized returns in
    a window spanning tiers would dominate the covariance the way raw
    returns always let the coarsest, largest-magnitude observations do.

    `{"value": None, ...}` with fewer than two paired returns, or when the
    benchmark had no variance at all to be sensitive to (a flat benchmark
    over the window - any beta would be dividing by zero).
    """
    pairs = _paired_returns(asset_values, benchmark_values, dates, scaled=True)
    granularity = granularity_of(dates)
    if len(pairs) < 2:
        return {"value": None, "granularity": granularity}
    asset_r = [a for a, _ in pairs]
    bench_r = [b for _, b in pairs]
    mean_a = sum(asset_r) / len(pairs)
    mean_b = sum(bench_r) / len(pairs)
    covariance = sum((a - mean_a) * (b - mean_b) for a, b in pairs) / (len(pairs) - 1)
    variance_b = sum((b - mean_b) ** 2 for b in bench_r) / (len(pairs) - 1)
    if variance_b == 0:
        return {"value": None, "granularity": granularity}
    return {"value": round(covariance / variance_b, PERCENT_DP), "granularity": granularity}


def r_squared(asset_values: list[float], benchmark_values: list[float], dates: list[str]) -> dict:
    """The fraction of the asset's variance that moves together with the
    benchmark's - the squared Pearson correlation of their (scaled)
    returns, from 0 (no linear relationship) to 1 (moves in lockstep, up
    to a scale factor).

    `{"value": None, ...}` with fewer than two paired returns, or when
    either series had no variance at all over the window to correlate.
    """
    pairs = _paired_returns(asset_values, benchmark_values, dates, scaled=True)
    granularity = granularity_of(dates)
    if len(pairs) < 2:
        return {"value": None, "granularity": granularity}
    asset_r = [a for a, _ in pairs]
    bench_r = [b for _, b in pairs]
    mean_a = sum(asset_r) / len(pairs)
    mean_b = sum(bench_r) / len(pairs)
    covariance = sum((a - mean_a) * (b - mean_b) for a, b in pairs) / (len(pairs) - 1)
    variance_a = sum((a - mean_a) ** 2 for a in asset_r) / (len(pairs) - 1)
    variance_b = sum((b - mean_b) ** 2 for b in bench_r) / (len(pairs) - 1)
    if variance_a == 0 or variance_b == 0:
        return {"value": None, "granularity": granularity}
    correlation = covariance / math.sqrt(variance_a * variance_b)
    return {"value": round(correlation ** 2, PERCENT_DP), "granularity": granularity}


def idiosyncratic_volatility(
    asset_values: list[float],
    benchmark_values: list[float],
    dates: list[str],
    r_squared_result: dict | None = None,
) -> dict:
    """The asset's own annualised volatility with the part explained by
    its relationship to the benchmark removed: total volatility scaled by
    the square root of one minus R-squared, in the standard single-factor
    decomposition of variance into a market component and a residual one.

    `r_squared_result` lets a caller that already computed this asset's
    own R² against the same benchmark (issue #107's fund-relation column,
    which reports both R² and idiosyncratic volatility from one pass) pass
    that result straight through instead of this function silently paying
    for the same Pearson correlation a second time - the two are meant to
    "reuse the same ρ rather than recompute it" rather than each measuring
    it independently. Left as `None` (the default), this computes it
    itself, exactly as before - no existing caller passes it.

    `{"value": None, ...}` wherever `volatility` or R² itself is None -
    there is nothing to remove a fraction from.
    """
    total = volatility(asset_values, dates)
    explained = (
        r_squared_result if r_squared_result is not None
        else r_squared(asset_values, benchmark_values, dates)
    )
    if total["value"] is None or explained["value"] is None:
        return {"value": None, "granularity": total["granularity"]}
    residual = max(0.0, 1 - explained["value"])
    value = round(total["value"] * math.sqrt(residual), PERCENT_DP)
    return {"value": value, "granularity": total["granularity"]}


def _capture(
    asset_values: list[float],
    benchmark_values: list[float],
    dates: list[str],
    *,
    up: bool,
) -> dict:
    pairs = _paired_returns(asset_values, benchmark_values, dates, scaled=False)
    granularity = granularity_of(dates)
    selected = [(a, b) for a, b in pairs if (b > 0 if up else b < 0)]
    if not selected:
        return {"value": None, "granularity": granularity}
    asset_growth = math.prod(1 + a for a, _ in selected)
    bench_growth = math.prod(1 + b for _, b in selected)
    if bench_growth == 1:
        return {"value": None, "granularity": granularity}
    value = round((asset_growth - 1) / (bench_growth - 1) * 100, PERCENT_DP)
    return {"value": value, "granularity": granularity}


def up_capture(asset_values: list[float], benchmark_values: list[float], dates: list[str]) -> dict:
    """The asset's compounded return over exactly the periods the
    benchmark rose, as a percentage of the benchmark's own compounded
    return over those same periods - 120% means the asset captured 20%
    more of the benchmark's rallies than the benchmark itself did.

    Built from raw, unscaled paired returns rather than the annualisation-
    ready ones `beta`/`r_squared` use: a capture ratio compares like
    return to like return over one identical stretch, not a dispersion
    figure that needs putting on a common time footing first.

    `{"value": None, ...}` when the benchmark never had an up period in
    the window to measure against.
    """
    return _capture(asset_values, benchmark_values, dates, up=True)


def down_capture(asset_values: list[float], benchmark_values: list[float], dates: list[str]) -> dict:
    """`up_capture`'s counterpart, over the periods the benchmark fell.
    Below 100% is the usual hope: the asset gave back less than the
    benchmark did on its way down.

    `{"value": None, ...}` when the benchmark never had a down period in
    the window to measure against.
    """
    return _capture(asset_values, benchmark_values, dates, up=False)


def tail_correlation(
    asset_values: list[float], benchmark_values: list[float], dates: list[str], quantile: float = 0.1
) -> dict:
    """Pearson correlation of the asset's returns with the benchmark's,
    restricted to the benchmark's own worst `quantile` of periods by
    return (issue #107) - does this holding still move with the fund on
    the days that hurt, or only on an average one. An ordinary, full-
    window correlation can hide a relationship that quietly comes apart
    exactly when it would matter most.

    Built from the same raw, unscaled paired returns `up_capture`/
    `down_capture` use, not the trading-time-scaled ones `volatility`/
    `beta` use - a tail is about which periods were the worst by how much
    they actually moved, not about comparing dispersion across gaps of
    different lengths.

    The "worst decile" is a decile **of periods actually observed**, not
    of calendar time: for a window answered in weekly buckets (issue #10
    - a 1-5 year window, most of the time), this is the worst weeks, not
    the worst days, and a null-rule reader should say so rather than let
    "tail" quietly imply daily granularity it doesn't have.
    `granularity_of` still names it, same as every other function here.

    `{"value": None, ...}` when there are fewer than two periods in the
    tail after the cutoff (a single point has no correlation to report),
    or when either series has no variance within just that tail.
    """
    pairs = _paired_returns(asset_values, benchmark_values, dates, scaled=False)
    granularity = granularity_of(dates)
    if len(pairs) < 2:
        return {"value": None, "granularity": granularity}

    n_tail = max(1, round(len(pairs) * quantile))
    tail = sorted(pairs, key=lambda p: p[1])[:n_tail]
    if len(tail) < 2:
        return {"value": None, "granularity": granularity}

    asset_r = [a for a, _ in tail]
    bench_r = [b for _, b in tail]
    mean_a = sum(asset_r) / len(tail)
    mean_b = sum(bench_r) / len(tail)
    covariance = sum((a - mean_a) * (b - mean_b) for a, b in tail) / (len(tail) - 1)
    variance_a = sum((a - mean_a) ** 2 for a in asset_r) / (len(tail) - 1)
    variance_b = sum((b - mean_b) ** 2 for b in bench_r) / (len(tail) - 1)
    if variance_a == 0 or variance_b == 0:
        return {"value": None, "granularity": granularity}
    correlation = covariance / math.sqrt(variance_a * variance_b)
    return {"value": round(correlation, PERCENT_DP), "granularity": granularity}


# ── Basket statistics (weights, and the risk they carry) ──────────────────────

def herfindahl(weights: list[float]) -> float | None:
    """Herfindahl-Hirschman concentration index of a set of portfolio
    weights (each a fraction of the whole; they need not already sum to 1
    - a caller with raw dollar values can pass those directly and the
    index still reads correctly, since it is scale-invariant only in the
    sense that it is computed on whatever fractions are given): the sum of
    each weight squared.

    Not a time series and not scaled by anything in this module - equal
    weights of 1/n each give 1/n; a portfolio entirely in one holding
    gives 1. A pure measure of concentration, independent of which
    holdings they are or how they have moved.

    None for an empty portfolio: there is nothing to be concentrated in.
    """
    if not weights:
        return None
    total = sum(weights)
    if total <= 0:
        return None
    shares = [w / total for w in weights]
    return round(sum(w ** 2 for w in shares), PERCENT_DP)


def effective_n(weights: list[float]) -> float | None:
    """The number of *equally weighted* holdings that would produce the
    same concentration as the actual weights: 1 / Herfindahl. A
    ten-holding portfolio with one 90% position has an effective N near 1,
    not 10 - it behaves like a single-stock position with nine
    afterthoughts.

    None wherever `herfindahl` itself is None.
    """
    hhi = herfindahl(weights)
    if not hhi:
        return None
    return round(1 / hhi, PERCENT_DP)


def _aligned_covariance(values_by_ticker: dict[str, list[float]], dates: list[str]):
    """Trimmed, aligned scaled-return covariance for a set of tickers -
    the shared alignment step behind every basket statistic that needs
    one joint covariance matrix over the same window: `risk_contribution`
    and `diversification_ratio` (issue #105). Splitting this out is what
    keeps the two reading the exact same matrix rather than each aligning
    the basket its own way and happening to agree.

    Alignment is the caller's job, same as `risk_contribution` always
    documented: `values_by_ticker[t]` and `dates` must already be the
    same length and on the same calendar for every ticker (services/
    portfolio.py has every holding's value on one calendar already;
    services/fund_metrics.py restricts itself to holdings with no gap in
    the window for the same reason - see that module's own docstring for
    why it does not lean on pandas' pairwise-complete-observations trick
    the correlation matrix uses instead).

    Returns `(tickers, n, covariance)`, where `covariance(a, b)` is the
    sample covariance of `a` and `b`'s own trimmed scaled returns, or
    `(tickers, 0, None)` when there are fewer than two aligned returns to
    build one from - trimmed to the same length **from the end**, so a
    ragged alignment (a holding whose first row produced no return
    because it started at or below zero) still lines up pointwise with
    the others.
    """
    tickers = list(values_by_ticker)
    returns = {t: scaled_returns(values_by_ticker[t], dates) for t in tickers}
    n = min((len(r) for r in returns.values()), default=0)
    if n < 2:
        return tickers, 0, None

    trimmed = {t: r[-n:] for t, r in returns.items()}
    means = {t: sum(r) / n for t, r in trimmed.items()}

    def covariance(a: str, b: str) -> float:
        return sum(
            (trimmed[a][i] - means[a]) * (trimmed[b][i] - means[b]) for i in range(n)
        ) / (n - 1)

    return tickers, n, covariance


def risk_contribution(
    values_by_ticker: dict[str, list[float]], dates: list[str], weights: dict[str, float]
) -> dict[str, float | None]:
    """Each holding's share of the portfolio's total variance, as a
    percentage that sums to 100 across the basket (the Euler
    decomposition of variance: `weight x marginal contribution to
    variance, over total variance`).

    Not the same thing as a holding's share of value - a small, volatile,
    uncorrelated holding can contribute far more risk than its dollar
    weight suggests, and a large one that moves opposite the rest of the
    basket can contribute less than zero.

    Built from the same scaled returns every other dispersion figure in
    this module is, aligned across holdings on the shared `dates` via
    `_aligned_covariance` - the same covariance matrix
    `diversification_ratio` below reads, so a fund's risk shares and its
    diversification ratio always describe the same window rather than two
    that happen to look similar.

    Every holding reports `None` when the portfolio has no variance to
    apportion at all - every holding flat, or fewer than two usable
    returns once alignment is accounted for.
    """
    tickers, n, covariance = _aligned_covariance(values_by_ticker, dates)
    if covariance is None:
        return {t: None for t in tickers}

    portfolio_variance = sum(
        weights[a] * weights[b] * covariance(a, b) for a in tickers for b in tickers
    )
    if portfolio_variance <= 0:
        return {t: None for t in tickers}

    contributions = {}
    for a in tickers:
        marginal = sum(weights[b] * covariance(a, b) for b in tickers)
        contributions[a] = round(weights[a] * marginal / portfolio_variance * 100, PERCENT_DP)
    return contributions


def diversification_ratio(
    values_by_ticker: dict[str, list[float]], dates: list[str], weights: dict[str, float]
) -> float | None:
    """How many genuinely independent bets a basket's holdings behave
    like: the weighted average of each holding's own volatility, over the
    basket's actual volatility once their correlations are counted in -
    `Σ wᵢσᵢ ÷ σ_fund` (issue #105). 1.0 means the holdings move in
    lockstep and diversifying across them bought nothing; the further
    above 1 it climbs, the more the basket's own swings are smaller than
    the sum of its parts.

    Shares `_aligned_covariance` with `risk_contribution` above, so this
    is always read off the exact same matrix a fund's risk-contribution
    shares are - and every σᵢ here is `sqrt` of that same matrix's own
    diagonal (`covariance(t, t)`), not each holding's volatility computed
    over whatever window it happens to have on its own. That is what
    keeps the ratio mathematically guaranteed to be at least 1 (Cauchy-
    Schwarz) rather than occasionally dipping under it from a σᵢ measured
    over a different stretch than the covariance it is being divided
    against.

    `None` under the same two conditions `risk_contribution` itself
    reports `None` for: fewer than two aligned returns across the basket,
    or a basket with no variance at all to divide by.
    """
    tickers, n, covariance = _aligned_covariance(values_by_ticker, dates)
    if covariance is None:
        return None

    portfolio_variance = sum(
        weights[a] * weights[b] * covariance(a, b) for a in tickers for b in tickers
    )
    if portfolio_variance <= 0:
        return None

    weighted_vol = sum(weights[t] * math.sqrt(max(covariance(t, t), 0.0)) for t in tickers)
    return round(weighted_vol / math.sqrt(portfolio_variance), PERCENT_DP)


def weighted_index(
    values_by_ticker: dict[str, list[float]], weights: dict[str, float], dates: list[str]
) -> list[float] | None:
    """A synthetic fund-level price index built by compounding the
    weighted average of a basket's own simple returns (issue #107) -
    the "r_fund" every per-holding-vs-fund statistic added alongside this
    function is computed against (`beta`, `r_squared`,
    `idiosyncratic_volatility`, `up_capture`/`down_capture`,
    `tail_correlation`), materialised once as a plain value series so
    those functions need no benchmark-specific branch of their own; they
    already take one series to compare another against, and this is what
    is handed to them as it.

    Weights are renormalised to sum to 1 over exactly the tickers passed
    in, so a basket whose tracked weights sum to less than 100% (issue
    #105's own coverage gap) still produces an index representative of
    what the tracked basket actually did, rather than one silently
    dampened by the untracked share sitting out of the calculation as if
    it earned nothing.

    Starts at 100 and compounds by each date's weighted return - this
    answers "how did the tracked basket move", nothing about what any
    of it is worth, which is all every caller of this function needs: a
    `benchmark_values` argument whose own returns are the fund's.

    Alignment (every ticker's own list the same length as `dates`, on the
    same calendar) is the caller's job, the same contract
    `risk_contribution`/`diversification_ratio` above already state -
    this function does not merge, forward-fill or resample anything.

    `None` when there is nothing to build an index from: no tickers, or
    weights that sum to zero or less.
    """
    tickers = list(values_by_ticker)
    total_weight = sum(weights.get(t, 0.0) for t in tickers)
    if not tickers or total_weight <= 0:
        return None
    normalised = {t: weights.get(t, 0.0) / total_weight for t in tickers}

    index = [100.0]
    for i in range(1, len(dates)):
        step_return = sum(
            normalised[t] * (values_by_ticker[t][i] / values_by_ticker[t][i - 1] - 1)
            for t in tickers
            if values_by_ticker[t][i - 1] > 0
        )
        index.append(index[-1] * (1 + step_return))
    return index
