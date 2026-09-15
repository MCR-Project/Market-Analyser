"""
Worked examples for a portfolio metric's doc page (issue #104).

Much narrower than measurements/examples.py: there is no per-ticker sample
to truncate here, because a portfolio metric describes the whole run, not
one holding. The payload is "here is the portfolio, here is what the run
looked like, here is this metric's own figure from it" - three things, not
a sampled table.

**The computed value is real**, the same load-bearing rule
measurements/examples.py states: `simulate_portfolio` runs against
`config.DOCS_EXAMPLE_PORTFOLIO` (or a metric's own `example_portfolio`
override) exactly as `POST /api/portfolio/simulate` would, and the
metric's own `value()` reads its figure back out of that real response -
never a fabricated number standing in for one.
"""

from config import DOCS_EXAMPLE_PORTFOLIO
from services.portfolio import simulate_portfolio


def build_example(metric) -> dict:
    """Build the worked-example payload for one portfolio metric.

    A computed_from="etf_id" entry (issue #105) has no run to simulate -
    its own value() takes an etf_id directly - so this only echoes which
    fund it would be shown against; #105 is what actually exercises that
    path with a real metric.
    """
    if metric.computed_from != "run":
        return {"etf_id": metric.example_etf, "value": None}

    portfolio = metric.example_portfolio or DOCS_EXAMPLE_PORTFOLIO
    run = simulate_portfolio(
        [dict(holding) for holding in portfolio["holdings"]],
        value=portfolio.get("value", 10_000),
        period=portfolio.get("period"),
        start=portfolio.get("start"),
        end=portfolio.get("end"),
        rebalance=portfolio.get("rebalance", "none"),
        contribution=portfolio.get("contribution"),
    )
    run_metrics = run["metrics"]

    return {
        "portfolio": portfolio,
        "run": {"start": run["start"], "end": run["end"], "metrics": run_metrics},
        "value": metric.value(run),
        # Left out entirely when this metric's value in this example run
        # isn't null (issue #99's own convention: a key present only when
        # it actually applies, not a null one sent every time).
        **(
            {"reason": run_metrics["reasons"][metric.id]}
            if metric.value(run) is None and metric.id in run_metrics.get("reasons", {})
            else {}
        ),
    }
