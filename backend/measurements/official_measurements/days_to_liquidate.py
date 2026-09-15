"""Days to Liquidate measurement — how many normal trading days it would
take to sell a fund's full position in a holding, at that holding's own
average daily dollar volume (issue #111)."""

from measurements.base import MeasurementBase
from measurements.inputs.etf_info import get_etf_info
from measurements.inputs.holdings import get_holdings
from measurements.inputs.price_frame import get_price_frame
from services.stats import average_bucketed_daily_value

_NO_VOLUME_REASON = "no prices rows for this holding - every ETF, and anything resolved outside the tracked universe"
_TOO_SHORT_REASON = "fewer than two priced dates with volume on record over this window"


class DaysToLiquidateMeasurement(MeasurementBase):
    id = "days_to_liquidate"
    name = "Days to Liquidate"
    description = (
        "How many normal trading days it would take to sell the fund's "
        "entire position in a holding, at that holding's own average "
        "daily dollar volume - value held divided by average daily "
        "dollar volume (close x volume)."
    )
    route = "/measurements/days-to-liquidate/{etf_id}"
    uses_inputs = ["holdings", "etf_info", "price_frame"]

    column_key = "days_to_liquidate"
    column_label = "DAYS TO LIQUIDATE"
    column_width = 160
    default_enabled = False

    filterable = True
    filter_type = "range"
    filter_min = 0
    filter_max = 30
    filter_step = 1

    sort_type = "numerical"

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {"type": "Record<string, number>", "description": "Ticker → trading days to liquidate the fund's full position"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet for display, e.g. <Stat text=\"3.2d\" />"},
        "per_ticker_reason": {"type": "Record<string, string>", "description": "Ticker → why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        info = get_etf_info(etf_id)
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        # The bulk, volume-widened read (issue #102) - one query for the
        # whole basket rather than a call per holding, exactly what this
        # column needs `prices.volume` for and nothing else in the table
        # reads it for yet.
        frame = get_price_frame(tickers, include_volume=True)
        return {"aum": info["aum"], "holdings": holdings, "frame": frame}

    def compute(self, inputs: dict) -> dict:
        aum = inputs["aum"]
        per_ticker = {}
        per_ticker_reason = {}

        for ticker, weight in inputs["holdings"]:
            entry = inputs["frame"].get(ticker)
            volume_rows = entry.get("volume") if entry else None
            if not volume_rows:
                per_ticker[ticker] = None
                per_ticker_reason[ticker] = _NO_VOLUME_REASON
                continue

            closes_by_date = dict(entry["closes"])
            # Each row's own bucket dollar volume - close x volume, still
            # a whole bucket's sum rather than one day's at this point.
            dollar_volumes = [
                (row["date"], closes_by_date[row["date"]] * row["volume"])
                for row in volume_rows
                if row["date"] in closes_by_date
            ]
            avg_daily_dollar_volume = average_bucketed_daily_value(dollar_volumes)

            if avg_daily_dollar_volume is None or avg_daily_dollar_volume <= 0:
                per_ticker[ticker] = None
                per_ticker_reason[ticker] = _TOO_SHORT_REASON
                continue

            # Value held reuses value_held.py's own arithmetic exactly
            # (fund AUM, in billions, times weight) so the two columns can
            # never disagree - converted to raw dollars here so the ratio
            # against a raw-dollar daily volume comes out in plain days.
            value_held = aum * 1_000_000_000 * weight / 100
            per_ticker[ticker] = round(value_held / avg_daily_dollar_volume, 2)

        return {"per_ticker": per_ticker, "per_ticker_reason": per_ticker_reason}

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        return f'<Stat text="{value:.1f}d" />'
