"""Portfolio metric: total return (issue #104)."""

from portfolio_metrics.base import RunMetric


class TotalReturnMetric(RunMetric):
    id = "totalReturn"
    name = "Total Return"
    description = (
        "What a dollar left alone in the portfolio did over the window, "
        "with any contributions taken back out first."
    )
    family = "portfolio"
    format = "percent_signed"
    formula = "(unitEnd / unitStart − 1) × 100, read off the flow-free unit value"
    null_rule = (
        "Never null in practice: the opening value is validated greater than "
        "zero before a simulation ever starts."
    )
