"""
Measurement registry — auto-registers FastAPI routes for all measurement plugins.

For each measurement in ALL_MEASUREMENTS:
  - Parses the route template to extract path parameters (always just
    {etf_id}, or none at all for a fund-independent measurement)
  - Dynamically builds a handler function with the correct signature
  - Exposes GET /api/measurements as a manifest listing all available measurements
  - Exposes GET /api/measurement-docs/{id} serving the .mdx doc shipped
    next to each measurement (see measurements/docs.py)

Measurements take no query parameters — they fetch their own inputs (via
measurements/inputs/*) using internal defaults, so the frontend never
needs to know what a measurement needs beyond which ETF to compute for.
"""

import re
from fastapi import APIRouter, HTTPException
from measurements import ALL_MEASUREMENTS
from measurements.docs import DocError, load_doc

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


# ── Documentation endpoint ───────────────────────────────────────────────────
#
# Deliberately NOT mounted at /api/measurements/{id}/doc. Every plugin
# registers its own route under the same /api prefix above, and
# "/measurements/correlation/{etf_id}" would happily match etf_id="doc" —
# shadowing this endpoint for the correlation measurement only, which is
# the kind of bug that shows up once and confuses everyone. A distinct
# first path segment cannot collide with any plugin route.

@measurement_router.get(
    "/measurement-docs/{measurement_id}",
    summary="Read one measurement's documentation",
    description=(
        "Returns the parsed frontmatter and raw MDX body of the .mdx doc "
        "shipped next to a measurement. A measurement with no doc file "
        "answers 200 with has_doc=false and frontmatter synthesised from "
        "its manifest metadata."
    ),
    tags=["measurements"],
)
def get_measurement_doc(measurement_id: str):
    """Serve one measurement's documentation.

    Three outcomes, deliberately distinct:
      - no such measurement          → 404, a stable answer the frontend
                                       should not retry
      - measurement, but no .mdx     → 200 with has_doc=false; shipping no
                                       doc is supported, not a failure
      - .mdx exists but is malformed → 500 naming the file and the problem;
                                       it was hand-written to be read, so
                                       failing loudly beats dropping it
    """
    measurement = next((m for m in ALL_MEASUREMENTS if m.id == measurement_id), None)
    if measurement is None:
        raise HTTPException(404, f"No measurement with id '{measurement_id}'")

    try:
        return load_doc(measurement)
    except DocError as exc:
        raise HTTPException(500, str(exc)) from exc
