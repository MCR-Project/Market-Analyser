"""
ETF Weight measurement — percentage weight of each holding in the fund.
"""

from measurements.base import MeasurementBase
from measurements.inputs.holdings import get_holdings


class EtfWeightMeasurement(MeasurementBase):
    id = "etf_weight"
    name = "% of ETF"
    description = "Weight of each holding as a percentage of the fund's portfolio"
    route = "/measurements/etf-weight/{etf_id}"
    uses_inputs = ["holdings"]

    # Table column
    column_key = "weight"
    column_label = "% OF ETF"
    column_width = 90
    default_enabled = True

    # Filter: dropdown choices for minimum weight
    filterable = True
    filter_type = "choices"
    filter_options = [
        {"value": 0, "label": "Any %"},
        {"value": 0.5, "label": "≥ 0.5%"},
        {"value": 1, "label": "≥ 1%"},
        {"value": 2, "label": "≥ 2%"},
        {"value": 3, "label": "≥ 3%"},
    ]

    # Sort: plain numeric comparison of weight %
    sort_type = "numerical"

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker":     {"type": "Record<string, number>", "description": "Ticker → weight %"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet for display, e.g. <Stat text=\"7.9%\" />"},
    }

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        return {"holdings": get_holdings(etf_id)}

    def compute(self, inputs: dict) -> dict:
        holdings = inputs["holdings"]
        per_ticker = {ticker: round(weight, 2) for ticker, weight in holdings}

        return {
            "per_ticker": per_ticker,
            "total_weight": round(sum(h[1] for h in holdings), 2),
        }

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        return f'<Stat text="{value:.1f}%" />'
