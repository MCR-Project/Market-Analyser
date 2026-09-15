"""Volatility measurement — annualised standard deviation of a holding's
own returns over the table's shared window (issue #108)."""

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS
from measurements.base import MeasurementBase
from measurements.inputs.holdings import get_holdings
from measurements.inputs.price_frame import get_price_frame
from services.stats import volatility

_TOO_SHORT_REASON = "fewer than two priced dates over this window"


class VolatilityMeasurement(MeasurementBase):
    id = "volatility"
    name = "Volatility"
    description = (
        "Annualised standard deviation of the holding's own returns over "
        "the window - how much it has swung, not which direction. Each "
        "return is scaled by the trading time its own gap covers, so a "
        "window spanning storage tiers is not misreported."
    )
    route = "/measurements/volatility/{etf_id}"
    uses_inputs = ["holdings", "price_frame"]

    column_key = "volatility"
    column_label = "VOLATILITY"
    column_width = 120
    default_enabled = False

    filterable = True
    filter_type = "range"
    filter_min = 0
    filter_max = 100
    filter_step = 1

    sort_type = "numerical"

    window_options = MEASUREMENT_WINDOW_OPTIONS
    window_default = MEASUREMENT_WINDOW_DEFAULT

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {"type": "Record<string, number>", "description": "Ticker → annualised volatility, %"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet, e.g. <Stat text=\"23.4%\" />"},
        "per_ticker_reason": {"type": "Record<string, string>", "description": "Ticker → why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, window: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        frame = get_price_frame(tickers, period=window)
        return {"tickers": tickers, "frame": frame}

    def compute(self, inputs: dict) -> dict:
        per_ticker, per_ticker_reason = {}, {}
        for ticker in inputs["tickers"]:
            entry = inputs["frame"].get(ticker)
            closes = entry["closes"] if entry else []
            if len(closes) < 2:
                per_ticker[ticker] = None
                per_ticker_reason[ticker] = _TOO_SHORT_REASON
                continue
            dates = [row[0] for row in closes]
            values = [row[1] for row in closes]
            result = volatility(values, dates)
            per_ticker[ticker] = result["value"]
            if result["value"] is None:
                per_ticker_reason[ticker] = _TOO_SHORT_REASON
        return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        return f'<Stat text="{value:.1f}%" />'
