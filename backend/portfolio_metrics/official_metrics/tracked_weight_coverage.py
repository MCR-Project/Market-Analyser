"""Portfolio metric: tracked weight coverage (issue #105)."""

from portfolio_metrics.base import MetricBase
from services.fund_metrics import compute_fund_metrics


class TrackedWeightCoverageMetric(MetricBase):
    id = "trackedWeightCoverage"
    name = "Tracked Weight Coverage"
    tile_label = "Coverage"
    description = (
        "How much of the fund's weight its tracked holdings — each at "
        "least 1% of the fund — add up to. The rest is real weight this "
        "dashboard has no constituent-level figures for."
    )
    family = "coverage"
    format = "percent"
    formula = "Σ tracked holding weights (the same total_weight the % of ETF column already reports)"
    null_rule = "Never null — a fund with no tracked holdings at all genuinely covers 0% of itself."
    computed_from = "etf_id"

    def value(self, etf_id):
        return compute_fund_metrics(etf_id)["trackedWeightCoverage"]
