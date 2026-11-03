"""Revenue per Share measurement — each holding's own trailing revenue
divided by its shares outstanding, from its fundamentals record (issue
#194)."""

from measurements.base import MeasurementBase
from measurements.inputs.fundamentals import get_fundamentals
from measurements.inputs.holdings import get_holdings

_NO_REVENUE_REASON = "no revenue per share on record for this ticker"


class RevenuePerShareMeasurement(MeasurementBase):
    id = "revenue_per_share"
    name = "Revenue per Share"
    description = (
        "Each holding's own trailing twelve-month revenue divided by its "
        "shares outstanding. Null for a holding Yahoo reports none for "
        "(an ETF held inside another ETF)."
    )
    route = "/measurements/revenue-per-share/{etf_id}"
    uses_inputs = ["holdings", "fundamentals"]

    column_key = "revenue_per_share"
    column_label = "REVENUE/SHARE"
    column_width = 125
    default_enabled = False

    filterable = True
    filter_type = "range"
    filter_min = 0
    filter_max = 500
    filter_step = 5

    sort_type = "numerical"

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {"type": "Record<string, number>", "description": "Ticker → trailing twelve-month revenue per share, USD"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet for display, e.g. <Stat text=\"$12.34\" />"},
        "per_ticker_reason": {"type": "Record<string, string>", "description": "Ticker → why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        fundamentals = get_fundamentals(tickers)
        return {"tickers": tickers, "fundamentals": fundamentals}

    def compute(self, inputs: dict) -> dict:
        per_ticker = {}
        per_ticker_reason = {}

        for ticker in inputs["tickers"]:
            revenue = inputs["fundamentals"].get(ticker, {}).get("revenuePerShare")
            if revenue is None:
                per_ticker[ticker] = None
                per_ticker_reason[ticker] = _NO_REVENUE_REASON
                continue
            per_ticker[ticker] = round(revenue, 2)

        return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        return f'<Stat text="${value:.2f}" />'
