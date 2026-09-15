"""Dividend Yield & Income Share measurement — trailing twelve-month
declared dividends against a holding's own last close, and how much of
its total return over the same stretch came from being paid rather than
from the price moving (issue #109)."""

from measurements.base import MeasurementBase
from measurements.inputs.dividend_events import get_dividend_events
from measurements.inputs.holdings import get_holdings
from measurements.inputs.price_frame import get_price_frame
from services.stats import PERCENT_DP

_TOO_SHORT_REASON = "fewer than two priced dates over the trailing twelve months"
_UNTRACKED_REASON = "the dividends table has no record of this holding - every ETF, and anything resolved live"
_NO_RETURN_REASON = "price change and dividends over the trailing twelve months net to zero, so there is no return to share"


class DividendIncomeMeasurement(MeasurementBase):
    id = "dividend_income"
    name = "Dividend Yield & Income Share"
    description = (
        "Trailing twelve-month declared dividends over a holding's own "
        "last close, and that same income measured against its total "
        "return over the same stretch - how much of what a holding made "
        "came from being paid rather than from its price moving. Amounts "
        "are unadjusted, exactly as the dividends table records them."
    )
    route = "/measurements/dividend-income/{etf_id}"
    uses_inputs = ["holdings", "price_frame", "dividend_events"]

    columns = [
        {
            "key": "dividend_yield", "label": "YIELD", "width": 90, "default_enabled": False,
            "filterable": True, "filter_type": "range", "filter_options": [],
            "filter_min": 0, "filter_max": 10, "filter_step": 0.25,
            "sort_type": "numerical", "sort_order": [],
        },
        {
            "key": "income_share", "label": "INCOME SHARE", "width": 120, "default_enabled": False,
            "filterable": True, "filter_type": "range", "filter_options": [],
            "filter_min": -100, "filter_max": 100, "filter_step": 5,
            "sort_type": "numerical", "sort_order": [],
        },
    ]

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {
            "type": "Record<string, Record<string, number>>",
            "description": "column key ('dividend_yield'|'income_share') → ticker → value",
        },
        "per_ticker_mdx": {"type": "Record<string, Record<string, string>>", "description": "Same shape, MDX snippets"},
        "per_ticker_reason": {"type": "Record<string, Record<string, string>>", "description": "Same shape, why a null value is null"},
    }

    def fetch_inputs(self, etf_id: str, **_) -> dict:
        holdings = get_holdings(etf_id)
        tickers = [h[0] for h in holdings]
        # No window here - the trailing-twelve-month stretch this plugin
        # reads is a fixed part of its own definition (issue #109's
        # "Decisions already settled"), not the shared table-wide window
        # control #108's columns opt into. get_price_frame's own default
        # period is CORRELATION_PERIOD ("1y"), which is exactly that
        # stretch, so this read shares its cache entry with the
        # correlation matrix rather than asking Supabase again.
        frame = get_price_frame(tickers)
        events = get_dividend_events(tickers)
        return {"tickers": tickers, "frame": frame, "events": events}

    def compute(self, inputs: dict) -> dict:
        per_ticker = {"dividend_yield": {}, "income_share": {}}
        per_ticker_reason = {"dividend_yield": {}, "income_share": {}}

        for ticker in inputs["tickers"]:
            event = inputs["events"].get(ticker, {"events": [], "tracked": False})
            if not event["tracked"]:
                per_ticker["dividend_yield"][ticker] = None
                per_ticker["income_share"][ticker] = None
                per_ticker_reason["dividend_yield"][ticker] = _UNTRACKED_REASON
                per_ticker_reason["income_share"][ticker] = _UNTRACKED_REASON
                continue

            entry = inputs["frame"].get(ticker)
            closes = entry["closes"] if entry else []
            if len(closes) < 2:
                per_ticker["dividend_yield"][ticker] = None
                per_ticker["income_share"][ticker] = None
                per_ticker_reason["dividend_yield"][ticker] = _TOO_SHORT_REASON
                per_ticker_reason["income_share"][ticker] = _TOO_SHORT_REASON
                continue

            window_start, first_close = closes[0]
            window_end, last_close = closes[-1]
            trailing_dividends = sum(
                amount for date, amount in event["events"] if window_start <= date <= window_end
            )

            per_ticker["dividend_yield"][ticker] = round(trailing_dividends / last_close * 100, PERCENT_DP)

            total_return = (last_close - first_close) + trailing_dividends
            if total_return == 0:
                per_ticker["income_share"][ticker] = None
                per_ticker_reason["income_share"][ticker] = _NO_RETURN_REASON
            else:
                per_ticker["income_share"][ticker] = round(trailing_dividends / total_return * 100, PERCENT_DP)

        return {
            "per_ticker": per_ticker,
            "per_ticker_reason": {k: v for k, v in per_ticker_reason.items() if v},
        }

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        if value is None:
            return "—"
        if column_key == "dividend_yield":
            return f'<Stat text="{value:.2f}%" />'
        if column_key == "income_share":
            sign = "+" if value >= 0 else "−"
            color = "var(--negative)" if value < 0 else "var(--fg)"
            return f'<Stat text="{sign}{abs(value):.1f}%" color="{color}" />'
        return "—"
