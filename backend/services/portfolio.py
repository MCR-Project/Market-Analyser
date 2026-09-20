"""
Portfolio simulation — what a basket of tickers would have been worth on
every day of a window, and what each holding was worth inside it.

Portfolios are not stored here or anywhere else server-side: they live in
the browser that authored them, and arrive whole in the request. This
module is the arithmetic, and only the arithmetic.

The model, in the order the decisions were made:

  - **Weights are normalised.** The caller may send any non-negative
    numbers; what matters is their ratio. 30/30/30 and 33.33/33.33/33.33
    are the same portfolio and must simulate identically.

  - **Buy and hold by default.** The weights buy shares once, and from
    then on each holding drifts with its own price. That drift is the
    thing worth looking at: a winner visibly taking over the portfolio is
    invisible under continuous rebalancing.

  - **A rebalance restores the target weights** from the then-current
    total, on the first trading day of each new period. Not on a fixed
    calendar date - the 1st of a month is often not a trading day, and an
    old enough window has no daily rows at all (see the calendar note
    below), so "the first row of a new month" is the only definition that
    holds across the whole of history.

  - **An allocation is cash until its holding lists.** A ticker with no
    price yet cannot be bought, and pretending otherwise would either
    invent a price or silently drop the allocation. It sits in cash - idle,
    earning nothing - and buys in at the first close it has. Because the
    cash converts at exactly that price, the portfolio's total does not
    move on the day it happens.

  - **Contributions are optional, and land on the first row of a new
    period** - the same definition a rebalance uses, and for the same
    reason: the 1st of a month is often not a trading day, and an old
    enough window has no daily rows at all. A contribution is spread
    across the target weights at that row's prices, and any part of it
    belonging to a holding that has not listed waits in cash exactly as
    the opening allocation does. The window's first row is the opening
    lump sum, never a contribution, so a year of monthly contributions is
    the twelve times money arrived *after* the start.

  - **Withdrawals are the other direction, and a portfolio has one or the
    other** (issue #150, ADR 0002). A fixed amount leaves on the first row
    of each new period - the same timing rule, for the same reason - and
    comes out of every holding, and of any cash still waiting for a holding
    to list, in proportion to what each is worth at that moment. Not over
    the target weights the way a contribution is spread: under buy and hold
    the holdings have drifted, and a target weight can ask for more of a
    holding than it is now worth. Pro rata changes how much the portfolio
    holds and never what the mix is; a rebalance on the same row then
    restores the targets from what is left, so the withdrawal is taken
    first. A portfolio that cannot cover one takes what is left and pays
    nothing after that - shorting is not modelled - and every figure
    downstream reads what was actually taken, never what was scheduled.
    `depletedOn` names the row it ran out on. Both schedules at once is
    refused: the money-weighted return is only guaranteed one answer while
    the run's cash flows change sign once.

How the run is then scored, in one place because a number is only worth
as much as the convention behind it:

  - **Returns are simple, not logarithmic**, taken between consecutive
    rows of the run's own calendar.

  - **Performance is time-weighted; the account is money-weighted.** A
    deposit is not a gain, and a withdrawal is not a loss. Paying $100 into
    a $1,000 portfolio moves the total 10% on a day the market did nothing
    (and taking $100 out moves it 10% the other way), and left alone that
    flows straight into the volatility, the drawdown and the return. So every
    metric describing *the portfolio* - total return, CAGR, volatility,
    drawdown - is computed on a flow-free unit value that only moves when
    prices do, while the money-weighted return (IRR) answers the different
    question of what the money itself earned given when it arrived. With
    no contributions the unit value is the total, and the two questions
    have the same answer.

  - **The return and risk arithmetic itself - a year, a trading day, what
    a coarse row means, CAGR, volatility, max drawdown, the flow-free unit
    value - lives in `services/stats.py` (issue #98), not here.** That
    module states the conventions once (a year is 365.25 days; volatility
    annualises to 252 trading days, each return first divided by the root
    of the trading time it covers); this module only decides which series
    to hand it and how to read the result back into a portfolio's shape.
    Read its module docstring for the full account of why that scaling
    is not a refinement.

  - **Drawdown is measured on the total**, the only series a holder
    experiences. A single holding can fall much further without the
    portfolio noticing.

  - **Dividend income is reported, never added.** `prices` stores
    split- and dividend-adjusted closes (issue #13), so every return here
    is already a total return: the income is in the value, spent the
    moment it arrived on more of the same holding. Adding the cash on top
    would count it twice. It is computed from the sparse `dividends` event
    table and reported beside the run as the answer to a different
    question - how much of this came from being paid rather than from the
    price moving - and a holding whose dividends are not on record reports
    that it does not know rather than reporting nothing.

  - **A holding's contribution is its final value, plus every dollar taken
    out of it, less every dollar put into it.** Once a rebalance starts
    moving money between holdings, a final value says nothing about which
    holding earned it; the flows have to be netted out. Money a withdrawal
    took was still earned, so it is added back, and the portfolio's own
    gain is `finalValue + withdrawn - totalInvested` for the same reason.
    Contributions add up to the portfolio's gain.

The calendar every holding is aligned onto is the union of the dates the
price rows cover, not the intersection: one holding missing one day must
not delete that day for the others. A gap inside a holding's own history
is forward-filled (its last known close still describes what it is worth);
the dates before its first close are left empty, which is what makes it
cash rather than free. Note that `prices` tiers history by age (issue #10),
so a window reaching years back is a calendar of monthly buckets, not of
trading days - the simulation is only ever as fine-grained as the rows
underneath it.
"""

import math

import pandas as pd

from services.market_data import (
    DataUnavailable,
    get_closes,
    get_dividends,
    get_risk_free_rate,
    tracked_tickers,
)
from services.stats import (
    DAYS_PER_YEAR,
    PERCENT_DP,
    average_correlation,
    cagr,
    calmar_ratio,
    effective_n,
    max_drawdown,
    pain_index,
    risk_contribution,
    sharpe_ratio,
    sortino_ratio,
    time_under_water,
    unit_values,
    volatility,
)
from services.tickers import resolve_ticker

# A ceiling on basket size, so one anonymous request cannot ask for an
# unbounded price read (issue #93). Well clear of what a portfolio copied
# from a tracked ETF holds (only constituents weighing >=1% of their fund
# are tracked), and of any real portfolio anyone has actually built here.
#
# Not primarily a memory limit: measured in the prod image capped at
# 512MB (docker run --memory 512m), a window=max simulation over a
# deliberately old-inception 32-year daily history peaked at 174MB for
# 100 holdings and 149MB for 50 - a third of the cap either way, with
# room to spare. The real cost this bounds is latency and CPU for one
# HTTP request from a caller who has proven nothing about who they are:
# the same run took 3.52s at 100 holdings and 1.96s at 50.
MAX_HOLDINGS = 50

# How often the target weights are restored. "none" is buy and hold.
REBALANCE_FREQUENCIES = ("none", "monthly", "quarterly", "yearly")

# How often money is paid in, when it is. There is no "none" here: a
# contribution is absent by being absent, and an amount of zero is off.
CONTRIBUTION_FREQUENCIES = ("monthly", "quarterly", "yearly")

# How often money is taken out, when it is - the same three periods, on the
# same "first row of a new period" rule (issue #150). A separate name rather
# than a reuse of the tuple above because the two schedules are separate
# concepts that happen to agree today, and a frequency added to one should
# not silently appear on the other.
WITHDRAWAL_FREQUENCIES = ("monthly", "quarterly", "yearly")

# Money is reported to the cent. Each holding's value is rounded, and the
# total is summed from those rounded parts rather than computed alongside
# them, so a stacked chart's bands add up to exactly the total line drawn
# above them.
MONEY_DP = 2

# A balance smaller than this after a withdrawal is empty, not a sliver: half
# a cent is below what MONEY_DP rounds a value to, so it could never be seen
# on a series anyway (issue #150).
EMPTY_BELOW = 0.5 * 10 ** -MONEY_DP

# PERCENT_DP and DAYS_PER_YEAR are imported from services.stats above
# rather than redefined here - the IRR discounting below (`_npv`) has to
# agree with `stats.cagr` about how long a year is, and a second copy of
# either constant is exactly the kind of drift issue #98 moved this
# arithmetic out to prevent.


def _period_key(timestamp: pd.Timestamp, frequency: str):
    """Which period a date belongs to. A rebalance happens on the first
    row whose key differs from the previous row's."""
    if frequency == "monthly":
        return timestamp.year, timestamp.month
    if frequency == "quarterly":
        return timestamp.year, (timestamp.month - 1) // 3
    return timestamp.year


def _npv(rate: float, flows: list[tuple[pd.Timestamp, float]]) -> float:
    """Present value of `flows` at `rate`, discounting by calendar time.

    The same 365.25-day year CAGR compounds over, so the two annual rates
    are answers to different questions rather than to different calendars.
    A rate close to -100% raises the discount factor of a distant flow to
    an enormous power; that overflows to infinity rather than raising, and
    infinity is the correct end of the bracket the search below wants.
    """
    origin = flows[0][0]
    total = 0.0
    for timestamp, amount in flows:
        years = (timestamp - origin).days / DAYS_PER_YEAR
        try:
            total += amount / (1 + rate) ** years
        except OverflowError:
            return math.inf if amount > 0 else -math.inf
    return total


def _money_weighted_return(flows: list[tuple[pd.Timestamp, float]]) -> float | None:
    """The annualised rate at which the money itself grew, as a percentage.

    This is the internal rate of return: the single annual rate that makes
    every dollar paid in, discounted from the day it arrived, add up to
    what the portfolio is worth at the end. It is the number a plain total
    return cannot give once money keeps arriving - $1,000 that became
    $1,100 after a $100 deposit last week has not returned 10%.

    `flows` is signed from the holder's point of view: negative going in,
    positive coming out - each recurring withdrawal on its own date, and
    one last flow at the end for what it is all worth. A portfolio pays in
    or draws out, never both (ADR 0002), so that shape has exactly one sign
    change either way - money in and then one positive flow, or the opening
    amount and then only positive ones - so there is exactly one rate that
    solves it, and bisection finds it without needing a derivative or a
    starting guess to be lucky. That is the property the both-schedules
    refusal protects. NPV falls as the rate rises, so the bracket is
    widened upward until it does turn negative.

    None when the question does not arise - nothing was paid in, or no
    time passed. A portfolio that ended at nothing returns -100%: every
    dollar went, and no rate describes that better than all of it.
    """
    if len(flows) < 2:
        return None
    paid_in = -sum(amount for _, amount in flows if amount < 0)
    received = sum(amount for _, amount in flows if amount > 0)
    if paid_in <= 0:
        return None
    if (flows[-1][0] - flows[0][0]).days <= 0:
        return None
    if received <= 0:
        return -100.0

    low, high = -0.9999, 1.0
    # NPV decreases as the rate rises; push the ceiling up until it is
    # past the root. Ten doublings covers a 1,000x-per-year portfolio,
    # which no window of real prices reaches.
    for _ in range(40):
        if _npv(high, flows) <= 0:
            break
        high *= 2
    else:
        return None
    if _npv(low, flows) <= 0:
        # Even a near-total-loss rate cannot discount the deposits down to
        # what came back. Reporting the floor is honest; a null here would
        # hide a real and very bad answer.
        return round(low * 100, PERCENT_DP)

    for _ in range(200):
        middle = (low + high) / 2
        if _npv(middle, flows) > 0:
            low = middle
        else:
            high = middle
        if high - low < 1e-12:
            break
    return round((low + high) / 2 * 100, PERCENT_DP)


def _resolve_rate(
    rate: float | None, window_start: str, window_end: str
) -> tuple[float | None, str | None]:
    """The annual risk-free rate Sharpe/Sortino are scored against for
    this run (issue #112): `rate` itself if the caller supplied an
    override, else the tracked series' own average over *this run's own
    window* - not a single point value, since the window a rate is read
    for should be the window it is scoring.

    `(None, None)` when neither is available - `get_risk_free_rate`'s own
    "no live fallback" rule (a number that sometimes comes from a record
    and sometimes from a network call is a number nobody can reconcile)
    means a caller here must show a null with a reason rather than assume
    a rate of zero, the same as every other reader of that table does.
    """
    if rate is not None:
        return float(rate), "override"
    rows = get_risk_free_rate(start=window_start, end=window_end)
    if not rows:
        return None, None
    return sum(row["rate"] for row in rows) / len(rows), "tracked"


def _metrics(
    totals: list[float],
    dates: list[str],
    units: list[float],
    flows: list[tuple[pd.Timestamp, float]],
    contributed: float,
    withdrawn: float,
    depleted_on: str | None,
    income: dict[str, float],
    unknown: list[str],
    rate: float | None,
    rate_source: str | None,
) -> dict:
    """How the run did, as one object beside the series rather than
    interleaved into it - a summary is read whole, not walked date by
    date.

    Two families of number, and the split is the point. Total return,
    CAGR, volatility, drawdown, time under water, pain index, Calmar,
    Sharpe and Sortino (issue #112) are read off `units` - the flow-free
    unit value - and describe **the portfolio**: what a dollar left alone
    in it would have done. Contributed, invested, gain and the
    money-weighted return are read off the cash flows and describe **the
    account**: what actually went in, what came out, and the rate that
    reconciles the two given when each dollar arrived.

    With no contributions `units` is `totals` and the two families agree,
    which is why a run with contributions switched off is unchanged.

    `cagr` and `maxDrawdown` are `services.stats`'s own return shape
    (see issue #98); `volatility`'s `{"value", "granularity"}` is
    unpacked to its bare value here, because this response's `volatility`
    key has always been a plain number and changing that would be a
    change to the simulator's output, not to where its arithmetic lives.
    `timeUnderWater`/`shareUnderWater` and `sharpe`/`sortino` are each
    unpacked the same way, for the same reason.

    `reasons` (issue #99) is the same optional sidecar `per_ticker_reason`
    is for a measurement column, scoped to this dict instead of a
    per-ticker one: one entry per metric below that is null in this
    particular run, naming why, present only when at least one actually
    is - a run with a real value for every metric gets back exactly the
    response it always has.
    """
    start_value, final_value = totals[0], totals[-1]
    unit_start, unit_end = units[0], units[-1]
    total_return = (
        round((unit_end / unit_start - 1) * 100, PERCENT_DP) if unit_start > 0 else None
    )
    invested = round(start_value + contributed, MONEY_DP)
    cagr_value = cagr(units, dates)
    volatility_value = volatility(units, dates)["value"]
    max_drawdown_value = max_drawdown(units, dates)
    money_weighted = _money_weighted_return(flows)
    time_under_water_value = time_under_water(units, dates)
    pain_index_value = pain_index(units, dates)["value"]
    calmar_value = calmar_ratio(cagr_value, max_drawdown_value["value"])
    sharpe_value = sharpe_ratio(units, dates, rate)["value"] if rate is not None else None
    sortino_value = sortino_ratio(units, dates, rate)["value"] if rate is not None else None

    # `value` and `contribution.amount` are validated > 0 before a run ever
    # starts, so `totalReturn`/`dividendYield`'s own None branches (an
    # opening value of 0) are unreachable today and get no reason here -
    # inventing one for a state validation already forecloses would be
    # explaining something that cannot happen. The rest are real:
    # a single-row window leaves CAGR with no elapsed time to compound
    # over, a window under three rows leaves volatility (and, on the same
    # returns, Sharpe/Sortino's own mean) with fewer than the two returns
    # it needs, and the money-weighted return can fail either the same
    # way (no elapsed time at all) or for a window so short relative to
    # its return that no annual rate, however large, discounts one back
    # into the other - `_money_weighted_return`'s bracket search gives up
    # rather than guess, so both read as one honest explanation instead
    # of two, only one of which is exercised by the tests that reach it.
    reasons = {}
    if cagr_value is None:
        reasons["cagr"] = (
            "a single trading day has no elapsed time to compound a growth rate over"
        )
    if volatility_value is None:
        reasons["volatility"] = (
            f"only {len(dates)} row(s) of price history in this window - "
            "fewer than the two returns needed to measure dispersion"
        )
    if money_weighted is None:
        reasons["moneyWeightedReturn"] = (
            "this window is too short for an internal rate of return to be found"
        )
    if time_under_water_value["longestDays"] is None:
        reasons["timeUnderWater"] = reasons["shareUnderWater"] = (
            f"only {len(dates)} row(s) of price history in this window - "
            "fewer than the two rows needed for an elapsed day to measure"
        )
    if calmar_value is None:
        reasons["calmar"] = (
            "CAGR is null for the same reason noted above"
            if cagr_value is None
            else "the run never fell below a prior peak, so there is no drawdown to divide by"
        )
    if rate is None:
        reasons["sharpe"] = reasons["sortino"] = (
            "no risk-free rate is available for this window, and no override was given"
        )
    else:
        if sharpe_value is None:
            reasons["sharpe"] = (
                "fewer than two period returns to measure a mean and a volatility from"
            )
        if sortino_value is None:
            reasons["sortino"] = (
                "fewer than two period returns, or none fell short of the target to "
                "measure a downside deviation from"
            )

    result = {
        "startValue": start_value,
        "finalValue": final_value,
        "totalReturn": total_return,
        "cagr": cagr_value,
        "volatility": volatility_value,
        "maxDrawdown": max_drawdown_value,
        # The longest single stretch below a prior peak, in calendar
        # days, and that time as a share of the whole window - 0 for
        # both is a real answer (the run was never under water), null
        # only when the window itself is too short to measure at all.
        "timeUnderWater": time_under_water_value["longestDays"],
        "shareUnderWater": time_under_water_value["shareOfWindow"],
        # Time-weighted average drawdown depth - 0 is a real answer here
        # too, for the same reason.
        "painIndex": pain_index_value,
        "calmar": calmar_value,
        "sharpe": sharpe_value,
        "sortino": sortino_value,
        # Which rate Sharpe/Sortino were actually scored against, and
        # where it came from - an explicit `?rate=` override, or the
        # tracked series' own average over this run's window. Null,
        # alongside both ratios, when neither was available.
        "riskFreeRate": rate,
        "riskFreeRateSource": rate_source,
        # Recurring contributions only: the opening lump sum is
        # `startValue`, and adding the two is what `totalInvested` is for.
        "contributed": round(contributed, MONEY_DP),
        "totalInvested": invested,
        # Recurring withdrawals only (issue #150): what was actually taken
        # out, which is less than what was scheduled for a portfolio that
        # ran dry. Never subtracted from `totalInvested` - that stays what
        # was paid in, because netting the two would let it go negative
        # for a portfolio drawn on for longer than it was funded.
        "withdrawn": round(withdrawn, MONEY_DP),
        # The row on which a withdrawal left nothing behind. Nothing else in
        # the response says the money is gone: the time-weighted figures
        # are read off a unit value that a withdrawal does not move. Null
        # means the run never ran out - it is not an "unknown".
        "depletedOn": depleted_on,
        # What the portfolio made, as opposed to what was paid into it.
        # Money taken out was still earned, so it is added back: a
        # portfolio that returned $2,000 and paid $1,500 of it to its
        # holder made $2,000, not $500.
        "gain": round(final_value + withdrawn - invested, MONEY_DP),
        "moneyWeightedReturn": money_weighted,
        # Income over the window, from the holdings the `dividends` table
        # can speak for. Never added to `finalValue`: the adjusted closes
        # already spent it (issue #13), and adding it would count the same
        # money twice.
        "dividendIncome": round(sum(income.values()), MONEY_DP),
        # As a percentage of every dollar paid in, which for a portfolio
        # funded once is its starting value and for one paid into monthly
        # is the whole of it. Dividing by the opening amount alone would
        # credit five years of deposits with the income they earned while
        # pretending they were never made.
        "dividendYield": (
            round(sum(income.values()) / invested * 100, PERCENT_DP) if invested > 0 else None
        ),
        # Holdings the income figure could not include, named rather than
        # counted: a total that quietly omits two of five holdings is worse
        # than one that says which two.
        "incomeUnknownFor": unknown,
    }
    if reasons:
        result["reasons"] = reasons
    return result


def _normalise_holdings(holdings) -> list[tuple[str, float]]:
    """Validate a requested basket and turn it into (ticker, share) pairs
    whose shares sum to 1.

    Raises ValueError - naming what is wrong - for anything unusable. The
    checks are deliberately about the basket rather than about the market:
    whether NVDA exists is a question for the price read, but whether it
    was asked for twice is answerable here, before anything is fetched.
    """
    if not isinstance(holdings, list) or not holdings:
        raise ValueError("`holdings` must be a non-empty list of {ticker, weight}")
    if len(holdings) > MAX_HOLDINGS:
        raise ValueError(
            f"`holdings` has {len(holdings)} entries, more than the {MAX_HOLDINGS} allowed"
        )

    pairs: list[tuple[str, float]] = []
    seen: set[str] = set()
    for entry in holdings:
        ticker = str(entry.get("ticker") or "").strip().upper()
        if not ticker:
            raise ValueError("every holding needs a `ticker`")
        if ticker in seen:
            raise ValueError(f"`{ticker}` appears twice - each holding must be one entry")
        seen.add(ticker)

        weight = entry.get("weight", 0)
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not math.isfinite(weight):
            raise ValueError(f"`{ticker}` has a weight that is not a number: {weight!r}")
        if weight < 0:
            raise ValueError(
                f"`{ticker}` has a negative weight ({weight}) - shorting is not modelled"
            )
        pairs.append((ticker, float(weight)))

    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        raise ValueError("the weights are all zero - there is nothing to invest in")

    return [(ticker, weight / total_weight) for ticker, weight in pairs]


def _normalise_schedule(
    schedule, field: str, frequencies: tuple[str, ...], negative_hint: str
) -> tuple[float, str | None]:
    """Validate an optional `{amount, frequency}` schedule - a recurring
    contribution or a recurring withdrawal, which are checked identically -
    into (amount, frequency). `field` names it in every message.

    Off is `(0.0, None)`, and there are three ways to mean it: send
    nothing, send null, or send an amount of zero. All three are the same
    request, and all three must simulate exactly as a run with no
    schedule at all - which is what makes "off by default" a promise
    rather than a hope.

    A frequency is required as soon as there is an amount to move: "$100"
    without saying how often is not a schedule, and picking one for the
    caller would move money in or out of their portfolio on dates they
    never asked for. Raises ValueError naming what is wrong.
    """
    if schedule is None:
        return 0.0, None
    if not isinstance(schedule, dict):
        raise ValueError(f"`{field}` must be an object with `amount` and `frequency`")

    amount = schedule.get("amount", 0) or 0
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or not math.isfinite(amount):
        raise ValueError(f"`{field}.amount` must be a number: {amount!r}")
    if amount < 0:
        raise ValueError(f"`{field}.amount` cannot be negative ({amount}){negative_hint}")
    if amount == 0:
        return 0.0, None

    frequency = schedule.get("frequency")
    if frequency not in frequencies:
        raise ValueError(
            f"`{field}.frequency` must be one of {', '.join(frequencies)}: {frequency!r}"
        )
    return float(amount), frequency


def _normalise_contribution(contribution) -> tuple[float, str | None]:
    """Validate an optional recurring contribution into (amount, frequency)."""
    return _normalise_schedule(
        contribution, "contribution", CONTRIBUTION_FREQUENCIES,
        # Money going out has its own field rather than a sign on this one:
        # an older build reads an amount at or below zero as "no schedule",
        # and would quietly simulate a withdrawal as a lump sum (ADR 0002).
        negative_hint=" - to take money out, send a `withdrawal` instead",
    )


def _normalise_withdrawal(withdrawal) -> tuple[float, str | None]:
    """Validate an optional recurring withdrawal into (amount, frequency)."""
    return _normalise_schedule(
        withdrawal, "withdrawal", WITHDRAWAL_FREQUENCIES,
        negative_hint=" - to pay money in, send a `contribution` instead",
    )


def _verify_absent(tickers: list[str], window_start: str) -> None:
    """Decide what a holding with no price rows in the window means.

    Three things look identical from the window's price read alone - all
    of them are simply an absent column - and they need three different
    answers. The resolver tells them apart:

      - **A typo.** No history at all, so `resolve_ticker` raises
        SymbolNotFound and main.py answers 404. It must not be quietly
        simulated as a pile of money.
      - **A holding that had not listed yet.** Real, with history starting
        after the window, which is exactly why the window has none of it.
        Simulated as cash until it lists (#56).
      - **A holding that should have been priced and was not.** Real, with
        history reaching back *before* the window started. There is no
        reading of that where the right answer is cash: the price read
        failed, and saying so is the only honest option (#86). This used
        to be the silent case - a portfolio holding one tracked stock and
        one ETF valued the ETF at zero for the whole run and reported the
        difference as cash.

    Raises SymbolNotFound (404) for the first and DataUnavailable (503)
    for the third. The third is retryable because it usually is: the
    upstream read that should have supplied those prices is what failed.
    """
    for ticker in tickers:
        resolved = resolve_ticker(ticker)
        first = resolved.get("firstDate")
        if first and first < window_start:
            raise DataUnavailable(
                f"{ticker} has prices from {first} but none could be read for this "
                "window - it cannot be valued right now"
            )


_INCOMPLETE_HISTORY = (
    "fewer than two of this basket's holdings have a complete price "
    "history over the window"
)
_NO_VARIANCE = "no measurable variance across this basket's holdings over this window"


def compute_portfolio_risk(
    holdings,
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """How independently this basket's own holdings actually move (issue
    #113) - the same basket a caller would send `simulate_portfolio`, over
    the same kind of window, but answering a different question: not what
    it would have been worth, but how much diversification its weights
    actually bought.

    Its own function, and its own route (`POST /api/portfolio/risk`),
    deliberately apart from `simulate_portfolio`: a correlation matrix
    over the basket is a second, wider price read than a value simulation
    needs, and folding it into every run would cost every simulation for
    the sake of the ones somebody actually asked a risk question of.
    Reads nothing and stores nothing, exactly as `simulate_portfolio`
    does, and is bounded by the same `MAX_HOLDINGS` via the same
    `_normalise_holdings`.

    Three figures, all read off the exact same joint covariance matrix
    (`services.stats._aligned_covariance`, shared with `fund_metrics.py`'s
    own use of it for a fund's basket rather than a simulated one -
    "sharing the risk-contribution and effective-N helpers" is the point,
    not a coincidence):

      - `averageCorrelation` - the average pairwise correlation among the
        basket's holdings. Lower means more diversified.
      - `effectiveBets` - the number of *equally weighted* holdings that
        would concentrate risk the same way the basket's actual risk
        contributions do (`stats.effective_n`, applied to `riskShare`
        rather than to the raw weights - the same helper `fund_metrics.py`
        never needed because it only ever asked this question of a fund's
        dollar weights, not of its risk shares). Applied to each share's
        *magnitude*, not its signed value: a holding whose own moves
        offset the rest of the basket's can carry a genuinely negative
        risk share (a real outcome of the Euler decomposition, not
        noise), and `effective_n` is built for a non-negative set of
        weights - feeding it a signed one would let that single holding
        push the result outside its own guaranteed range. Between 1 (all
        the risk sits in one holding, however many are in the basket) and
        the holding count (every holding contributes its risk
        independently) as a result, and exactly 1 for a basket of one
        holding by construction - one holding is one bet, regardless of
        whether there is even enough price history to measure its own
        variance.
      - `riskShare` - each holding's own share of the basket's variance,
        as a percentage that sums to 100 (`stats.risk_contribution`, the
        same Euler decomposition `fund_metrics.py` reads for a fund's
        basket). Not the same thing as dollar weight - a small, volatile,
        uncorrelated holding can carry far more of the basket's risk than
        its weight suggests.

    A basket of exactly one holding is answered directly, without needing
    any price history to measure a variance from: one holding is trivially
    all of the basket's risk and the only bet in it, so `effectiveBets`
    is `1.0` and `riskShare` is `{ticker: 100.0}` unconditionally.
    `averageCorrelation` stays null - there is no second holding to
    correlate it against - with its own reason rather than the shared
    "incomplete history" one below, which would misstate why.

    For two holdings or more: only a holding priced for every date in the
    window can join the joint covariance matrix, the same rule
    `fund_metrics.py` follows and for the same reason (see that module's
    own docstring) - a basket's variance decomposition needs one matrix
    built from every holding's returns aligned to the *same* stretch of
    dates at once, so narrowing the window to whatever a newly listed
    holding has traded would silently shrink every other holding's own
    window too. Fewer than two holdings with a complete history, or a
    basket with no measurable variance at all once aligned, reports all
    three null with a reason - the same two conditions
    `risk_contribution`/`diversification_ratio` themselves report `None`
    for.

    Raises ValueError for an unusable basket (see `_normalise_holdings`
    and `market_data.resolve_window`), SymbolNotFound for a holding that
    does not exist, and DataUnavailable when the price read fails
    upstream - the same three outcomes `simulate_portfolio` raises, for
    the same reasons.
    """
    weights = _normalise_holdings(holdings)
    tickers = [ticker for ticker, _ in weights]
    weight_of = dict(weights)

    closes = get_closes(tickers, period=period, start=start, end=end, min_tickers=1)
    if closes is None or closes.empty:
        raise ValueError(
            "no price data in the requested window - it may contain no trading days"
        )

    absent = [ticker for ticker in tickers if ticker not in closes.columns]
    if absent:
        _verify_absent(absent, closes.index[0].date().isoformat())

    result = {
        "start": closes.index[0].date().isoformat(),
        "end": closes.index[-1].date().isoformat(),
        "averageCorrelation": None,
        "effectiveBets": None,
        "riskShare": None,
        "reasons": {},
    }

    if len(tickers) == 1:
        ticker = tickers[0]
        result["effectiveBets"] = 1.0
        result["riskShare"] = {ticker: 100.0}
        result["reasons"]["averageCorrelation"] = (
            "a basket of one holding has no pair to correlate"
        )
        return result

    # Only a holding priced for every date in the frame can safely join a
    # joint covariance matrix - see fund_metrics.py's own docstring for
    # why this differs from a pairwise correlation's own approach.
    complete = [t for t in tickers if t in closes.columns and closes[t].notna().all()]
    if len(complete) < 2:
        result["reasons"] = {
            "averageCorrelation": _INCOMPLETE_HISTORY,
            "effectiveBets": _INCOMPLETE_HISTORY,
            "riskShare": _INCOMPLETE_HISTORY,
        }
        return result

    dates = [idx.date().isoformat() for idx in closes.index]
    values_by_ticker = {t: closes[t].tolist() for t in complete}
    used_weights = {t: weight_of[t] for t in complete}

    contributions = risk_contribution(values_by_ticker, dates, used_weights)
    ranked = [v for v in contributions.values() if v is not None]
    if not ranked:
        result["reasons"] = {
            "averageCorrelation": _NO_VARIANCE,
            "effectiveBets": _NO_VARIANCE,
            "riskShare": _NO_VARIANCE,
        }
        return result

    # effective_n is built for a non-negative set of weights (herfindahl's
    # own docstring: "each a fraction of the whole") and riskShare is not
    # one - a holding whose own moves offset the rest of the basket's can
    # carry a genuinely negative share (see compute_portfolio_risk's own
    # docstring), which is real and expected, not noise. Applying
    # effective_n straight to signed shares would let that one holding
    # push the result outside [1, holding count] - magnitude is what
    # keeps the bound a real guarantee, the same way diversification_
    # ratio's own Cauchy-Schwarz bound is guaranteed rather than merely
    # typical, instead of a property that happens to hold on tidy data.
    result["effectiveBets"] = effective_n([abs(v) for v in ranked])
    result["riskShare"] = contributions
    avg_corr = average_correlation(values_by_ticker, dates)
    result["averageCorrelation"] = avg_corr
    if avg_corr is None:
        result["reasons"]["averageCorrelation"] = (
            "no two holdings in this basket both had measurable variance to correlate"
        )
    return result


def simulate_portfolio(
    holdings,
    value: float,
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
    rebalance: str = "none",
    contribution=None,
    rate: float | None = None,
    withdrawal=None,
) -> dict:
    """Simulate `holdings` over a window, starting from `value` in cash.

    The stretch of history is named the same two ways every read in this
    codebase names one (see market_data.resolve_window): a `period`
    counting back from today, or an explicit `start`/`end`. They are
    mutually exclusive. "max" is the one a caller cannot express as dates,
    since how far back a basket reaches is a fact about its holdings
    rather than something to be guessed at and clamped.

    Returns the run in columnar form - one date array, one total array,
    one cash array, and one value array per holding - because that is the
    shape a stacked chart consumes, and it does not repeat a ticker's name
    once per date.

    Alongside the series: `metrics` scores the run as a whole (final
    value, total return, CAGR, volatility, deepest drawdown, time under
    water, pain index, Calmar, Sharpe, Sortino - issue #112 - and, once
    money keeps arriving, what was paid in, what was gained and the
    money-weighted return), and each holding carries its own price return,
    final value, share of the finished portfolio, and dollar contribution
    to its gain. Both are read whole rather than walked date by date, so
    they sit beside the arrays instead of inside them.

    `contribution` is optional and off by default: `{"amount": 100,
    "frequency": "monthly"}` pays that much in on the first row of every
    new month after the start, spread across the target weights. The
    `invested` array beside `total` is the running sum of everything paid
    in, so a chart can draw the money against the value without having to
    reconstruct the schedule.

    `withdrawal` is the same shape and the same off-by-default (issue
    #150): `{"amount": 100, "frequency": "monthly"}` takes that much out on
    the first row of every new month after the start. It cannot be
    combined with a `contribution` (ValueError). The `withdrawn` array
    beside `invested` is the running sum of what was actually taken - null
    when there is no schedule - and `metrics.depletedOn` the row a
    withdrawal left nothing behind, null when the money lasted.

    `rate` is optional too (issue #112, filed alongside #103): an
    override for the annual risk-free rate Sharpe/Sortino are scored
    against, percent per annum. Omitted, the tracked series' own average
    over this run's actual window is used instead - not a single point
    value, since the window a rate is read for should be the one it is
    scoring. `metrics.riskFreeRate`/`riskFreeRateSource` echo whichever
    one actually produced the two ratios, and both ratios are null with a
    reason when neither is available.

    The `start` and `end` in the response are the window actually
    simulated, which for "max" - or for any window reaching past the data -
    is narrower than the one asked for. It is the honest boundary, and
    what the frontend shows.

    Raises ValueError for an unusable request (see _normalise_holdings and
    resolve_window), SymbolNotFound for a holding that does not exist, and
    DataUnavailable when the price read fails upstream. Nothing is written
    anywhere: the portfolio arrives in the request and leaves in the
    response.
    """
    weights = _normalise_holdings(holdings)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"`value` must be a number: {value!r}")
    if value <= 0:
        raise ValueError(f"`value` must be greater than zero: {value!r}")
    if rebalance not in REBALANCE_FREQUENCIES:
        raise ValueError(
            f"`rebalance` must be one of {', '.join(REBALANCE_FREQUENCIES)}: {rebalance!r}"
        )
    pay_in, pay_every = _normalise_contribution(contribution)
    pay_out, take_every = _normalise_withdrawal(withdrawal)
    if pay_every is not None and take_every is not None:
        # ADR 0002. Not a preference for tidiness: the money-weighted return
        # is only guaranteed one answer while the run's cash flows change
        # sign once, and money going both in and out can change it several
        # times. Checked after both are normalised, so an amount of zero or
        # a null - which mean off - is not a second schedule.
        raise ValueError(
            "`contribution` and `withdrawal` cannot both be set - a portfolio "
            "pays in or draws out, never both"
        )

    tickers = [ticker for ticker, _ in weights]
    closes = get_closes(tickers, period=period, start=start, end=end, min_tickers=1)
    if closes is None or closes.empty:
        raise ValueError(
            "no price data in the requested window - it may contain no trading days"
        )

    # A holding with no column at all either does not exist (an error) or
    # had not listed by the end of the window (cash for the whole run).
    absent = [ticker for ticker in tickers if ticker not in closes.columns]
    if absent:
        _verify_absent(absent, closes.index[0].date().isoformat())
        closes = closes.copy()
        for ticker in absent:
            closes[ticker] = float("nan")

    # One frame, holdings in the caller's order, each one's gaps carried
    # forward from its last known close. Dates before a holding's first
    # close stay empty - that is what keeps its allocation in cash.
    closes = closes[tickers].ffill()

    invested = {ticker: 0.0 for ticker in tickers}   # shares held
    idle = {ticker: value * share for ticker, share in weights}  # not yet buyable

    dates: list[str] = []
    totals: list[float] = []
    cash_series: list[float] = []
    # Money paid in, running: the opening lump sum, then each
    # contribution as it lands. Drawn against `total` on the chart, so
    # what was deposited is never read as what was earned.
    invested_series: list[float] = []
    # Every payment, signed from the holder's side, for the IRR. The
    # closing value is appended as the one positive flow once it is known.
    cash_flows: list[tuple[pd.Timestamp, float]] = []
    paid_in = float(value)
    contributed = 0.0
    # Money taken out, running - the mirror of `invested_series`, and just
    # as much a series rather than a total so a chart can read the account
    # at any date without reconstructing the schedule.
    withdrawn = 0.0
    withdrawn_series: list[float] = []
    depleted_on: str | None = None
    # What crossed the portfolio's edge on each row - positive for money
    # arriving, negative for money leaving - which is exactly what has to be
    # taken back out again before a return is measured (see
    # stats.unit_values).
    inflows: list[float] = []
    values: dict[str, list[float]] = {ticker: [] for ticker in tickers}
    first_priced: dict[str, str | None] = {ticker: None for ticker in tickers}
    # Every dollar ever moved into a holding's position, less every dollar
    # taken back out of it by a rebalance. What is left over at the end -
    # final value minus this - is the money the holding actually made, and
    # it is the only way to attribute a gain once rebalancing starts moving
    # money between holdings (each holding's "contribution", below).
    flows = {ticker: 0.0 for ticker in tickers}
    # The holding's own price at each end of the stretch it was held over,
    # for the price return reported per holding.
    first_price: dict[str, float | None] = {ticker: None for ticker in tickers}
    last_price: dict[str, float | None] = {ticker: None for ticker in tickers}

    # Dividends over exactly the window the run turned out to cover, and
    # which of these holdings the record can speak for at all. Read here
    # rather than per holding: one query for the basket, like the prices.
    window_start = closes.index[0].date().isoformat()
    window_end = closes.index[-1].date().isoformat()
    events = get_dividends(tickers, start=window_start, end=window_end)
    on_record = tracked_tickers(tickers)
    income = {ticker: 0.0 for ticker in tickers}
    # How far through each holding's event list the walk has got. The
    # lists are sorted, so each is consumed once across the whole run.
    next_event = {ticker: 0 for ticker in tickers}

    previous = None
    for timestamp, row in closes.iterrows():
        prices = {ticker: row[ticker] for ticker in tickers}
        priced = {
            ticker: price
            for ticker, price in prices.items()
            if price == price and price > 0  # price == price rejects NaN
        }

        # Dividends whose ex-date has been reached, paid on the shares held
        # going into this row - that is, before anything this row does.
        # Holding *before* the ex-date is what earns the payment, so a
        # dividend dated on the window's own first row pays nothing: those
        # shares are bought at that close, after the fact.
        #
        # This only counts. It does not touch `invested`, `idle` or any
        # series, because the adjusted closes have already spent this money
        # on more of the same holding (issue #13) - the value is right, and
        # the income is a separate reading of the same run.
        for ticker in tickers:
            series = events.get(ticker)
            if not series:
                continue
            held = invested[ticker]
            index = next_event[ticker]
            while index < len(series) and series[index][0] <= timestamp.date().isoformat():
                income[ticker] += held * series[index][1]
                index += 1
            next_event[ticker] = index

        # Anything holding cash that can now be bought, is bought - at this
        # date's close, so the conversion moves no money.
        for ticker, price in priced.items():
            if first_priced[ticker] is None:
                first_priced[ticker] = timestamp.date().isoformat()
                first_price[ticker] = float(price)
            last_price[ticker] = float(price)
            if idle[ticker] > 0:
                flows[ticker] += idle[ticker]
                invested[ticker] += idle[ticker] / price
                idle[ticker] = 0.0

        # Money arriving, on the first row of a new period. Never on the
        # first row of the window: that one is the opening lump sum, and
        # paying a contribution into it as well would bill the holder
        # twice for the day they started.
        arrived = 0.0
        if (
            pay_every is not None
            and previous is not None
            and _period_key(timestamp, pay_every) != _period_key(previous, pay_every)
        ):
            arrived = pay_in
            contributed += pay_in
            paid_in += pay_in
            cash_flows.append((timestamp, -pay_in))
            # Spread across the target weights at this row's prices, with
            # a not-yet-listed holding's share waiting in cash exactly as
            # the opening allocation does.
            for ticker, share in weights:
                slice_of = pay_in * share
                price = priced.get(ticker)
                if price is None:
                    idle[ticker] += slice_of
                else:
                    flows[ticker] += slice_of
                    invested[ticker] += slice_of / price

        # Money leaving, on the same rule and in the same slot: before a
        # rebalance, so the targets are restored from what is left rather
        # than sold down to and then drawn on. Every holding - and any cash
        # still waiting for a holding to list - gives up the same fraction
        # of its current value, so a withdrawal changes how much is held
        # and never what the mix is. Spreading it over the *target* weights
        # the way a contribution is would try to sell more of a drifted
        # holding than it is now worth.
        taken = 0.0
        if (
            take_every is not None
            and previous is not None
            and _period_key(timestamp, take_every) != _period_key(previous, take_every)
        ):
            live_total = sum(invested[t] * p for t, p in priced.items()) + sum(idle.values())
            # Shorting is not modelled, so a withdrawal the portfolio cannot
            # cover takes what is left and the portfolio is empty from here
            # on: `taken` is what actually left, and everything downstream -
            # the gain, the money-weighted return, the series - reads that,
            # never the scheduled amount. Half a cent is the ledger's own
            # precision (MONEY_DP), so a balance that would be left with
            # less than that is empty rather than a fraction of a cent.
            if live_total > 0:
                emptied = live_total - pay_out < EMPTY_BELOW
                taken = live_total if emptied else pay_out
                fraction = 1.0 if emptied else pay_out / live_total
                for ticker in tickers:
                    price = priced.get(ticker)
                    if price is not None:
                        # Money out of the position, not a loss in it:
                        # netted from what was put in, so the holding's gain
                        # stays what it made (see "flows" above).
                        flows[ticker] -= invested[ticker] * price * fraction
                        invested[ticker] -= invested[ticker] * fraction
                    idle[ticker] -= idle[ticker] * fraction
                withdrawn += taken
                cash_flows.append((timestamp, taken))
                # The first row a withdrawal left nothing behind. Null for
                # a run that never got there means "did not run out" - not
                # "unknown", which is why this is not a reason string.
                if emptied and depleted_on is None:
                    depleted_on = timestamp.date().isoformat()

        if (
            rebalance != "none"
            and previous is not None
            and _period_key(timestamp, rebalance) != _period_key(previous, rebalance)
        ):
            live_total = sum(invested[t] * p for t, p in priced.items()) + sum(idle.values())
            for ticker, share in weights:
                target = live_total * share
                price = priced.get(ticker)
                if price is None:
                    # Still unlisted: its share of the new total waits in
                    # cash rather than being spent on the others.
                    invested[ticker], idle[ticker] = 0.0, target
                else:
                    # Topping the position up or selling it down is money
                    # in or out of it, not a gain or a loss.
                    flows[ticker] += target - invested[ticker] * price
                    invested[ticker], idle[ticker] = target / price, 0.0

        dates.append(timestamp.date().isoformat())
        held = 0.0
        for ticker in tickers:
            price = priced.get(ticker)
            holding_value = round(invested[ticker] * price, MONEY_DP) if price else 0.0
            values[ticker].append(holding_value)
            held += holding_value
        cash = round(sum(idle.values()), MONEY_DP)
        cash_series.append(cash)
        totals.append(round(held + cash, MONEY_DP))
        invested_series.append(round(paid_in, MONEY_DP))
        withdrawn_series.append(round(withdrawn, MONEY_DP))
        inflows.append(arrived - taken)
        previous = timestamp

    # The opening lump sum, and the closing value it all turned into: the
    # two ends of the IRR, with every contribution already in between.
    cash_flows.insert(0, (pd.Timestamp(dates[0]), -float(value)))
    cash_flows.append((pd.Timestamp(dates[-1]), totals[-1]))
    units = unit_values(totals, inflows)
    resolved_rate, rate_source = _resolve_rate(rate, window_start, window_end)

    return {
        "start": dates[0],
        "end": dates[-1],
        "startValue": round(float(value), MONEY_DP),
        "rebalance": rebalance,
        # Echoed the way `rebalance` is, so a response says what it was a
        # simulation of. Null when nothing was paid in.
        "contribution": (
            {"amount": round(pay_in, MONEY_DP), "frequency": pay_every} if pay_every else None
        ),
        # The same, for money taken out (issue #150). At most one of the two
        # is ever set: a portfolio pays in or draws out, never both.
        "withdrawal": (
            {"amount": round(pay_out, MONEY_DP), "frequency": take_every} if take_every else None
        ),
        "dates": dates,
        "total": totals,
        "cash": cash_series,
        "invested": invested_series,
        # Running sum of what was actually taken out. Null when there is no
        # withdrawal schedule, as `unitValue` is when nothing moved it away
        # from `total` - a copy of zeros would say there was a schedule.
        "withdrawn": withdrawn_series if take_every else None,
        # The flow-free series the metrics are read off, for a chart that
        # plots return rather than value: a percentage taken off `total`
        # would count the deposits (or read the withdrawals as losses), and
        # then the chart and the summary beside it would disagree about the
        # same line. Null when nothing was paid in or taken out, because
        # then it is `total` again and sending a copy would say there was a
        # difference.
        "unitValue": None if units is totals else [round(u, MONEY_DP) for u in units],
        "metrics": _metrics(
            totals, dates, units, cash_flows, contributed,
            withdrawn=withdrawn,
            depleted_on=depleted_on,
            income={t: v for t, v in income.items() if t in on_record},
            unknown=[t for t in tickers if t not in on_record],
            rate=resolved_rate,
            rate_source=rate_source,
        ),
        "holdings": [
            {
                "ticker": ticker,
                # The share actually simulated, as a percentage - the same
                # 0-100 vocabulary etf_holdings.weight uses - however the
                # request happened to express it.
                "weight": round(share * 100, 6),
                # None means the holding never had a price in this window:
                # its allocation sat in cash throughout.
                "firstDate": first_priced[ticker],
                "values": values[ticker],
                # The holding's own price return over the stretch it was
                # actually held - measured from its first close, which for
                # a late-listing holding is not the window's start, because
                # before that there was no price to return from.
                "return": (
                    round((last_price[ticker] / first_price[ticker] - 1) * 100, PERCENT_DP)
                    if first_price[ticker]
                    else None
                ),
                "finalValue": values[ticker][-1],
                # How much of the portfolio it ended up being.
                "share": (
                    round(values[ticker][-1] / totals[-1] * 100, PERCENT_DP)
                    if totals[-1] > 0
                    else 0.0
                ),
                # Dollars of the portfolio's gain that came from it: what
                # the position is worth, less every dollar put into it.
                # Rebalancing moves money between holdings, so a final
                # value on its own says nothing about who earned it.
                "contribution": round(values[ticker][-1] - flows[ticker], MONEY_DP),
                # Cash paid out by this holding over the window, on the
                # shares held at each ex-date. Already inside `finalValue`
                # via the adjusted closes, so it is a reading of the run
                # rather than something to add to it.
                #
                # None, not 0.0, for a holding the `dividends` table has no
                # record of - every ETF, and any symbol resolved live.
                # "Paid nothing" and "not on record here" are different
                # claims, and answering the second with the first would say
                # SPY pays no dividend.
                "income": round(income[ticker], MONEY_DP) if ticker in on_record else None,
            }
            for ticker, share in weights
        ],
    }
