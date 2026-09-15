"""Fund relation measurement — beta, R-squared and idiosyncratic
volatility of each holding against its fund's own weighted return
(issue #107)."""

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS
from measurements.base import MeasurementBase
from measurements.inputs.fund_index import get_fund_index
from measurements.inputs.holdings import get_holdings
from services.stats import beta as compute_beta
from services.stats import idiosyncratic_volatility as compute_idio_vol
from services.stats import r_squared as compute_r_squared

_NO_FUND_REASON = "fewer than two of the fund's holdings have a complete price history over this window"
_TOO_FEW_RETURNS_REASON = "fewer than two paired returns with the fund over this window, or the fund had no variance in it"


class FundRelationMeasurement(MeasurementBase):
    id = "fund_relation"
    name = "Beta / R² / Idiosyncratic Volatility"
    description = (
        "How much of a holding's own movement is explained by the fund "
        "it belongs to, and how much is not. Beta is its sensitivity to "
        "the fund's moves; R-squared is how much of its own variance the "
        "fund's does; idiosyncratic volatility is the annualised part "
        "left over once the fund's own influence is removed."
    )
    route = "/measurements/fund-relation/{etf_id}"
    uses_inputs = ["holdings", "price_frame", "fund_index"]

    columns = [
        {
            "key": "beta", "label": "BETA", "width": 90, "default_enabled": False,
            "filterable": True, "filter_type": "range", "filter_options": [],
            "filter_min": -1, "filter_max": 3, "filter_step": 0.1,
            "sort_type": "numerical", "sort_order": [],
        },
        {
            "key": "r_squared", "label": "R²", "width": 80, "default_enabled": False,
            "filterable": True, "filter_type": "range", "filter_options": [],
            "filter_min": 0, "filter_max": 1, "filter_step": 0.05,
            "sort_type": "numerical", "sort_order": [],
        },
        {
            "key": "idio_vol", "label": "IDIO VOL", "width": 100, "default_enabled": False,
            "filterable": False, "filter_type": "none", "filter_options": [],
            "filter_min": 0, "filter_max": 1, "filter_step": 0.01,
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
            "description": "column key ('beta'|'r_squared'|'idio_vol') → ticker → value",
        },
        "per_ticker_mdx": {"type": "Record<string, Record<string, string>>", "description": "Same shape, MDX snippets"},
        "per_ticker_reason": {"type": "Record<string, Record<string, string>>", "description": "Same shape, why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, window: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        weights = {t: w for t, w in holdings}
        fund = get_fund_index(tickers, weights, period=window)
        return {"tickers": tickers, "fund": fund}

    def compute(self, inputs: dict) -> dict:
        tickers = inputs["tickers"]
        fund = inputs["fund"]
        dates = fund["dates"]
        values_by_ticker = fund["values_by_ticker"]
        fund_values = fund["fund_values"]

        per_ticker = {"beta": {}, "r_squared": {}, "idio_vol": {}}
        per_ticker_reason = {"beta": {}, "r_squared": {}, "idio_vol": {}}

        for t in tickers:
            if fund_values is None or t not in values_by_ticker:
                for key in per_ticker:
                    per_ticker[key][t] = None
                    per_ticker_reason[key][t] = _NO_FUND_REASON
                continue

            asset_values = values_by_ticker[t]
            b = compute_beta(asset_values, fund_values, dates)
            r2 = compute_r_squared(asset_values, fund_values, dates)
            # Idiosyncratic volatility reuses this same R² (issue #107's
            # own to-do) rather than letting idiosyncratic_volatility
            # recompute the Pearson correlation underneath it a second
            # time - see that function's own docstring.
            idio = compute_idio_vol(asset_values, fund_values, dates, r_squared_result=r2)

            per_ticker["beta"][t] = b["value"]
            per_ticker["r_squared"][t] = r2["value"]
            per_ticker["idio_vol"][t] = idio["value"]

            if b["value"] is None:
                per_ticker_reason["beta"][t] = _TOO_FEW_RETURNS_REASON
            if r2["value"] is None:
                per_ticker_reason["r_squared"][t] = _TOO_FEW_RETURNS_REASON
            if idio["value"] is None:
                per_ticker_reason["idio_vol"][t] = _TOO_FEW_RETURNS_REASON

        return {
            "per_ticker": per_ticker,
            "per_ticker_reason": {k: v for k, v in per_ticker_reason.items() if v},
        }

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        if column_key == "beta":
            color = "var(--negative)" if value < 0 else "var(--fg)"
            return f'<Stat text="{value:.2f}" color="{color}" />'
        if column_key == "r_squared":
            label = "1.00" if value >= 0.995 else f"{value:.2f}".replace("0.", ".")
            return f'<Bar value={{{value}}} label="{label}" />'
        if column_key == "idio_vol":
            return f'<Stat text="{value:.1f}%" />'
        return "—"
