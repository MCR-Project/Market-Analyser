"""Portfolio metric: dividend yield (issue #104)."""

from portfolio_metrics.base import RunMetric


class DividendYieldMetric(RunMetric):
    id = "dividendYield"
    name = "Dividend Yield"
    description = "Dividend income as a percentage of every dollar paid in."
    family = "dividend"
    tile = False
    default_enabled = True
    format = "percent"
    formula = "dividendIncome / totalInvested × 100"
    null_rule = "Never null for a valid run — totalInvested is validated greater than zero before a simulation starts."
