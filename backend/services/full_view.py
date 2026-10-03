"""
What a Full view is drawn from (issue #173): a deep-filled fund's whole-basket
correlation matrix and clusters, in a payload bounded for ~500 holdings.

Pure - no I/O, no clock, no store. `deep_fill._derive` calls `build` once, when a
Deep-fill finishes, and the store holds the answer with the fund's result; the
route only reads it back. That is what lets a Full view say "as of when it was
drawn" and never compute on open (the owner's snapshot requirement,
docs/adr/0006-deep-fill-writes-nothing-to-the-database.md).

**Why not the matrix `GET /api/correlation` serves.** That is `{a: {b: ρ}}` - 250,000
entries for 500 holdings, each carrying both tickers' names and four decimals, several
megabytes of JSON for a page that only wants to colour squares. The Full view's shape:

- `tickers` and `weights` (fund weight %) side by side, in the fund's own order,
  heaviest first, for the holdings the matrix could be computed for;
- `correlation.triangle`, the **lower triangle without the diagonal**: row `i` holds
  the ρ between `tickers[i]` and each of `tickers[0..i-1]`, so row 0 is empty and the
  whole matrix is N(N-1)/2 numbers (~125,000 for 500 holdings, about 0.6 MB). ρ is
  symmetric and a holding's correlation with itself is 1 by definition, so nothing is
  lost; the page rebuilds the square.
- ρ rounded to `DECIMALS` places - the figure the page prints and the colour scale
  is no finer than.
- `averages` (parallel to `tickers`) and `clusters`, as the correlation endpoint
  gives them, because the matrix's cluster order is built from them (matrixOrder.js).
- `excluded`: every holding the fund lists that is *not* in `tickers`, with why.

A pair with too little shared history has no correlation (issue #97) and is `null`
here, as in the matrix it came from - never 0 (invariant 7).
"""

DECIMALS = 2

NO_HISTORY = "it has no usable price history over the past year"


def _round(value) -> float | None:
    if value is None:
        return None
    # `+ 0.0` turns the -0.0 a small negative rounds to into 0.0, which would
    # otherwise travel as "-0.0".
    return round(float(value), DECIMALS) + 0.0


def build(holdings: list[list], matrix_result: dict, failures: dict[str, str], period: str) -> dict:
    """The payload for one fund.

    `holdings` is every holding the fund lists, `[ticker, weight%]`, in the fund's
    order; `matrix_result` is `compute_correlation_matrix` over all of them;
    `failures` is `{ticker: why}` for the holdings the Deep-fill could not fetch.
    """
    available = list(matrix_result["tickers"])
    matrix = matrix_result["matrix"]
    weight_of = {ticker: weight for ticker, weight in holdings}
    drawn = set(available)

    return {
        "period": period,
        "tickers": available,
        "weights": [weight_of[t] for t in available],
        "averages": [matrix_result["averages"].get(t) for t in available],
        "clusters": [list(group) for group in matrix_result["clusters"]],
        "correlation": {
            "decimals": DECIMALS,
            "triangle": [
                [_round(matrix[a].get(available[j])) for j in range(i)]
                for i, a in enumerate(available)
            ],
        },
        "excluded": {
            ticker: failures.get(ticker, NO_HISTORY)
            for ticker, _ in holdings if ticker not in drawn
        },
    }
