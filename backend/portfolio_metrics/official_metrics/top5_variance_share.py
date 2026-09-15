"""Portfolio metric: variance share of the fund's five largest risk
contributors (issue #105)."""

from portfolio_metrics.base import MetricBase
from services.fund_metrics import compute_fund_metrics


class Top5VarianceShareMetric(MetricBase):
    id = "top5VarianceShare"
    name = "Top 5 Variance Share"
    tile_label = "Top 5 Risk Share"
    description = (
        "How much of the fund's own variance its five largest risk "
        "contributors — not necessarily its five largest positions — "
        "account for between them."
    )
    family = "diversification"
    format = "percent"
    formula = (
        "sum of the five largest per-holding shares of the fund's variance "
        "(services.stats.risk_contribution, the Euler decomposition)"
    )
    null_rule = (
        "Null under the same conditions diversificationRatio is: too "
        "little shared price history among the fund's tracked holdings, "
        "or no measurable variance to apportion."
    )
    computed_from = "etf_id"

    def value(self, etf_id):
        return compute_fund_metrics(etf_id)["top5VarianceShare"]

    def reason(self, etf_id):
        return compute_fund_metrics(etf_id)["reasons"].get(self.id)
