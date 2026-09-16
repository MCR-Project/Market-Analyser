"""Portfolio metric: pain index (issue #112)."""

from portfolio_metrics.base import RunMetric


class PainIndexMetric(RunMetric):
    id = "painIndex"
    name = "Pain Index"
    description = "Time-weighted average drawdown depth across the whole window - Max Drawdown's 'how much, once' answered as 'how much, on average'."
    family = "portfolio"
    format = "percent"
    default_enabled = False
    formula = "time-weighted mean of (unitValue − running peak) / running peak, each day weighted by how long it persisted"
    null_rule = (
        "Never null except for a window with no elapsed day at all: 0% means the "
        "run never fell below a prior peak, which is a real answer, not a missing one."
    )
