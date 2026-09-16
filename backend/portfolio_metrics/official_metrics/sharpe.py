"""Portfolio metric: Sharpe ratio (issue #112)."""

from portfolio_metrics.base import RunMetric


class SharpeMetric(RunMetric):
    id = "sharpe"
    name = "Sharpe Ratio"
    description = (
        "Annualised mean excess return over annualised volatility - the run's own return "
        "per unit of total risk it took to get there, scored against metrics.riskFreeRate."
    )
    family = "portfolio"
    format = "ratio"
    default_enabled = False
    formula = "(annualised mean of period returns − risk-free rate) / volatility"
    null_rule = (
        "Null when no risk-free rate is available for this window and no override was given, "
        "or when the window has fewer than two period returns to measure a mean or a volatility from."
    )
