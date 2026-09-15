"""Portfolio metric: contributed (issue #104)."""

from portfolio_metrics.base import RunMetric


class ContributedMetric(RunMetric):
    id = "contributed"
    name = "Contributed"
    description = "The recurring contributions on their own, without the opening lump sum."
    family = "account"
    formula = "Σ contribution.amount, once per period after the window's first row"
    null_rule = "Never null: 0 when there is no recurring contribution, which is the default."
