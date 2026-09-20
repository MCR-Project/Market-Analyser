"""Portfolio metric: withdrawn (issue #150)."""

from portfolio_metrics.base import RunMetric


class WithdrawnMetric(RunMetric):
    id = "withdrawn"
    name = "Withdrawn"
    description = "The recurring withdrawals on their own — what was actually taken out of the portfolio."
    family = "account"
    formula = "Σ what each withdrawal actually took, once per period after the window's first row"
    null_rule = "Never null: 0 when there is no recurring withdrawal, which is the default."

    # The default example portfolio pays money in, and a portfolio does one or
    # the other (ADR 0002), so this page names its own - the same basket and
    # window, drawn on instead of paid into. $100 a month against $10,000 over
    # five years is enough elapsed time to be a real figure without emptying it.
    example_portfolio = {
        "holdings": [{"ticker": "SPY", "weight": 60}, {"ticker": "AGG", "weight": 40}],
        "value": 10_000,
        "period": "5y",
        "rebalance": "none",
        "withdrawal": {"amount": 100, "frequency": "monthly"},
    }
