"""Portfolio metric: money-weighted return (issue #104)."""

from portfolio_metrics.base import RunMetric


class MoneyWeightedReturnMetric(RunMetric):
    id = "moneyWeightedReturn"
    name = "Money-Weighted Return"
    tile_label = "Money-Weighted"
    description = (
        "Internal rate of return: the annual rate that reconciles every deposit, "
        "discounted from the day it arrived, with the final value."
    )
    family = "account"
    format = "percent_signed"
    formula = "the rate r solving Σ flow / (1 + r)^years = 0, found by bisection"
    null_rule = (
        "Null when the window is too short for an internal rate of return to be "
        "found — no elapsed time at all, or a return so extreme no annual rate "
        "discounts one into the other."
    )
