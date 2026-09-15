"""Portfolio metric: final value (issue #104)."""

from portfolio_metrics.base import RunMetric


class FinalValueMetric(RunMetric):
    id = "finalValue"
    name = "Final Value"
    description = "What the portfolio is worth on the last date of the window."
    family = "portfolio"
    formula = "total[-1] — the portfolio's value on the window's last row"
    null_rule = "Never null: every run that starts has a final value."
