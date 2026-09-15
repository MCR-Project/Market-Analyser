"""Portfolio metric: gain (issue #104)."""

from portfolio_metrics.base import RunMetric


class GainMetric(RunMetric):
    id = "gain"
    name = "Gain"
    description = "What the portfolio actually made — final value less everything paid into it."
    family = "account"
    format = "currency_signed"
    formula = "finalValue − totalInvested"
    null_rule = "Never null."
