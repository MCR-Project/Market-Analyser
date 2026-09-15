"""Portfolio metric: dividend income (issue #104)."""

from portfolio_metrics.base import RunMetric


class DividendIncomeMetric(RunMetric):
    id = "dividendIncome"
    name = "Dividend Income"
    description = (
        "Cash paid over the window by the holdings the `dividends` table can speak "
        "for, on the shares held at each ex-date — already inside every value above "
        "via the adjusted closes, never added on top."
    )
    family = "dividend"
    # The dividend note stays prose, not a tile (issue #68, kept as-is by
    # issue #104): still a full registry entry with its own doc page, just
    # never offered in the enable/disable dialog.
    tile = False
    default_enabled = True
    formula = "Σ shares_held(ticker) × dividend.amount, over events whose ex-date falls in the window"
    null_rule = "Never null; 0 when no dividends were paid in the window."
