"""Market Cap measurement — each holding's own market capitalisation,
read straight from its metadata record (issue #109)."""

from measurements.base import MeasurementBase
from measurements.inputs.holdings import get_holdings
from measurements.inputs.stock_info import get_stock_info

_NO_CAP_REASON = "no market cap on record for this ticker"


class MarketCapMeasurement(MeasurementBase):
    id = "market_cap"
    name = "Market Cap"
    description = (
        "Each holding's own market capitalisation, from its stock_info "
        "metadata record - the same figure the holding's own popup shows, "
        "now readable across the whole fund at once."
    )
    route = "/measurements/market-cap/{etf_id}"
    uses_inputs = ["holdings", "stock_info"]

    column_key = "market_cap"
    column_label = "MARKET CAP"
    column_width = 120
    default_enabled = False

    filterable = True
    filter_type = "choices"
    filter_options = [
        {"value": 0, "label": "Any cap"},
        {"value": 10, "label": "≥ $10B"},
        {"value": 50, "label": "≥ $50B"},
        {"value": 200, "label": "≥ $200B"},
        {"value": 500, "label": "≥ $500B"},
    ]

    sort_type = "numerical"

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {"type": "Record<string, number>", "description": "Ticker → market cap in billions USD"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet for display, e.g. <Stat text=\"$61.8B\" />"},
        "per_ticker_reason": {"type": "Record<string, string>", "description": "Ticker → why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        info = get_stock_info(tickers)
        return {"tickers": tickers, "info": info}

    def compute(self, inputs: dict) -> dict:
        per_ticker = {}
        per_ticker_reason = {}

        for ticker in inputs["tickers"]:
            cap = inputs["info"].get(ticker, {}).get("marketCap")
            if not cap:
                per_ticker[ticker] = None
                per_ticker_reason[ticker] = _NO_CAP_REASON
                continue
            per_ticker[ticker] = round(cap / 1_000_000_000, 2)

        return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        # Mirrors value_held.py's own $/B/T thresholds, so a market cap and
        # a value-held figure read the same way (issue #109's own
        # acceptance criterion).
        if value >= 1000:
            text = f"${value / 1000:.2f}T"
        elif value >= 1:
            text = f"${value:.1f}B"
        else:
            text = f"${round(value * 1000)}M"
        return f'<Stat text="{text}" />'
