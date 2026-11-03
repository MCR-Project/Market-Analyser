"""Earnings Quarterly Growth measurement — each holding's own year-over-year
growth in its most recent quarter's earnings, from its fundamentals record
(issue #194)."""

from measurements.base import MeasurementBase
from measurements.inputs.fundamentals import get_fundamentals
from measurements.inputs.holdings import get_holdings

_NO_GROWTH_REASON = "no earnings quarterly growth on record for this ticker"


class EarningsQuarterlyGrowthMeasurement(MeasurementBase):
    id = "earnings_quarterly_growth"
    name = "Earnings Quarterly Growth"
    description = (
        "Each holding's own year-over-year growth in its most recent "
        "quarter's earnings, against the same quarter a year earlier. "
        "Null for a holding Yahoo reports none for (an ETF held inside "
        "another ETF, a company with no comparable prior-year quarter)."
    )
    route = "/measurements/earnings-quarterly-growth/{etf_id}"
    uses_inputs = ["holdings", "fundamentals"]

    column_key = "earnings_quarterly_growth"
    column_label = "EARNINGS GROWTH"
    column_width = 130
    default_enabled = False

    filterable = True
    filter_type = "range"
    filter_min = -100
    filter_max = 200
    filter_step = 5

    sort_type = "numerical"

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {"type": "Record<string, number>", "description": "Ticker → year-over-year quarterly earnings growth, percent"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet for display, e.g. <Stat text=\"+12.3%\" />"},
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
            growth = inputs["fundamentals"].get(ticker, {}).get("earningsQuarterlyGrowth")
            if growth is None:
                per_ticker[ticker] = None
                per_ticker_reason[ticker] = _NO_GROWTH_REASON
                continue
            per_ticker[ticker] = round(growth * 100, 2)

        return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        sign = "+" if value >= 0 else "−"
        color = "var(--negative)" if value < 0 else "var(--fg)"
        return f'<Stat text="{sign}{abs(value):.1f}%" color="{color}" />'
