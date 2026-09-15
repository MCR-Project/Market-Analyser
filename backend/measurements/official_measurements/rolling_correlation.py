"""Rolling Correlation measurement — a holding's Pearson correlation to
its fund's own weighted return, computed over consecutive rolling blocks
rather than once across the whole window (issue #110)."""

from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS, MIN_OVERLAPPING_RETURNS
from measurements.base import MeasurementBase
from measurements.inputs.fund_index import get_fund_index
from measurements.inputs.holdings import get_holdings
from services.stats import rolling_correlation as compute_rolling_correlation

# Paired returns per block, not days - reuses issue #97's own bar for "how
# many returns before a correlation is more than noise" (about six trading
# weeks) as "how long one rolling reading should span", rather than a
# second, unexplained number meaning almost the same thing.
ROLLING_PERIODS = MIN_OVERLAPPING_RETURNS

_NO_FUND_REASON = "fewer than two of the fund's holdings have a complete price history over this window"
_TOO_SHORT_REASON = (
    f"fewer than two rolling blocks of {ROLLING_PERIODS} paired returns each over this window, "
    "or the earliest or latest block had no variance to correlate"
)


class RollingCorrelationMeasurement(MeasurementBase):
    id = "rolling_correlation"
    name = "Correlation to Fund (Rolling)"
    description = (
        "A holding's correlation to its fund's own weighted return, "
        "computed over consecutive rolling blocks of returns rather than "
        "once across the whole window - the path this relationship "
        "actually took, not the single number an average of it collapses "
        "to. A holding whose correlation climbed all year and one whose "
        "fell away can report the same average and be opposite findings."
    )
    route = "/measurements/rolling-correlation/{etf_id}"
    uses_inputs = ["holdings", "price_frame", "fund_index"]

    column_key = "rolling_correlation"
    column_label = "ρ TREND"
    column_width = 140
    default_enabled = False

    filterable = True
    filter_type = "range"
    filter_min = -1
    filter_max = 1
    filter_step = 0.1

    sort_type = "numerical"

    window_options = MEASUREMENT_WINDOW_OPTIONS
    window_default = MEASUREMENT_WINDOW_DEFAULT

    input_schema = {
        "etf_id": {"type": "string", "required": True, "description": "ETF ticker symbol"},
    }
    output_schema = {
        "per_ticker": {"type": "Record<string, number>", "description": "Ticker → change in rolling ρ, last block less first, -2 to 2"},
        "per_ticker_mdx": {"type": "Record<string, string>", "description": "Ticker → MDX snippet, a <Spark> of the rolling ρ series"},
        "per_ticker_reason": {"type": "Record<string, string>", "description": "Ticker → why a null value is null"},
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
        dates, values_by_ticker, fund_values = fund["dates"], fund["values_by_ticker"], fund["fund_values"]

        per_ticker, per_ticker_reason, series_by_ticker = {}, {}, {}
        for t in tickers:
            if fund_values is None or t not in values_by_ticker:
                per_ticker[t] = None
                per_ticker_reason[t] = _NO_FUND_REASON
                continue
            result = compute_rolling_correlation(values_by_ticker[t], fund_values, dates, ROLLING_PERIODS)
            per_ticker[t] = result["change"]
            series_by_ticker[t] = result["series"]
            if result["change"] is None:
                per_ticker_reason[t] = _TOO_SHORT_REASON

        return {
            "per_ticker": per_ticker,
            "per_ticker_reason": per_ticker_reason,
            # Private to this plugin - the raw per-block ρ series render_cell
            # alone has no way to see (it receives only per_ticker's own
            # scalar, the same as every other column - see backend/
            # measurements/CLAUDE.md's "Spark: a path, not a level"). run()
            # is overridden below to read this back out and pop it before
            # the response ever leaves the plugin, since it is not part of
            # this measurement's documented output_schema.
            "_rolling_series": series_by_ticker,
        }

    def render_cell(self, ticker: str, value, column_key: str) -> str:
        """The ABC-required implementation, and the actual rendering used
        when only the scalar is available (called in isolation, with no
        series). `run()` below calls the same `_render` with the real
        per-block series once it has one, which is what the table and a
        doc page's worked example actually show - see that override."""
        return self._render(value, None)

    def _render(self, value, series) -> str:
        if value is None:
            return "—"
        color = "var(--negative)" if value < 0 else "var(--accent)"
        usable = [v for v in series if v is not None] if series else None
        # A real series draws the true path; without one (render_cell
        # called on its own) the only honest fallback is the two points
        # the change itself is built from - a slope from "before" to
        # "the change", not a fabricated shape.
        points = usable if usable and len(usable) >= 2 else [0, value]
        label = (
            f"correlation to the fund {'rose' if value >= 0 else 'fell'} "
            f"{abs(value):.2f} across the window's rolling {ROLLING_PERIODS}-return blocks"
        )
        literal = "[" + ", ".join(repr(v) for v in points) + "]"
        return f'<Spark values={{{literal}}} baseline={{0}} label="{label}" color="{color}" />'

    def run(self, **params) -> dict:
        """Identical to MeasurementBase.run() in every way that matters -
        window resolution, null-reason filtering - except for the one
        thing this column needs that no other column does: `per_ticker_mdx`
        has to be built from the *series* `compute()` worked out, not from
        `per_ticker`'s own scalar alone, since a <Spark> cell draws a path
        and the base class's generic dispatch only ever hands render_cell
        that one scalar (deliberately - see backend/measurements/CLAUDE.md's
        "Spark: a path, not a level"). Calling the base implementation
        first and then replacing per_ticker_mdx is cheaper to keep correct
        than re-deriving window/reason handling here by hand, and safe:
        `_rolling_series` is a plain local value threaded through return
        values the whole way, never state on `self` a concurrent request
        for a different ETF could stomp on.
        """
        result = super().run(**params)
        series_by_ticker = result.pop("_rolling_series", {})
        result["per_ticker_mdx"] = {
            ticker: self._render(change, series_by_ticker.get(ticker))
            for ticker, change in result["per_ticker"].items()
        }
        return result
