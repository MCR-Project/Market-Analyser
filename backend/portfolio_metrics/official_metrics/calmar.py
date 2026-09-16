"""Portfolio metric: Calmar ratio (issue #112)."""

from portfolio_metrics.base import RunMetric


class CalmarMetric(RunMetric):
    id = "calmar"
    name = "Calmar Ratio"
    description = "CAGR divided by the depth of the worst drawdown - how much was made for how deep the worst fall was."
    family = "portfolio"
    format = "ratio"
    default_enabled = False
    formula = "CAGR / |max drawdown|"
    null_rule = (
        "Null when CAGR itself is null, or when the run never fell below a prior peak - "
        "a ratio against a drawdown of exactly zero is not a number, however good the CAGR."
    )
