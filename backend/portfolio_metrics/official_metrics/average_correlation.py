"""Portfolio metric: average pairwise correlation of a basket's own
holdings (issue #113)."""

from portfolio_metrics.base import RiskMetric


class AverageCorrelationMetric(RiskMetric):
    id = "averageCorrelation"
    name = "Average Correlation"
    tile_label = "Avg ρ"
    description = (
        "The average pairwise correlation among this basket's own holdings. "
        "Lower means more diversified; 1.0 would mean every holding moves "
        "in lockstep."
    )
    family = "risk"
    format = "correlation"
    formula = "mean of Corr(rᵢ, rⱼ) over every distinct pair i≠j in the basket"
    null_rule = (
        "Null for a basket of one holding - there is no pair to correlate - or "
        "when fewer than two holdings have a complete price history over the "
        "window, or when no pair of holdings both had measurable variance to "
        "correlate."
    )
    default_enabled = False
