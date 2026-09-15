"""
Portfolio metric registry (issue #104) — exposes the manifest and
documentation for every portfolio metric tile, mirroring
measurements/registry.py.

The one structural difference from that registry: a measurement gets its
own route per plugin, because each one computes something the frontend has
to ask for. A portfolio metric does not - every metric shipped today reads
its figure out of the response `POST /api/portfolio/simulate` already
returns (see base.RunMetric), so there is nothing to route per metric,
only a manifest and a pair of documentation endpoints.

  - `GET /api/portfolio-metrics` — the manifest: every metric's identity,
    family, formula, null rule and doc pointer, plus the family
    definitions themselves (label + note), so `PortfolioSummary.jsx`'s two
    row headers are read off this rather than hardcoded (issue #104's own
    decision).
  - `GET /api/portfolio-metric-docs/{metric_id}` — parsed frontmatter + raw
    MDX body of the .mdx shipped next to the metric.
  - `GET /api/portfolio-metric-docs/{metric_id}/example` — the worked
    example behind that doc.
"""

from fastapi import APIRouter, HTTPException

from portfolio_metrics import ALL_METRICS
from portfolio_metrics.base import FAMILIES
from portfolio_metrics.docs import DocError, load_doc
from portfolio_metrics.examples import build_example

metric_router = APIRouter(prefix="/api")


@metric_router.get(
    "/portfolio-metrics",
    summary="List available portfolio metrics",
    description=(
        "Returns every registered portfolio metric's self-description "
        "plus the family definitions (label, note) their `family` field "
        "names."
    ),
    tags=["portfolio-metrics"],
)
def list_portfolio_metrics():
    return {
        "metrics": [m.manifest() for m in ALL_METRICS],
        "families": FAMILIES,
    }


@metric_router.get(
    "/portfolio-metric-docs/{metric_id}",
    summary="Read one portfolio metric's documentation",
    description=(
        "Returns the parsed frontmatter and raw MDX body of the .mdx doc "
        "shipped next to a portfolio metric. A metric with no .mdx answers "
        "200 with has_doc=false and frontmatter synthesised from its "
        "manifest metadata."
    ),
    tags=["portfolio-metrics"],
)
def get_portfolio_metric_doc(metric_id: str):
    """Three outcomes, deliberately distinct — the same three
    measurement-docs answers with, for the same reasons:
      - no such metric              → 404, a stable answer, do not retry
      - metric, but no .mdx         → 200 with has_doc=false
      - .mdx exists but malformed   → 500 naming the file and the problem
    """
    metric = _find(metric_id)
    try:
        return load_doc(metric)
    except DocError as exc:
        raise HTTPException(500, str(exc)) from exc


@metric_router.get(
    "/portfolio-metric-docs/{metric_id}/example",
    summary="Worked example for one portfolio metric",
    description=(
        "Runs the documented example portfolio and returns the metric's "
        "real value from that run."
    ),
    tags=["portfolio-metrics"],
)
def get_portfolio_metric_example(metric_id: str):
    """A DataUnavailable from the simulated example is deliberately NOT
    caught: main.py maps it onto a 503 with Retry-After, the same as
    measurement-docs' own example endpoint, so a doc page opened during an
    upstream blip retries and heals rather than showing a fabricated
    number."""
    metric = _find(metric_id)
    try:
        return build_example(metric)
    except DocError as exc:
        raise HTTPException(500, str(exc)) from exc


def _find(metric_id: str):
    metric = next((m for m in ALL_METRICS if m.id == metric_id), None)
    if metric is None:
        raise HTTPException(404, f"No portfolio metric with id '{metric_id}'")
    return metric
