"""Portfolio metric: each holding's own share of a basket's variance
(issue #113)."""

from portfolio_metrics.base import RiskMetric


class RiskShareMetric(RiskMetric):
    id = "riskShare"
    name = "Risk Share"
    description = (
        "Each holding's own share of the basket's total variance, as a "
        "percentage that sums to 100 - not the same thing as its dollar "
        "weight, since a small, volatile, uncorrelated holding can carry "
        "far more of the basket's risk than its weight suggests."
    )
    family = "risk"
    format = "percent"
    formula = "wᵢ · Cov(rᵢ, r_p) ÷ Var(r_p) × 100, per holding i - the Euler decomposition of variance"
    null_rule = (
        "Null (for every holding at once) when fewer than two holdings have "
        "a complete price history over the window, or when the basket has "
        "no measurable variance at all to apportion. Never null for a basket "
        "of one holding, which trivially carries 100% of its own risk."
    )
    # A per-holding breakdown, not a single number - there is nothing a
    # tile could show that would not misrepresent it as one figure. It
    # still gets a manifest row and a doc page, the same "no tile, still
    # documented" decision dividendIncome/dividendYield/incomeUnknownFor
    # made under issue #68.
    tile = False
