"""Cap-Weight Tilt measurement — how far a holding's actual fund weight
sits from the weight a passive, cap-weighted basket of the same tracked
holdings would have given it (issue #109)."""

from measurements.base import MeasurementBase
from measurements.inputs.holdings import get_holdings
from measurements.inputs.stock_info import get_stock_info
from services.stats import PERCENT_DP

_NO_CAP_REASON = "no market cap on record for this ticker"
_NO_TRACKED_CAP_REASON = "no tracked holding in this fund has a market cap on record"


class CapWeightTiltMeasurement(MeasurementBase):
    id = "cap_weight_tilt"
    name = "Cap-Weight Tilt"
    description = (
        "A holding's fund weight less the weight a passive, cap-weighted "
        "basket of the same tracked holdings would have given it - where "
        "the fund is deliberately overweight or underweight a plain "
        "market-cap ranking, rather than merely following it."
    )
    route = "/measurements/cap-weight-tilt/{etf_id}"
    uses_inputs = ["holdings", "stock_info"]

    column_key = "cap_weight_tilt"
    column_label = "TILT"
    column_width = 90
    default_enabled = False

    filterable = True
    filter_type = "range"
    filter_options = []
    filter_min = -10
    filter_max = 10
    filter_step = 0.5

    sort_type = "numerical"

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {"type": "Record<string, number>", "description": "Ticker → fund weight less cap weight, percentage points"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet for display"},
        "per_ticker_reason": {"type": "Record<string, string>", "description": "Ticker → why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        info = get_stock_info(tickers)
        return {"holdings": holdings, "info": info}

    def compute(self, inputs: dict) -> dict:
        holdings = inputs["holdings"]
        info = inputs["info"]

        # Only the holdings this fund's own table tracks (>=1% weight -
        # measurements.inputs.holdings' own docstring states this) ever
        # reach this plugin at all, so that is necessarily the tracked set
        # the denominator sums over - there is no fuller basket to compare
        # against.
        caps = {ticker: info.get(ticker, {}).get("marketCap") for ticker, _ in holdings}
        total_cap = sum(cap for cap in caps.values() if cap)

        per_ticker = {}
        per_ticker_reason = {}

        if not total_cap:
            for ticker, _ in holdings:
                per_ticker[ticker] = None
                per_ticker_reason[ticker] = _NO_TRACKED_CAP_REASON
            return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

        for ticker, weight in holdings:
            cap = caps.get(ticker)
            if not cap:
                per_ticker[ticker] = None
                per_ticker_reason[ticker] = _NO_CAP_REASON
                continue
            cap_weight = cap / total_cap * 100
            per_ticker[ticker] = round(weight - cap_weight, PERCENT_DP)

        return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        sign = "+" if value >= 0 else "−"
        color = "var(--negative)" if value < 0 else "var(--fg)"
        return f'<Stat text="{sign}{abs(value):.1f}pp" color="{color}" />'
