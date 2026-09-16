"""Portfolio metric: effective number of independent bets in a basket
(issue #113)."""

from portfolio_metrics.base import RiskMetric


class EffectiveBetsMetric(RiskMetric):
    id = "effectiveBets"
    name = "Effective Bets"
    tile_label = "Effective Bets"
    description = (
        "The number of equally weighted holdings that would concentrate risk "
        "the same way this basket's actual risk contributions do - the "
        "inverse Herfindahl of riskShare rather than of dollar weight."
    )
    family = "risk"
    format = "ratio"
    formula = "1 ÷ Σ (risk share)² , over the basket's per-holding riskShare"
    null_rule = (
        "Null under the same conditions riskShare is: fewer than two holdings "
        "with a complete price history over the window, or no measurable "
        "variance at all once aligned. Never null for a basket of one holding "
        "- one holding is trivially the only bet in it, reported as 1."
    )
    default_enabled = False
