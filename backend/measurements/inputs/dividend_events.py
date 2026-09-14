"""
Input getter: dividend events for a set of tickers, plus which of them the
`ticker` table actually knows about (issue #102).

Like correlation_matrix and price_frame, this getter needs a ticker list
rather than an etf_id directly - measurements first resolve holdings via
inputs.holdings.get_holdings(etf_id), then pass the resulting tickers
here.

Wraps services.market_data.get_dividends together with tracked_tickers
rather than exposing either alone, because get_dividends' own "absent
means no events in the window" is ambiguous by itself - a ticker with a
genuinely empty events list (on record, paid nothing) and one the
`ticker` table has never heard of (every ETF, and anything resolved
outside the tracked universe) both come back the same way. A caller using
only get_dividends could not tell "paid nothing" from "no record here"
without also asking tracked_tickers, so this getter asks both and keeps
the two meanings apart - the same distinction
services/portfolio.py's own income/incomeUnknownFor already makes for the
simulator (see README.md's "Dividends" section).

No window here, unlike price_frame: a measurement wanting a fund's whole
dividend history reads it in one call rather than one bounded to whatever
window a price-based column happens to be showing.
"""

from services.market_data import get_dividends, tracked_tickers


def get_dividend_events(tickers: list[str]) -> dict:
    """Every recorded dividend event per ticker, plus whether it is
    tracked at all.

    Returns {ticker: {"events": [[date, amount], ...], "tracked": bool}}
    for every requested ticker. `tracked=False` (every ETF, and anything
    resolved outside the tracked universe) means "no record here", not
    "paid nothing" - `events` is `[]` either way, so a caller must read
    `tracked` to tell the two apart rather than treating an empty list on
    its own as an answer.
    """
    events = get_dividends(tickers)
    on_record = tracked_tickers(tickers)
    return {
        ticker: {
            "events": [list(pair) for pair in events.get(ticker, [])],
            "tracked": ticker in on_record,
        }
        for ticker in tickers
    }


def _sample(etf_id: str, tickers: list[str]):
    """Real value of this input for one ETF, for a doc's worked example."""
    return get_dividend_events(tickers) if tickers else {}


# Self-description for the documentation page - see inputs/__init__.py.
INPUT_SPEC = {
    "description": (
        "Dividend events per holding - one [date, amount] pair per "
        "ex-date, unadjusted - alongside whether the `ticker` table "
        "tracks that holding at all, which is what lets a caller tell "
        "'tracked, paid nothing' from 'no record here' rather than "
        "reading both as the same empty list."
    ),
    "defaults": {},
    "sample": _sample,
}
