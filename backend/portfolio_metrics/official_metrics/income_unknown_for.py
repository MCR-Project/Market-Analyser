"""Portfolio metric: income unknown for (issue #104)."""

from portfolio_metrics.base import RunMetric


class IncomeUnknownForMetric(RunMetric):
    id = "incomeUnknownFor"
    name = "Income Unknown For"
    description = (
        "Holdings the `dividends` table has no record of — every ETF, and anything "
        "resolved outside the tracked universe — named rather than silently folded "
        "into dividendIncome as if they paid nothing."
    )
    family = "dividend"
    tile = False
    default_enabled = True
    format = "list"
    formula = "[ticker for ticker in holdings if ticker not in tracked_tickers(holdings)] — a list, not a number"
    null_rule = "Never null; an empty list when every holding's dividend history is on record."
