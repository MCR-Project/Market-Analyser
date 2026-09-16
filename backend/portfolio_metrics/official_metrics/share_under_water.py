"""Portfolio metric: share of the window spent under water (issue #112)."""

from portfolio_metrics.base import RunMetric


class ShareUnderWaterMetric(RunMetric):
    id = "shareUnderWater"
    name = "Share Under Water"
    tile_label = "Time Under Water %"
    description = "Time Under Water's own companion: what fraction of the whole window was spent below a prior peak, not just the longest single stretch of it."
    family = "portfolio"
    format = "percent"
    default_enabled = False
    formula = "sum of every underwater stretch's own duration, over the window's own elapsed days"
    null_rule = (
        "Null only for a window with fewer than two rows of price history, the same floor "
        "Time Under Water reports null for. 0% is a real answer: the run was never under water."
    )
