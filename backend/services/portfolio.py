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

from services.market_data import SymbolNotFound, get_closes, get_price_series

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


def _period_key(timestamp: pd.Timestamp, frequency: str):
    """Which period a date belongs to. A rebalance happens on the first
    row whose key differs from the previous row's."""
    if frequency == "monthly":
        return timestamp.year, timestamp.month
    if frequency == "quarterly":
        return timestamp.year, (timestamp.month - 1) // 3
    return timestamp.year


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
    window's price read alone - both are simply an absent column. Asking
    for the symbol's whole history separates them: a real holding has one
    (starting after the window, which is why it is absent), and a typo has
    none, so it must not be quietly simulated as a pile of cash.

    The question is deliberately "does this have prices" rather than "does
    Yahoo know the name": a made-up ticker's info request comes back as a
    shell dict rather than an error (the same quirk api/routes.py's get_etf
    works around), so a name proves nothing, while a symbol with no price
    history cannot be simulated whatever it is called. Issue #58 replaces
    this with a shared resolver that also reports the first date available.

    Raises SymbolNotFound naming the ticker; main.py answers 404.
    """
    for ticker in tickers:
        try:
            history = get_price_series(ticker, period="max")
        except SymbolNotFound as exc:
            raise SymbolNotFound(f"no such symbol: '{ticker}'") from exc
        if not history:
            raise SymbolNotFound(f"no price history for '{ticker}'")


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
            if idle[ticker] > 0:
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
            }
            for ticker, share in weights
        ],
    }
