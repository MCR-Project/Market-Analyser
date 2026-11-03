"""P/E Ratio measurement — trailing and forward price/earnings, each
holding's own, straight from its fundamentals record (issue #194)."""

from measurements.base import MeasurementBase
from measurements.inputs.fundamentals import get_fundamentals
from measurements.inputs.holdings import get_holdings

_NO_TRAILING_REASON = "no trailing P/E on record for this ticker"
_NO_FORWARD_REASON = "no forward P/E on record for this ticker"


class PeRatioMeasurement(MeasurementBase):
    id = "pe_ratio"
    name = "P/E Ratio"
    description = (
        "Each holding's own trailing and forward price/earnings ratio - "
        "trailing is price over the last twelve months' earnings, forward "
        "is price over analysts' estimate of the next twelve. Null for a "
        "holding Yahoo reports neither for (an ETF held inside another "
        "ETF, a company with negative or no earnings)."
    )
    route = "/measurements/pe-ratio/{etf_id}"
    uses_inputs = ["holdings", "fundamentals"]

    columns = [
        {
            "key": "trailing_pe", "label": "TRAILING P/E", "width": 110, "default_enabled": False,
            "filterable": True, "filter_type": "range", "filter_options": [],
            "filter_min": 0, "filter_max": 100, "filter_step": 1,
            "sort_type": "numerical", "sort_order": [],
        },
        {
            "key": "forward_pe", "label": "FORWARD P/E", "width": 110, "default_enabled": False,
            "filterable": True, "filter_type": "range", "filter_options": [],
            "filter_min": 0, "filter_max": 100, "filter_step": 1,
            "sort_type": "numerical", "sort_order": [],
        },
    ]

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {
            "type": "Record<string, Record<string, number>>",
            "description": "column key ('trailing_pe'|'forward_pe') → ticker → value",
        },
        "per_ticker_mdx": {"type": "Record<string, Record<string, string>>", "description": "Same shape, MDX snippets"},
        "per_ticker_reason": {"type": "Record<string, Record<string, string>>", "description": "Same shape, why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        fundamentals = get_fundamentals(tickers)
        return {"tickers": tickers, "fundamentals": fundamentals}

    def compute(self, inputs: dict) -> dict:
        per_ticker = {"trailing_pe": {}, "forward_pe": {}}
        per_ticker_reason = {"trailing_pe": {}, "forward_pe": {}}

        for ticker in inputs["tickers"]:
            data = inputs["fundamentals"].get(ticker, {})

            trailing = data.get("trailingPE")
            if trailing is None:
                per_ticker["trailing_pe"][ticker] = None
                per_ticker_reason["trailing_pe"][ticker] = _NO_TRAILING_REASON
            else:
                per_ticker["trailing_pe"][ticker] = round(trailing, 2)

            forward = data.get("forwardPE")
            if forward is None:
                per_ticker["forward_pe"][ticker] = None
                per_ticker_reason["forward_pe"][ticker] = _NO_FORWARD_REASON
            else:
                per_ticker["forward_pe"][ticker] = round(forward, 2)

        return {
            "per_ticker": per_ticker,
            "per_ticker_reason": {k: v for k, v in per_ticker_reason.items() if v},
        }

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        return f'<Stat text="{value:.1f}x" />'
