"""Risk contribution measurement — each holding's own share of the
fund's variance (issue #107)."""

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS
from measurements.base import MeasurementBase
from measurements.inputs.holdings import get_holdings
from measurements.inputs.price_frame import get_aligned_closes
from services.stats import risk_contribution

_TOO_FEW_HOLDINGS_REASON = "fewer than two of the fund's holdings have a complete price history over this window"
_NO_VARIANCE_REASON = "no measurable variance to apportion across this window's holdings"


class RiskContributionMeasurement(MeasurementBase):
    id = "risk_contribution"
    name = "Risk Contribution"
    description = (
        "Each holding's own share of the fund's total variance - weight "
        "times its marginal contribution to variance, over the fund's "
        "own variance. Sums to 100% across the fund, but answers a "
        "different question than weight does: a volatile holding closely "
        "correlated with the rest of the fund can drive far more of its "
        "risk than its dollar weight suggests, and one that moves "
        "opposite the rest of the fund can contribute less than zero."
    )
    route = "/measurements/risk-contribution/{etf_id}"
    uses_inputs = ["holdings", "price_frame"]

    # Table column
    column_key = "risk_contribution"
    column_label = "RISK CONTRIB."
    column_width = 130
    default_enabled = False

    # Filter: range slider - a holding can contribute negative risk
    filterable = True
    filter_type = "range"
    filter_min = -10
    filter_max = 30
    filter_step = 1

    sort_type = "numerical"

    window_options = MEASUREMENT_WINDOW_OPTIONS
    window_default = MEASUREMENT_WINDOW_DEFAULT

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {"type": "Record<string, number>", "description": "Ticker → % share of the fund's variance, summing to 100 across the fund"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet, e.g. <Stat text=\"12.4%\" />"},
        "per_ticker_reason": {"type": "Record<string, string>", "description": "Ticker → why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, window: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        weights = {t: w for t, w in holdings}
        dates, values_by_ticker = get_aligned_closes(tickers, period=window)
        return {"tickers": tickers, "weights": weights, "dates": dates, "values_by_ticker": values_by_ticker}

    def compute(self, inputs: dict) -> dict:
        tickers = inputs["tickers"]
        dates = inputs["dates"]
        values_by_ticker = inputs["values_by_ticker"]

        if len(values_by_ticker) < 2:
            return {
                "per_ticker": {t: None for t in tickers},
                "per_ticker_reason": {t: _TOO_FEW_HOLDINGS_REASON for t in tickers},
            }

        weights = {t: inputs["weights"].get(t, 0.0) for t in values_by_ticker}
        contributions = risk_contribution(values_by_ticker, dates, weights)

        per_ticker = {t: contributions.get(t) for t in tickers}
        per_ticker_reason = {}
        for t in tickers:
            if per_ticker[t] is not None:
                continue
            per_ticker_reason[t] = (
                _NO_VARIANCE_REASON if t in values_by_ticker else _TOO_FEW_HOLDINGS_REASON
            )
        return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        color = "var(--negative)" if value < 0 else "var(--fg)"
        return f'<Stat text="{value:.1f}%" color="{color}" />'
