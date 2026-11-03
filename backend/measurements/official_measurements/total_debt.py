"""Total Debt measurement — each holding's own total debt, from its
fundamentals record (issue #194)."""

from measurements.base import MeasurementBase
from measurements.inputs.fundamentals import get_fundamentals
from measurements.inputs.holdings import get_holdings

_NO_DEBT_REASON = "no total debt on record for this ticker"


class TotalDebtMeasurement(MeasurementBase):
    id = "total_debt"
    name = "Total Debt"
    description = (
        "Each holding's own total debt - short- and long-term borrowings "
        "combined, most recent quarter. Null for a holding Yahoo reports "
        "none for (an ETF held inside another ETF)."
    )
    route = "/measurements/total-debt/{etf_id}"
    uses_inputs = ["holdings", "fundamentals"]

    column_key = "total_debt"
    column_label = "TOTAL DEBT"
    column_width = 110
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
        "per_ticker": {"type": "Record<string, number>", "description": "Ticker → total debt in billions USD"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet for display, e.g. <Stat text=\"$12.3B\" />"},
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
            debt = inputs["fundamentals"].get(ticker, {}).get("totalDebt")
            # debt is None, not falsy (invariant 7): a real, debt-free
            # company's totalDebt is a genuine 0, not an absent figure, and
            # must still show as $0 rather than a dash.
            if debt is None:
                per_ticker[ticker] = None
                per_ticker_reason[ticker] = _NO_DEBT_REASON
                continue
            per_ticker[ticker] = round(debt / 1_000_000_000, 2)

        return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        # Mirrors market_cap.py's own $/B/T thresholds, so a debt figure
        # reads the same way a market cap or a value-held figure does.
        if value >= 1000:
            text = f"${value / 1000:.2f}T"
        elif value >= 1:
            text = f"${value:.1f}B"
        else:
            text = f"${round(value * 1000)}M"
        return f'<Stat text="{text}" />'
