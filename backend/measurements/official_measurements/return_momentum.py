"""1Y Return & Momentum measurement — a holding's own total return over
the table's shared window, and that same return with the final month
skipped (issue #108)."""

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS
from measurements.base import MeasurementBase
from measurements.inputs.holdings import get_holdings
from measurements.inputs.price_frame import get_price_frame
from services.stats import momentum as compute_momentum
from services.stats import total_return

_TOO_SHORT_REASON = "fewer than two priced dates over this window"
_NO_SKIPPABLE_MONTH_REASON = "the window itself spans less than a month, so there is no prior month to measure to"


class ReturnMomentumMeasurement(MeasurementBase):
    id = "return_momentum"
    name = "1Y Return & Momentum"
    description = (
        "Total return over the window, on adjusted closes so income is "
        "already inside it - and that same return with the most recent "
        "month skipped. The skip is deliberate: a very recent month tends "
        "to mean-revert, and leaving it out is what keeps momentum from "
        "just restating the return column."
    )
    route = "/measurements/return-momentum/{etf_id}"
    uses_inputs = ["holdings", "price_frame"]

    columns = [
        {
            "key": "total_return", "label": "RETURN", "width": 100, "default_enabled": False,
            "filterable": True, "filter_type": "range", "filter_options": [],
            "filter_min": -50, "filter_max": 100, "filter_step": 5,
            "sort_type": "numerical", "sort_order": [],
        },
        {
            "key": "momentum", "label": "MOMENTUM", "width": 110, "default_enabled": False,
            "filterable": True, "filter_type": "range", "filter_options": [],
            "filter_min": -50, "filter_max": 100, "filter_step": 5,
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
            "description": "column key ('total_return'|'momentum') → ticker → % return",
        },
        "per_ticker_mdx": {"type": "Record<string, Record<string, string>>", "description": "Same shape, MDX snippets"},
        "per_ticker_reason": {"type": "Record<string, Record<string, string>>", "description": "Same shape, why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, window: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        frame = get_price_frame(tickers, period=window)
        return {"tickers": tickers, "frame": frame}

    def compute(self, inputs: dict) -> dict:
        per_ticker = {"total_return": {}, "momentum": {}}
        per_ticker_reason = {"total_return": {}, "momentum": {}}

        for ticker in inputs["tickers"]:
            entry = inputs["frame"].get(ticker)
            closes = entry["closes"] if entry else []
            if len(closes) < 2:
                per_ticker["total_return"][ticker] = None
                per_ticker["momentum"][ticker] = None
                per_ticker_reason["total_return"][ticker] = _TOO_SHORT_REASON
                per_ticker_reason["momentum"][ticker] = _TOO_SHORT_REASON
                continue

            dates = [row[0] for row in closes]
            values = [row[1] for row in closes]

            ret = total_return(values)
            per_ticker["total_return"][ticker] = ret
            if ret is None:
                per_ticker_reason["total_return"][ticker] = _TOO_SHORT_REASON

            mom = compute_momentum(values, dates)
            per_ticker["momentum"][ticker] = mom["value"]
            if mom["value"] is None:
                per_ticker_reason["momentum"][ticker] = _NO_SKIPPABLE_MONTH_REASON

        return {
            "per_ticker": per_ticker,
            "per_ticker_reason": {k: v for k, v in per_ticker_reason.items() if v},
        }

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        sign = "+" if value >= 0 else "−"
        color = "var(--negative)" if value < 0 else "var(--fg)"
        return f'<Stat text="{sign}{abs(value):.1f}%" color="{color}" />'
