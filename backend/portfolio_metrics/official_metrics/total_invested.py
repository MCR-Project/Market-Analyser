"""Portfolio metric: total invested (issue #104)."""

from portfolio_metrics.base import RunMetric


class TotalInvestedMetric(RunMetric):
    id = "totalInvested"
    name = "Paid In"
    description = "The opening amount plus every contribution — every dollar that ever went in."
    family = "account"
    formula = "startValue + contributed"
    null_rule = "Never null."
