"""
Weighted Correlation measurement - each holding's average ρ to its peers, every
peer counting in proportion to its fund weight (issue #185).

A standalone plugin rather than a second column on `correlation`, so that
column's id, route and values do not move. It reads the same cached one-year
matrix `correlation` does, so it adds no price read of its own; the arithmetic
is `services.stats.weighted_peer_correlation`, shared with GET /api/correlation
so the table column and the Network tab's card are one number.
"""

from config import MIN_OVERLAPPING_RETURNS
from measurements.base import MeasurementBase
from measurements.inputs.correlation_matrix import get_correlation_matrix
from measurements.inputs.holdings import get_holdings
from services.stats import weighted_peer_correlation

_NO_HISTORY_REASON = "no price history to correlate"
_TOO_FEW_HOLDINGS_REASON = "fewer than two of the fund's holdings have price history to correlate"
_NO_OVERLAP_REASON = (
    f"fewer than {MIN_OVERLAPPING_RETURNS} overlapping daily returns with any other holding in the fund"
)
_NO_WEIGHT_REASON = "every peer it correlates with has no fund weight to count"


class WeightedCorrelationMeasurement(MeasurementBase):
    id = "weighted_correlation"
    name = "Weighted Correlation"
    description = (
        "Average Pearson correlation of each holding's daily returns to the "
        "other holdings of its fund, each peer counting in proportion to its "
        "fund weight - so a heavy peer such as NVDA moves the figure far more "
        "than one weighing a fraction of a percent; unknown, not zero, for a "
        "holding with no computed pair"
    )
    route = "/measurements/weighted-correlation/{etf_id}"
    uses_inputs = ["holdings", "correlation_matrix"]

    # Table column - a fixed one-year lookback like `correlation`, so no window
    # options and the same bar, range and step.
    column_key = "weighted_corr"
    column_label = "WEIGHTED ρ"
    column_width = 350
    default_enabled = False

    filterable = True
    filter_type = "range"
    filter_min = 0
    filter_max = 0.9
    filter_step = 0.05

    sort_type = "numerical"

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker":        {"type": "Record<string, number>", "description": "Ticker → fund-weighted average ρ to its peers"},
        "per_ticker_mdx":    {"type": "Record<string, string>", "description": "Ticker → MDX snippet for display, e.g. <Bar value={0.7} label=\".70\" />"},
        "per_ticker_reason": {"type": "Record<string, string>", "description": "Ticker → why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        weights = {t: w for t, w in holdings}
        matrix = {}
        if tickers:
            matrix = get_correlation_matrix(tickers).get("matrix") or {}
        return {"tickers": tickers, "weights": weights, "matrix": matrix}

    def compute(self, inputs: dict) -> dict:
        tickers = inputs["tickers"]
        matrix = inputs["matrix"]

        scores = weighted_peer_correlation(matrix, inputs["weights"])

        # Every holding gets an entry, so a dash is explained rather than absent -
        # including the ones the matrix dropped for want of any price history,
        # which is also what lets a deep-filled fund's own reason replace ours.
        per_ticker = {t: scores.get(t) for t in tickers}
        per_ticker_reason = {}
        for ticker in tickers:
            if per_ticker[ticker] is not None:
                continue
            if len(matrix) < 2:
                # An empty or one-ticker matrix: nobody has a peer to correlate with,
                # which is not the same fact as "this holding has no history".
                per_ticker_reason[ticker] = _TOO_FEW_HOLDINGS_REASON
            elif ticker not in matrix:
                per_ticker_reason[ticker] = _NO_HISTORY_REASON
            elif any(
                rho is not None for peer, rho in matrix[ticker].items() if peer != ticker
            ):
                per_ticker_reason[ticker] = _NO_WEIGHT_REASON
            else:
                per_ticker_reason[ticker] = _NO_OVERLAP_REASON
        return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        """The same filled bar + ρ pill `correlation` draws. `value` clamps to
        [0, 1] on the frontend, so it is passed through as-is."""
        if value is None:
            return "—"
        label = "1.00" if value >= 0.995 else f"{value:.2f}".replace("0.", ".")
        return f'<Bar value={{{value}}} label="{label}" />'
