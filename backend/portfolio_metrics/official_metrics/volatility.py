"""Portfolio metric: volatility (issue #104)."""

from portfolio_metrics.base import RunMetric


class VolatilityMetric(RunMetric):
    id = "volatility"
    name = "Volatility"
    description = "Annualised standard deviation of the run's own returns."
    family = "portfolio"
    format = "percent"
    formula = "stdev(period returns) × √252, each return first scaled by the trading time its own gap covers"
    null_rule = "Null when the window has fewer than two returns — one row of price history is not enough to measure dispersion."
