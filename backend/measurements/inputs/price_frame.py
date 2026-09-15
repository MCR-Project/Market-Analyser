"""
Input getter: bulk close (optionally volume) price history for a set of
tickers (issue #102).

Like correlation_matrix, this getter needs a ticker list rather than an
etf_id directly - measurements first resolve holdings via
inputs.holdings.get_holdings(etf_id), then pass the resulting tickers
here, so a plugin using both inputs (a rolling correlation column, say)
fetches holdings once rather than twice.

`period` defaults to CORRELATION_PERIOD - the same window the correlation
matrix reads - specifically so the two share services.market_data's cache
entry for that read instead of each issuing its own bulk query for the
same tickers and window.
"""

from config import CORRELATION_PERIOD
from services.market_data import get_price_frame as _get_price_frame

DEFAULT_PERIOD = CORRELATION_PERIOD


def get_price_frame(
    tickers: list[str], period: str = DEFAULT_PERIOD, include_volume: bool = False
) -> dict:
    """Close prices (and, when asked, volume) for `tickers` over `period`.

    Returns {ticker: {"closes": [[date, close], ...]}} by default, or with
    a "volume" key added - [{"date", "volume", "granularity"}, ...] or
    None, see services.market_data.get_price_frame - when include_volume
    is set. Left off entirely (rather than always sent and mostly unused)
    so a plain price-history metric's worked example isn't cluttered with
    a field it never reads.
    """
    frame = _get_price_frame(tickers, period=period)
    if include_volume:
        return frame
    return {ticker: {"closes": value["closes"]} for ticker, value in frame.items()}


def get_aligned_closes(tickers: list[str], period: str = DEFAULT_PERIOD) -> tuple[list[str], dict[str, list[float]]]:
    """Close prices for `tickers` over `period`, restricted to exactly
    the tickers priced for every date in the window's own trading
    calendar and aligned to that shared date list (issue #107) - the
    rectangular shape a joint calculation (risk_contribution, a fund's
    own weighted index) needs, rather than `get_price_frame`'s own ragged
    per-ticker `[[date, close], ...]` shape.

    The reference calendar is taken as whichever requested ticker
    reports the most priced dates, not the intersection across all of
    them - the same reasoning `services/fund_metrics.py` states for the
    fund-level card (issue #105): a joint calculation needs every series
    aligned to the *same* stretch of dates at once, and narrowing that
    stretch down to whatever a single newly-listed holding has traded
    would shrink a year-old fund's own window to a few weeks the moment
    it gained one new position. A ticker missing any date in that
    calendar is excluded entirely rather than forward-filled.

    Returns `(dates, values_by_ticker)` - `values_by_ticker` only has an
    entry for a ticker that made the cut; both are empty when nothing did
    (no tickers, or none with any priced history at all).
    """
    frame = get_price_frame(tickers, period=period)
    per_ticker_dates = {t: dict(frame[t]["closes"]) for t in frame if frame[t]["closes"]}
    if not per_ticker_dates:
        return [], {}

    reference_ticker = max(per_ticker_dates, key=lambda t: len(per_ticker_dates[t]))
    dates = sorted(per_ticker_dates[reference_ticker].keys())
    complete = [
        t for t in tickers
        if t in per_ticker_dates and all(d in per_ticker_dates[t] for d in dates)
    ]
    values_by_ticker = {t: [per_ticker_dates[t][d] for d in dates] for t in complete}
    return dates, values_by_ticker


def _sample(etf_id: str, tickers: list[str]):
    """Real value of this input for one ETF, for a doc's worked example.

    Unlike holdings/etf_info this one takes tickers rather than an etf_id
    - the caller has already resolved the fund's full holdings - and
    includes volume, the same way a doc page should show the whole shape
    a measurement might read, not just the part today's official
    measurements happen to use.
    """
    return get_price_frame(tickers, include_volume=True) if tickers else {}


# Self-description for the documentation page - see inputs/__init__.py.
# The defaults matter to a reader: they are the window the numbers
# describe, and nothing in the UI exposes them for a metric that doesn't
# itself declare window_options.
INPUT_SPEC = {
    "description": (
        "Close prices for the fund's holdings, one bulk query for the "
        "whole basket, plus volume wherever the database can answer for "
        "it. Volume is null, not zero, for a holding with no `prices` "
        "rows at all - every ETF, and anything resolved outside the "
        "tracked universe."
    ),
    "defaults": {"period": DEFAULT_PERIOD, "interval": "1d"},
    "sample": _sample,
}
