"""Portfolio metric: fund diversification ratio (issue #105)."""

from portfolio_metrics.base import MetricBase
from services.fund_metrics import compute_fund_metrics


class DiversificationRatioMetric(MetricBase):
    id = "diversificationRatio"
    name = "Diversification Ratio"
    tile_label = "Diversification"
    description = (
        "How much of the fund's own volatility its holdings' individual "
        "swings would add up to if they moved independently, over what "
        "they actually came to once their correlations are counted."
    )
    family = "diversification"
    format = "ratio"
    formula = "Σ (weight × holding volatility) ÷ fund volatility, over the fund's own tracked holdings"
    null_rule = (
        "Null when fewer than two of the fund's tracked holdings have a "
        "complete price history over the window, or when the basket has "
        "no measurable variance at all to divide by."
    )
    computed_from = "etf_id"

    def value(self, etf_id):
        return compute_fund_metrics(etf_id)["diversificationRatio"]

    def reason(self, etf_id):
        return compute_fund_metrics(etf_id)["reasons"].get(self.id)
