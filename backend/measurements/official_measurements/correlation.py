"""
Correlation measurement — pairwise Pearson ρ of daily returns across ETF holdings.
"""

from measurements.base import MeasurementBase
from measurements.inputs.holdings import get_holdings
from measurements.inputs.correlation_matrix import get_correlation_matrix


class CorrelationMeasurement(MeasurementBase):
    id = "correlation"
    name = "Correlation to Fund"
    description = "Average Pearson correlation of each holding's daily returns to all other holdings"
    route = "/measurements/correlation/{etf_id}"
    uses_inputs = ["holdings", "correlation_matrix"]

    # Table column — shows per-ticker average ρ
    column_key = "avg_corr"
    column_label = "CORRELATION"
    column_width = 350
    default_enabled = True

    # Filter: range slider for minimum ρ
    filterable = True
    filter_type = "range"
    filter_min = 0
    filter_max = 0.9
    filter_step = 0.05

    # Sort: plain numeric comparison of average ρ
    sort_type = "numerical"

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker":     {"type": "Record<string, number>", "description": "Ticker → average ρ to all peers"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet for display, e.g. <Bar value={0.35} label=\"0.35\" />"},
        "matrix":         {"type": "Record<string, Record<string, number>>", "description": "Full NxN matrix"},
    }

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        return {"tickers": tickers}

    def compute(self, inputs: dict) -> dict:
        tickers = inputs["tickers"]

        if not tickers:
            return {"per_ticker": {}, "matrix": {}, "tickers": [], "averages": {},
                    "strongest": {}, "weakest": {}, "hub": {}}

        result = get_correlation_matrix(tickers)
        # per_ticker = average correlation for each ticker (for the table column)
        result["per_ticker"] = result.get("averages", {})
        return result

    def render_cell(self, ticker: str, value) -> str:
        """A filled bar + ρ pill, using the frontend's shared <Bar> component.
        `value` clamps to [0, 1] on the frontend, so it's passed through as-is."""
        if value is None:
            return "—"
        label = "1.00" if value >= 0.995 else f"{value:.2f}".replace("0.", ".")
        return f'<Bar value={{{value}}} label="{label}" />'
