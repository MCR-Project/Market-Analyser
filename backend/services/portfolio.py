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

How the run is then scored, in one place because a number is only worth
as much as the convention behind it:

  - **Returns are simple, not logarithmic**, taken between consecutive
    rows of the run's own calendar.

  - **Performance is time-weighted; the account is money-weighted.** A
    deposit is not a gain. Paying $100 into a $1,000 portfolio moves the
    total 10% on a day the market did nothing, and left alone that flows
    straight into the volatility, the drawdown and the return. So every
    metric describing *the portfolio* - total return, CAGR, volatility,
    drawdown - is computed on a flow-free unit value that only moves when
    prices do, while the money-weighted return (IRR) answers the different
    question of what the money itself earned given when it arrived. With
    no contributions the unit value is the total, and the two questions
    have the same answer.

  - **A year is 365.25 days.** CAGR compounds over the calendar time the
    window actually covers, so the same year answered in twelve monthly
    buckets or 250 daily rows annualises to the same rate.

  - **Volatility is annualised to 252 trading days**, with each return
    first divided by the root of the trading time it actually covers. For
    a window of daily rows that is exactly the textbook "daily standard
    deviation times root 252"; for the older half of a long window, where
    `prices` answers in weekly or monthly buckets, it is what stops a
    week's movement being read as a day's.

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

  - **A holding's contribution is its final value less every dollar put
    into it.** Once a rebalance starts moving money between holdings, a
    final value says nothing about which holding earned it; the flows
    have to be netted out. Contributions add up to the portfolio's gain.

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
    tracked_tickers,
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

# Money is reported to the cent. Each holding's value is rounded, and the
# total is summed from those rounded parts rather than computed alongside
# them, so a stacked chart's bands add up to exactly the total line drawn
# above them.
MONEY_DP = 2

# Percentages keep more precision than they will be shown at, so a caller
# can round them for display without the rounding having happened twice.
PERCENT_DP = 4

# Annualisation. Volatility is scaled to a year of trading days; a year is
# 365.25 calendar days, which is also what CAGR compounds over, so the two
# agree about how long a year is.
TRADING_DAYS_PER_YEAR = 252
DAYS_PER_YEAR = 365.25


def _period_key(timestamp: pd.Timestamp, frequency: str):
    """Which period a date belongs to. A rebalance happens on the first
    row whose key differs from the previous row's."""
    if frequency == "monthly":
        return timestamp.year, timestamp.month
    if frequency == "quarterly":
        return timestamp.year, (timestamp.month - 1) // 3
    return timestamp.year


def _trading_days(gap_days: int) -> float:
    """How much trading time one gap between rows covers.

    Consecutive rows of the daily tier are one trading day apart whether
    or not a weekend sits between them - Friday to Monday is one day of
    market, not three. A coarser bucket is converted in proportion: a
    weekly row spans about 4.8 trading days, a monthly one about 21.
    """
    if gap_days <= 4:
        return 1.0
    return gap_days * TRADING_DAYS_PER_YEAR / DAYS_PER_YEAR


def _volatility(totals: list[float], dates: list[str]) -> float | None:
    """Annualised standard deviation of the run's returns, as a percentage.

    Each return is first divided by the square root of the trading time it
    covers, which puts a weekly bucket's return and a daily row's return
    into the same units before either is annualised by the usual 252. For
    a window answered entirely from the daily tier this is exactly the
    textbook "standard deviation of daily returns, times root 252"; the
    scaling only starts to matter when `prices` answers in coarser buckets
    (issue #10).

    That is not a refinement. A real 2019-2026 basket comes back as 198
    daily gaps, 207 weekly ones and 27 monthly: annualising every one of
    them by 252 reads a week's movement as a day's and reported 54%
    volatility where the same basket's true daily history gives 35% and
    its weekly 31%. Picking one factor for the whole window instead only
    moves which half of it is wrong. Scaling each return by its own gap is
    what makes the number mean one thing across a window spanning tiers.

    None rather than 0 when there are fewer than two returns to compare:
    a single return has no dispersion to measure, and reporting 0 would
    claim a portfolio held for two days was riskless.
    """
    parsed = [pd.Timestamp(d) for d in dates]
    scaled = [
        (totals[i] / totals[i - 1] - 1) / math.sqrt(_trading_days((parsed[i] - parsed[i - 1]).days))
        for i in range(1, len(totals))
        if totals[i - 1] > 0
    ]
    if len(scaled) < 2:
        return None
    mean = sum(scaled) / len(scaled)
    variance = sum((r - mean) ** 2 for r in scaled) / (len(scaled) - 1)
    return round(math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100, PERCENT_DP)


def _cagr(totals: list[float], dates: list[str]) -> float | None:
    """Compound annual growth rate, as a percentage, over the calendar
    time the run actually covers.

    Elapsed calendar days rather than a row count, so a window answered in
    twelve monthly buckets and one answered in 250 daily rows over the same
    year annualise to the same rate. None when there is no elapsed time to
    compound over - a single row, or every row on one date.
    """
    if len(totals) < 2 or totals[0] <= 0:
        return None
    days = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days
    if days <= 0:
        return None
    growth = totals[-1] / totals[0]
    return round((growth ** (DAYS_PER_YEAR / days) - 1) * 100, PERCENT_DP)


def _unit_values(totals: list[float], inflows: list[float]) -> list[float]:
    """The total with the deposits taken back out of it.

    A contribution is not a gain. Paying $100 into a $1,000 portfolio
    takes the total to $1,100 on a day the market did nothing, and any
    metric read straight off the total records that as a 10% day - which
    then lands in the volatility, in the drawdown, and in the return.

    So each step is measured against the money that was actually working
    before it: the row's total less whatever arrived that day, over the
    previous row's total. Chaining those steps gives a series that starts
    where the portfolio started and only ever moves because prices did -
    the standard time-weighted construction, in the one place every metric
    reads from.

    Returned as `totals` itself when nothing was ever paid in, so a run
    without contributions is not merely close to the old result but the
    same object.
    """
    if not any(inflows):
        return totals

    units = [totals[0]]
    for i in range(1, len(totals)):
        previous = totals[i - 1]
        # A portfolio worth nothing has no proportion left to grow by, and
        # dividing by it would invent one. It stays where it is.
        if previous <= 0:
            units.append(units[-1])
            continue
        units.append(units[-1] * (totals[i] - inflows[i]) / previous)
    return units


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
    and one positive flow at the end for what it is all worth. That shape
    has exactly one sign change, so there is exactly one rate that solves
    it, and bisection finds it without needing a derivative or a starting
    guess to be lucky. NPV falls as the rate rises, so the bracket is
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


def _max_drawdown(totals: list[float], dates: list[str]) -> dict:
    """The deepest peak-to-trough fall in the run, as a negative
    percentage, with the dates of both ends.

    Measured on the total value, which is the only series a holder
    experiences - an individual holding can fall much further without the
    portfolio noticing. A run that never falls reports 0 and no dates:
    there is no peak and no trough to point at, and naming the first date
    would invent a drawdown that did not happen.
    """
    worst, peak_at, trough_at = 0.0, None, None
    peak, peak_date = totals[0], dates[0]
    for date_str, total in zip(dates, totals):
        if total > peak:
            peak, peak_date = total, date_str
        if peak > 0:
            drawdown = total / peak - 1
            if drawdown < worst:
                worst, peak_at, trough_at = drawdown, peak_date, date_str
    return {
        "value": round(worst * 100, PERCENT_DP),
        "peakDate": peak_at,
        "troughDate": trough_at,
    }


def _metrics(
    totals: list[float],
    dates: list[str],
    units: list[float],
    flows: list[tuple[pd.Timestamp, float]],
    contributed: float,
    income: dict[str, float],
    unknown: list[str],
) -> dict:
    """How the run did, as one object beside the series rather than
    interleaved into it - a summary is read whole, not walked date by
    date.

    Two families of number, and the split is the point. Total return,
    CAGR, volatility and drawdown are read off `units` - the flow-free
    unit value - and describe **the portfolio**: what a dollar left alone
    in it would have done. Contributed, invested, gain and the
    money-weighted return are read off the cash flows and describe **the
    account**: what actually went in, what came out, and the rate that
    reconciles the two given when each dollar arrived.

    With no contributions `units` is `totals` and the two families agree,
    which is why a run with contributions switched off is unchanged.
    """
    start_value, final_value = totals[0], totals[-1]
    unit_start, unit_end = units[0], units[-1]
    total_return = (
        round((unit_end / unit_start - 1) * 100, PERCENT_DP) if unit_start > 0 else None
    )
    invested = round(start_value + contributed, MONEY_DP)
    return {
        "startValue": start_value,
        "finalValue": final_value,
        "totalReturn": total_return,
        "cagr": _cagr(units, dates),
        "volatility": _volatility(units, dates),
        "maxDrawdown": _max_drawdown(units, dates),
        # Recurring contributions only: the opening lump sum is
        # `startValue`, and adding the two is what `totalInvested` is for.
        "contributed": round(contributed, MONEY_DP),
        "totalInvested": invested,
        # What the portfolio made, as opposed to what was paid into it.
        "gain": round(final_value - invested, MONEY_DP),
        "moneyWeightedReturn": _money_weighted_return(flows),
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


def _normalise_contribution(contribution) -> tuple[float, str | None]:
    """Validate an optional recurring contribution into (amount, frequency).

    Off is `(0.0, None)`, and there are three ways to mean it: send
    nothing, send null, or send an amount of zero. All three are the same
    request, and all three must simulate exactly as a run with no
    contributions at all - which is what makes "off by default" a promise
    rather than a hope.

    A frequency is required as soon as there is an amount to pay: "$100"
    without saying how often is not a schedule, and picking one for the
    caller would put money into their portfolio on dates they never asked
    for. Raises ValueError naming what is wrong.
    """
    if contribution is None:
        return 0.0, None
    if not isinstance(contribution, dict):
        raise ValueError("`contribution` must be an object with `amount` and `frequency`")

    amount = contribution.get("amount", 0) or 0
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or not math.isfinite(amount):
        raise ValueError(f"`contribution.amount` must be a number: {amount!r}")
    if amount < 0:
        raise ValueError(
            f"`contribution.amount` cannot be negative ({amount}) - withdrawals are not modelled"
        )
    if amount == 0:
        return 0.0, None

    frequency = contribution.get("frequency")
    if frequency not in CONTRIBUTION_FREQUENCIES:
        raise ValueError(
            "`contribution.frequency` must be one of "
            f"{', '.join(CONTRIBUTION_FREQUENCIES)}: {frequency!r}"
        )
    return float(amount), frequency


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


def simulate_portfolio(
    holdings,
    value: float,
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
    rebalance: str = "none",
    contribution=None,
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
    value, total return, CAGR, volatility, deepest drawdown, and - once
    money keeps arriving - what was paid in, what was gained and the
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
    # What arrived on each row, which is exactly what has to be taken back
    # out again before a return is measured (see _unit_values).
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
        inflows.append(arrived)
        previous = timestamp

    # The opening lump sum, and the closing value it all turned into: the
    # two ends of the IRR, with every contribution already in between.
    cash_flows.insert(0, (pd.Timestamp(dates[0]), -float(value)))
    cash_flows.append((pd.Timestamp(dates[-1]), totals[-1]))
    units = _unit_values(totals, inflows)

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
        "dates": dates,
        "total": totals,
        "cash": cash_series,
        "invested": invested_series,
        # The flow-free series the metrics are read off, for a chart that
        # plots return rather than value: a percentage taken off `total`
        # would count the deposits, and then the chart and the summary
        # beside it would disagree about the same line. Null when there
        # were no contributions, because then it is `total` again and
        # sending a copy would say there was a difference.
        "unitValue": None if units is totals else [round(u, MONEY_DP) for u in units],
        "metrics": _metrics(
            totals, dates, units, cash_flows, contributed,
            income={t: v for t, v in income.items() if t in on_record},
            unknown=[t for t in tickers if t not in on_record],
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
