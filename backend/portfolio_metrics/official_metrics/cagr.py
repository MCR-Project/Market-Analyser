"""Portfolio metric: CAGR (issue #104)."""

from portfolio_metrics.base import RunMetric


class CagrMetric(RunMetric):
    id = "cagr"
    name = "CAGR"
    description = "Compound annual growth rate over the calendar time the window covers."
    family = "portfolio"
    format = "percent_signed"
    formula = "(unitEnd / unitStart)^(365.25 / elapsed_days) − 1, annualised on a 365.25-day year"
    null_rule = "Null when the window is a single row — no elapsed time to compound a growth rate over."
