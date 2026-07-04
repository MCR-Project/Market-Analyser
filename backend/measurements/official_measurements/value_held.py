"""
Value Held measurement — dollar value of each holding within the ETF.
"""

from measurements.base import MeasurementBase
from measurements.inputs.holdings import get_holdings
from measurements.inputs.etf_info import get_etf_info


class ValueHeldMeasurement(MeasurementBase):
    id = "value_held"
    name = "Value Held"
    description = "Estimated market value of each holding based on fund AUM and weight"
    route = "/measurements/value-held/{etf_id}"

    # Table column
    column_key = "value_b"
    column_label = "VALUE"
    column_width = 110
    default_enabled = True

    # Filter: dropdown choices for minimum value
    filterable = True
    filter_type = "choices"
    filter_options = [
        {"value": 0, "label": "Any value"},
        {"value": 1, "label": "≥ $1B"},
        {"value": 5, "label": "≥ $5B"},
        {"value": 10, "label": "≥ $10B"},
        {"value": 20, "label": "≥ $20B"},
    ]

    # Sort: plain numeric comparison of dollar value
    sort_type = "numerical"

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker":     {"type": "Record<string, number>", "description": "Ticker → value in billions USD"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet for display, e.g. <Stat text=\"$61.8B\" />"},
    }

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        info = get_etf_info(etf_id)
        holdings = get_holdings(etf_id)
        return {"aum": info["aum"], "holdings": holdings}

    def compute(self, inputs: dict) -> dict:
        aum = inputs["aum"]
        per_ticker = {ticker: round(aum * weight / 100, 2) for ticker, weight in inputs["holdings"]}

        return {
            "per_ticker": per_ticker,
            "aum": aum,
        }

    def render_cell(self, ticker: str, value) -> str:
        if value is None:
            return "—"
        # Mirrors the frontend's old fmtMoney(): $/B/T thresholds.
        if value >= 1000:
            text = f"${value / 1000:.2f}T"
        elif value >= 1:
            text = f"${value:.1f}B"
        else:
            text = f"${round(value * 1000)}M"
        return f'<Stat text="{text}" />'
