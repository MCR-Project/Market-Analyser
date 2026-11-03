"""Ownership measurement — held % insiders and held % institutions, each
holding's own, straight from its fundamentals record (issue #194)."""

from measurements.base import MeasurementBase
from measurements.inputs.fundamentals import get_fundamentals
from measurements.inputs.holdings import get_holdings

_NO_INSIDERS_REASON = "no insider ownership on record for this ticker"
_NO_INSTITUTIONS_REASON = "no institutional ownership on record for this ticker"


class OwnershipMeasurement(MeasurementBase):
    id = "ownership"
    name = "Ownership"
    description = (
        "Each holding's own share held by insiders and by institutions. "
        "Null for a holding Yahoo reports neither for (an ETF held inside "
        "another ETF, a security type .info doesn't cover ownership for)."
    )
    route = "/measurements/ownership/{etf_id}"
    uses_inputs = ["holdings", "fundamentals"]

    columns = [
        {
            "key": "held_percent_insiders", "label": "% INSIDERS", "width": 100, "default_enabled": False,
            "filterable": True, "filter_type": "range", "filter_options": [],
            "filter_min": 0, "filter_max": 100, "filter_step": 1,
            "sort_type": "numerical", "sort_order": [],
        },
        {
            "key": "held_percent_institutions", "label": "% INSTITUTIONS", "width": 125, "default_enabled": False,
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
            "description": "column key ('held_percent_insiders'|'held_percent_institutions') → ticker → value",
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
        per_ticker = {"held_percent_insiders": {}, "held_percent_institutions": {}}
        per_ticker_reason = {"held_percent_insiders": {}, "held_percent_institutions": {}}

        for ticker in inputs["tickers"]:
            data = inputs["fundamentals"].get(ticker, {})

            insiders = data.get("heldPercentInsiders")
            if insiders is None:
                per_ticker["held_percent_insiders"][ticker] = None
                per_ticker_reason["held_percent_insiders"][ticker] = _NO_INSIDERS_REASON
            else:
                per_ticker["held_percent_insiders"][ticker] = round(insiders * 100, 2)

            institutions = data.get("heldPercentInstitutions")
            if institutions is None:
                per_ticker["held_percent_institutions"][ticker] = None
                per_ticker_reason["held_percent_institutions"][ticker] = _NO_INSTITUTIONS_REASON
            else:
                per_ticker["held_percent_institutions"][ticker] = round(institutions * 100, 2)

        return {
            "per_ticker": per_ticker,
            "per_ticker_reason": {k: v for k, v in per_ticker_reason.items() if v},
        }

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        return f'<Stat text="{value:.1f}%" />'
