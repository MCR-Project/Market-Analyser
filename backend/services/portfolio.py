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

How the run is then scored, in one place because a number is only worth
as much as the convention behind it:

  - **Returns are simple, not logarithmic**, taken between consecutive
    rows of the run's own calendar.

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

from services.market_data import get_closes
from services.tickers import resolve_ticker

# A ceiling on basket size, so one request cannot ask for an unbounded
# price read. Well clear of what a portfolio copied from a tracked ETF
# holds (only constituents weighing >=1% of their fund are tracked).
MAX_HOLDINGS = 100

# How often the target weights are restored. "none" is buy and hold.
REBALANCE_FREQUENCIES = ("none", "monthly", "quarterly", "yearly")

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


def _metrics(totals: list[float], dates: list[str]) -> dict:
    """How the run did, as one object beside the series rather than
    interleaved into it - a summary is read whole, not walked date by
    date."""
    start_value, final_value = totals[0], totals[-1]
    total_return = (
        round((final_value / start_value - 1) * 100, PERCENT_DP) if start_value > 0 else None
    )
    return {
        "startValue": start_value,
        "finalValue": final_value,
        "totalReturn": total_return,
        "cagr": _cagr(totals, dates),
        "volatility": _volatility(totals, dates),
        "maxDrawdown": _max_drawdown(totals, dates),
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


def _verify_absent(tickers: list[str]) -> None:
    """Decide what a holding with no price rows in the window means.

    A typo and a company that had not listed yet look identical from the
    window's price read alone - both are simply an absent column. The
    resolver settles it: a real holding has history (starting after the
    window, which is why it is absent) and is simulated as cash, while a
    symbol with none is a typo that must not be quietly simulated as a
    pile of money.

    Raises SymbolNotFound naming the ticker; main.py answers 404.
    """
    for ticker in tickers:
        resolve_ticker(ticker)


def simulate_portfolio(
    holdings,
    value: float,
    start: str | None = None,
    end: str | None = None,
    rebalance: str = "none",
) -> dict:
    """Simulate `holdings` over a window, starting from `value` in cash.

    Returns the run in columnar form - one date array, one total array,
    one cash array, and one value array per holding - because that is the
    shape a stacked chart consumes, and it does not repeat a ticker's name
    once per date.

    Alongside the series: `metrics` scores the run as a whole (final
    value, total return, CAGR, volatility, deepest drawdown), and each
    holding carries its own price return, final value, share of the
    finished portfolio, and dollar contribution to its gain. Both are read
    whole rather than walked date by date, so they sit beside the arrays
    instead of inside them.

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

    tickers = [ticker for ticker, _ in weights]
    closes = get_closes(tickers, start=start, end=end, min_tickers=1)
    if closes is None or closes.empty:
        raise ValueError(
            "no price data in the requested window - it may contain no trading days"
        )

    # A holding with no column at all either does not exist (an error) or
    # had not listed by the end of the window (cash for the whole run).
    absent = [ticker for ticker in tickers if ticker not in closes.columns]
    if absent:
        _verify_absent(absent)
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

    previous = None
    for timestamp, row in closes.iterrows():
        prices = {ticker: row[ticker] for ticker in tickers}
        priced = {
            ticker: price
            for ticker, price in prices.items()
            if price == price and price > 0  # price == price rejects NaN
        }

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
        previous = timestamp

    return {
        "start": dates[0],
        "end": dates[-1],
        "startValue": round(float(value), MONEY_DP),
        "rebalance": rebalance,
        "dates": dates,
        "total": totals,
        "cash": cash_series,
        "metrics": _metrics(totals, dates),
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
            }
            for ticker, share in weights
        ],
    }
