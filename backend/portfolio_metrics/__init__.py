"""
Portfolio metric registry barrel (issue #104) — mirrors measurements/__init__.py.

Adding a metric:
  1. Create a new file in official_metrics/ (e.g. calmar.py)
  2. Subclass RunMetric (base.py) for a metric read out of a completed
     simulate_portfolio() response — every metric shipped today is this
     kind — or MetricBase directly for a computed_from="etf_id" one
     (issue #105), implementing value() yourself
  3. Add the instance to OFFICIAL_METRICS in official_metrics/__init__.py
  4. Copy portfolio_metrics/DOC_TEMPLATE.mdx to calmar.mdx next to it and
     fill it in — skipping this is supported (the page falls back to the
     metadata above) but leaves the tile unexplained

The registry (registry.py) reads ALL_METRICS to build the manifest and
serve documentation; there is no per-metric route to register, unlike
measurements, since every metric shipped today reads its figure out of
the one response POST /api/portfolio/simulate already returns.
"""

from portfolio_metrics.official_metrics import OFFICIAL_METRICS

ALL_METRICS = list(OFFICIAL_METRICS)
