"""Capture ratio measurement — how much of the fund's own up and down
periods a holding captured (issue #107)."""

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS
from measurements.base import MeasurementBase
from measurements.inputs.fund_index import get_fund_index
from measurements.inputs.holdings import get_holdings
from services.stats import down_capture, up_capture

_NO_FUND_REASON = "fewer than two of the fund's holdings have a complete price history over this window"
_NO_UP_REASON = "the fund had no up period in this window"
_NO_DOWN_REASON = "the fund had no down period in this window"


class CaptureRatioMeasurement(MeasurementBase):
    id = "capture_ratio"
    name = "Upside / Downside Capture"
    description = (
        "How much of the fund's own compounded return a holding captured "
        "over exactly the periods the fund rose, and over exactly the "
        "periods it fell - two different questions a single average "
        "return cannot separate."
    )
    route = "/measurements/capture-ratio/{etf_id}"
    uses_inputs = ["holdings", "price_frame", "fund_index"]

    columns = [
        {
            "key": "up_capture", "label": "UP CAPTURE", "width": 110, "default_enabled": False,
            "filterable": True, "filter_type": "range", "filter_options": [],
            "filter_min": 0, "filter_max": 200, "filter_step": 5,
            "sort_type": "numerical", "sort_order": [],
        },
        {
            "key": "down_capture", "label": "DOWN CAPTURE", "width": 120, "default_enabled": False,
            "filterable": True, "filter_type": "range", "filter_options": [],
            "filter_min": 0, "filter_max": 200, "filter_step": 5,
            "sort_type": "numerical", "sort_order": [],
        },
    ]

    window_options = MEASUREMENT_WINDOW_OPTIONS
    window_default = MEASUREMENT_WINDOW_DEFAULT

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {
            "type": "Record<string, Record<string, number>>",
            "description": "column key ('up_capture'|'down_capture') → ticker → % of the fund's own compounded return over those periods",
        },
        "per_ticker_mdx": {"type": "Record<string, Record<string, string>>", "description": "Same shape, MDX snippets"},
        "per_ticker_reason": {"type": "Record<string, Record<string, string>>", "description": "Same shape, why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, window: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        weights = {t: w for t, w in holdings}
        fund = get_fund_index(tickers, weights, period=window)
        return {"tickers": tickers, "fund": fund}

    def compute(self, inputs: dict) -> dict:
        tickers = inputs["tickers"]
        fund = inputs["fund"]
        dates, values_by_ticker, fund_values = fund["dates"], fund["values_by_ticker"], fund["fund_values"]

        per_ticker = {"up_capture": {}, "down_capture": {}}
        per_ticker_reason = {"up_capture": {}, "down_capture": {}}

        for t in tickers:
            if fund_values is None or t not in values_by_ticker:
                per_ticker["up_capture"][t] = None
                per_ticker["down_capture"][t] = None
                per_ticker_reason["up_capture"][t] = _NO_FUND_REASON
                per_ticker_reason["down_capture"][t] = _NO_FUND_REASON
                continue

            asset_values = values_by_ticker[t]
            up = up_capture(asset_values, fund_values, dates)
            down = down_capture(asset_values, fund_values, dates)
            per_ticker["up_capture"][t] = up["value"]
            per_ticker["down_capture"][t] = down["value"]
            if up["value"] is None:
                per_ticker_reason["up_capture"][t] = _NO_UP_REASON
            if down["value"] is None:
                per_ticker_reason["down_capture"][t] = _NO_DOWN_REASON

        return {
            "per_ticker": per_ticker,
            "per_ticker_reason": {k: v for k, v in per_ticker_reason.items() if v},
        }

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        return f'<Stat text="{value:.0f}%" />'
