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

A computed_from="etf_id" entry (issue #105) follows the same rule over a
fund instead of a run: `metric.value(etf_id)` is called against the
documented example ETF (`metric.example_etf`, or `config.
DOCS_EXAMPLE_ETF`) exactly as the fund metrics card would, and a null
result carries whatever `metric.reason(etf_id)` says - the etf_id
counterpart to a run's own `metrics["reasons"]` entry, since there is no
shared response here to read a reason out of.

A computed_from="risk" entry (issue #113) follows the "run" branch's own
shape rather than the etf_id one's: `compute_portfolio_risk` runs against
the same documented example portfolio `simulate_portfolio` does (`value`
and `contribution` are accepted by that basket's shape but irrelevant to
what this endpoint answers), and the risk response's own `reasons` is
read the same way a run's `metrics["reasons"]` is - so
PortfolioMetricWorkedExample.jsx, which already knows how to render a
`{"portfolio", "run", "value", "reason"}` payload, needs no change to
render this one too.
"""

from config import DOCS_EXAMPLE_ETF, DOCS_EXAMPLE_PORTFOLIO
from services.portfolio import compute_portfolio_risk, simulate_portfolio


def build_example(metric) -> dict:
    """Build the worked-example payload for one portfolio metric."""
    if metric.computed_from == "etf_id":
        etf_id = metric.example_etf or DOCS_EXAMPLE_ETF
        value = metric.value(etf_id)
        reason = metric.reason(etf_id) if value is None else None
        return {
            "etf_id": etf_id,
            "value": value,
            **({"reason": reason} if reason else {}),
        }

    portfolio = metric.example_portfolio or DOCS_EXAMPLE_PORTFOLIO

    if metric.computed_from == "risk":
        risk = compute_portfolio_risk(
            [dict(holding) for holding in portfolio["holdings"]],
            period=portfolio.get("period"),
            start=portfolio.get("start"),
            end=portfolio.get("end"),
        )
        return {
            "portfolio": portfolio,
            "run": {"start": risk["start"], "end": risk["end"], "metrics": risk},
            "value": metric.value(risk),
            **(
                {"reason": risk["reasons"][metric.id]}
                if metric.value(risk) is None and metric.id in risk.get("reasons", {})
                else {}
            ),
        }

    run = simulate_portfolio(
        [dict(holding) for holding in portfolio["holdings"]],
        value=portfolio.get("value", 10_000),
        period=portfolio.get("period"),
        start=portfolio.get("start"),
        end=portfolio.get("end"),
        rebalance=portfolio.get("rebalance", "none"),
        contribution=portfolio.get("contribution"),
        # A metric whose own example draws money out (Withdrawn, issue #150)
        # names a `withdrawal` in its `example_portfolio`. Dropping it here
        # would document that metric with a figure of zero.
        withdrawal=portfolio.get("withdrawal"),
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
