"""
Measurement registry — auto-registers FastAPI routes for all measurement plugins.

For each measurement in ALL_MEASUREMENTS:
  - Parses the route template to extract path parameters (always just
    {etf_id}, or none at all for a fund-independent measurement)
  - Dynamically builds a handler function with the correct signature
  - Exposes GET /api/measurements as a manifest listing all available measurements

Measurements take no query parameters — they fetch their own inputs (via
measurements/inputs/*) using internal defaults, so the frontend never
needs to know what a measurement needs beyond which ETF to compute for.
"""

import re
from fastapi import APIRouter, HTTPException
from measurements import ALL_MEASUREMENTS

measurement_router = APIRouter(prefix="/api")

PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


def _make_handler(measurement):
    """Dynamically create a route handler with explicit path param signature.

    FastAPI needs concrete parameter names in the function signature to bind
    path params. Every measurement route is scoped by etf_id alone (or takes
    no params at all), so there are only two shapes to generate.
    """
    param_names = PATH_PARAM_RE.findall(measurement.route)
    m = measurement  # captured in the closure

    if param_names == ["etf_id"]:
        def handler(etf_id: str):
            try:
                return m.run(etf_id=etf_id)
            except Exception as e:
                raise HTTPException(500, f"Measurement '{m.id}' failed: {e}")
    else:
        def handler():
            try:
                return m.run()
            except Exception as e:
                raise HTTPException(500, f"Measurement '{m.id}' failed: {e}")

    handler.__name__ = f"measure_{m.id}"
    handler.__doc__ = m.description
    return handler


# ── Auto-register each measurement as a GET route ────────────────────────────

for m in ALL_MEASUREMENTS:
    measurement_router.add_api_route(
        m.route,
        _make_handler(m),
        methods=["GET"],
        name=m.id,
        summary=m.name,
        description=m.description,
        tags=["measurements"],
    )


# ── Manifest endpoint ────────────────────────────────────────────────────────

@measurement_router.get(
    "/measurements",
    summary="List available measurements",
    description="Returns metadata for every registered measurement plugin.",
    tags=["measurements"],
)
def list_measurements():
    """Returns the manifest of all registered measurement plugins."""
    return [m.manifest() for m in ALL_MEASUREMENTS]
