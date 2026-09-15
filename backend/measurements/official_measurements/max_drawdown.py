"""Max drawdown measurement — the deepest fall from a prior peak in a
holding's own price history over the table's shared window (issue #108)."""

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS
from measurements.base import MeasurementBase
from measurements.inputs.holdings import get_holdings
from measurements.inputs.price_frame import get_price_frame
from services.stats import max_drawdown

_TOO_SHORT_REASON = "fewer than two priced dates over this window"


class MaxDrawdownMeasurement(MeasurementBase):
    id = "max_drawdown"
    name = "Max Drawdown"
    description = (
        "The deepest fall from a prior peak in the holding's own price "
        "history over the window - negative or zero, never positive. A "
        "holding that never fell below a prior peak in the window reports "
        "0%, a real answer, not a missing one."
    )
    route = "/measurements/max-drawdown/{etf_id}"
    uses_inputs = ["holdings", "price_frame"]

    column_key = "max_drawdown"
    column_label = "MAX DRAWDOWN"
    column_width = 130
    default_enabled = False

    filterable = True
    filter_type = "range"
    filter_min = -100
    filter_max = 0
    filter_step = 1

    sort_type = "numerical"

    window_options = MEASUREMENT_WINDOW_OPTIONS
    window_default = MEASUREMENT_WINDOW_DEFAULT

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {"type": "Record<string, number>", "description": "Ticker → deepest peak-to-trough fall over the window, % (≤ 0)"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet, e.g. <Stat text=\"-23.4%\" />"},
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
            per_ticker[ticker] = max_drawdown(values, dates)["value"]
        return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        color = "var(--negative)" if value < 0 else "var(--fg)"
        return f'<Stat text="{value:.1f}%" color="{color}" />'
