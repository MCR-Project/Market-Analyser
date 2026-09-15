"""Portfolio metric: max drawdown (issue #104)."""

from portfolio_metrics.base import RunMetric


class MaxDrawdownMetric(RunMetric):
    id = "maxDrawdown"
    name = "Max Drawdown"
    description = "The deepest fall from a prior peak the portfolio experienced in the window."
    family = "portfolio"
    format = "drawdown"
    formula = "min((unitValue − running peak) / running peak) — a {value, peakDate, troughDate} object, not a bare number"
    null_rule = "Never null: 0% means the portfolio never fell below a prior peak in this window, which is a real answer, not a missing one."
