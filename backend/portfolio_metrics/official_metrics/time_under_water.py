"""Portfolio metric: time under water (issue #112)."""

from portfolio_metrics.base import RunMetric


class TimeUnderWaterMetric(RunMetric):
    id = "timeUnderWater"
    name = "Time Under Water"
    description = "The longest single stretch, in calendar days, the run spent below a prior peak before recovering - Max Drawdown's 'how deep' with 'for how long' beside it."
    family = "portfolio"
    format = "days"
    default_enabled = False
    formula = "the longest stretch's own end (or the window's last row, if still open) minus its start, in calendar days"
    null_rule = (
        "Null only for a window with fewer than two rows of price history. "
        "0 days is a real answer: the run never fell below a prior peak at all."
    )
