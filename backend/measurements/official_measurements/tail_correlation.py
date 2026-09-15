"""Tail correlation measurement — how a holding moves with its fund on
the fund's own worst periods, not on an average one (issue #107)."""

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS
from measurements.base import MeasurementBase
from measurements.inputs.fund_index import get_fund_index
from measurements.inputs.holdings import get_holdings
from services.stats import tail_correlation

_NO_FUND_REASON = "fewer than two of the fund's holdings have a complete price history over this window"
_TOO_FEW_TAIL_REASON = "fewer than two periods in the fund's worst decile over this window"


class TailCorrelationMeasurement(MeasurementBase):
    id = "tail_correlation"
    name = "Tail Correlation"
    description = (
        "Correlation to the fund computed only over the fund's own worst "
        "decile of periods by return - whether a holding still moves "
        "with the fund on the days that hurt, not on an average one. An "
        "ordinary correlation can hide a relationship that comes apart "
        "exactly when it would matter most."
    )
    route = "/measurements/tail-correlation/{etf_id}"
    uses_inputs = ["holdings", "price_frame", "fund_index"]

    column_key = "tail_correlation"
    column_label = "TAIL ρ"
    column_width = 200
    default_enabled = False

    filterable = True
    filter_type = "range"
    filter_min = -1
    filter_max = 1
    filter_step = 0.05

    sort_type = "numerical"

    window_options = MEASUREMENT_WINDOW_OPTIONS
    window_default = MEASUREMENT_WINDOW_DEFAULT

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {"type": "Record<string, number>", "description": "Ticker → ρ over the fund's worst decile of periods, -1 to 1"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet, e.g. <Bar value={0.62} label=\".62\" />"},
        "per_ticker_reason": {"type": "Record<string, string>", "description": "Ticker → why a null value is null"},
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

        per_ticker, per_ticker_reason = {}, {}
        for t in tickers:
            if fund_values is None or t not in values_by_ticker:
                per_ticker[t] = None
                per_ticker_reason[t] = _NO_FUND_REASON
                continue
            result = tail_correlation(values_by_ticker[t], fund_values, dates)
            per_ticker[t] = result["value"]
            if result["value"] is None:
                per_ticker_reason[t] = _TOO_FEW_TAIL_REASON

        return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        label = "1.00" if value >= 0.995 else f"{value:.2f}".replace("0.", ".")
        return f'<Bar value={{{value}}} label="{label}" />'
