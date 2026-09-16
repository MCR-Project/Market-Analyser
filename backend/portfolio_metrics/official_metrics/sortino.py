"""Portfolio metric: Sortino ratio (issue #112)."""

from portfolio_metrics.base import RunMetric


class SortinoMetric(RunMetric):
    id = "sortino"
    name = "Sortino Ratio"
    description = (
        "Sharpe's sibling: the same annualised mean excess return, divided by annualised "
        "downside deviation instead of total volatility, so a run is not penalised for moving up."
    )
    family = "portfolio"
    format = "ratio"
    default_enabled = False
    formula = "(annualised mean of period returns − risk-free rate) / downside deviation"
    null_rule = (
        "Null when no risk-free rate is available for this window and no override was given, "
        "or when the window has fewer than two period returns, or none fell short of the "
        "target to measure a downside deviation from."
    )
