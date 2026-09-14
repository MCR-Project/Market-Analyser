"""
Measurement registry — auto-registers FastAPI routes for all measurement plugins.

For each measurement in ALL_MEASUREMENTS:
  - Parses the route template to extract path parameters (always just
    {etf_id}, or none at all for a fund-independent measurement)
  - Dynamically builds a handler function with the correct signature
  - Exposes GET /api/measurements as a manifest listing all available measurements
  - Exposes GET /api/measurement-docs/{id} serving the .mdx doc shipped
    next to each measurement (see measurements/docs.py)
  - Exposes GET /api/measurement-docs/{id}/example with the real inputs
    and computed values behind that doc (see measurements/examples.py)

Measurements take no query parameters — they fetch their own inputs (via
measurements/inputs/*) using internal defaults, so the frontend never
needs to know what a measurement needs beyond which ETF to compute for.
"""

import re
from fastapi import APIRouter, HTTPException
from measurements import ALL_MEASUREMENTS
from measurements.docs import DocError, load_doc
from measurements.examples import build_example
from services.market_data import DataUnavailable, SymbolNotFound

measurement_router = APIRouter(prefix="/api")

PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


def _make_handler(measurement):
    """Dynamically create a route handler with explicit path param signature.

    FastAPI needs concrete parameter names in the function signature to bind
    path params. Every measurement route is scoped by etf_id alone (or takes
    no params at all), so there are only two shapes to generate.

    A measurement failing because the data behind it is missing or briefly
    unreachable is not a bug in the measurement, so DataUnavailable and
    SymbolNotFound are re-raised untouched for main.py to map onto 503 and
    404. Swallowing them into a blanket 500 made every column retry
    forever against a ticker that does not exist: useMeasurements retries a
    5xx, so three columns kept asking about ZZZZ every three seconds long
    after the ETF request itself had correctly given up.

    The handler returns whatever `m.run()` produced with no key filtering
    of its own, which is what already carries `per_ticker_reason` (issue
    #99) into the response wherever a measurement's `compute()` set one —
    there is no allowlist here to fall out of date as `base.run()` grows
    what it puts in the result.
    """
    param_names = PATH_PARAM_RE.findall(measurement.route)
    m = measurement  # captured in the closure

    def fail(exc):
        raise HTTPException(500, f"Measurement '{m.id}' failed: {exc}")

    if param_names == ["etf_id"]:
        def handler(etf_id: str):
            try:
                return m.run(etf_id=etf_id)
            except (DataUnavailable, SymbolNotFound):
                raise
            except Exception as e:
                fail(e)
    else:
        def handler():
            try:
                return m.run()
            except (DataUnavailable, SymbolNotFound):
                raise
            except Exception as e:
                fail(e)

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

def _column_manifest_entries(measurement) -> list[dict]:
    """One manifest row per column this plugin provides (issue #100),
    so the frontend discovers columns to toggle rather than plugins to
    think about.

    Built from `measurement.manifest()` (the plugin's own identity -
    unaffected by this function) plus `measurement.resolved_columns`
    (one dict per column, whichever way the plugin declared them) - each
    row is the plugin's manifest with that one column's fields overlaid
    on top, plus `measurement_id`, which is what tells the frontend which
    route actually computes this column and lets it group sibling
    columns under one plugin in the picker.

    A single-column plugin's one row keeps `id` equal to the plugin's own
    id - already unique, the same way every measurement's `id` always
    had to be - which is what makes today's three official measurements'
    manifest rows unaffected by this function beyond the addition of
    `measurement_id` itself. A multi-column plugin's `id` is namespaced
    as `f"{measurement.id}.{column['key']}"` so its own columns cannot
    collide with each other or with an unrelated plugin's.
    """
    base = measurement.manifest()
    columns = measurement.resolved_columns
    single = len(columns) == 1

    entries = []
    for column in columns:
        entry = {**base, "measurement_id": measurement.id}
        entry["id"] = measurement.id if single else f"{measurement.id}.{column['key']}"
        entry["column_key"] = column["key"]
        entry["column_label"] = column["label"]
        entry["column_width"] = column["width"]
        entry["default_enabled"] = column["default_enabled"]
        entry["filterable"] = column["filterable"]
        entry["filter_type"] = column["filter_type"]
        entry["filter_options"] = column["filter_options"]
        entry["filter_min"] = column["filter_min"]
        entry["filter_max"] = column["filter_max"]
        entry["filter_step"] = column["filter_step"]
        entry["sort_type"] = column["sort_type"]
        entry["sort_order"] = column["sort_order"]
        entries.append(entry)
    return entries


@measurement_router.get(
    "/measurements",
    summary="List available measurements",
    description="Returns metadata for every column a registered measurement plugin provides.",
    tags=["measurements"],
)
def list_measurements():
    """Returns the manifest, one entry per column (issue #100) rather
    than one per plugin - a plugin providing several columns from one
    computation appears as that many independently toggleable rows, each
    naming the plugin (`measurement_id`) that actually computes it."""
    return [entry for m in ALL_MEASUREMENTS for entry in _column_manifest_entries(m)]


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
    measurement = _find(measurement_id)

    try:
        return load_doc(measurement)
    except DocError as exc:
        raise HTTPException(500, str(exc)) from exc


@measurement_router.get(
    "/measurement-docs/{measurement_id}/example",
    summary="Worked example for one measurement",
    description=(
        "Runs a measurement against its documented example ETF and returns "
        "the real input values, the computed per-ticker values and the "
        "rendered cells for a handful of holdings."
    ),
    tags=["measurements"],
)
def get_measurement_example(measurement_id: str):
    """Serve the worked example behind a measurement's documentation.

    A DataUnavailable from any upstream fetch is deliberately NOT caught:
    main.py maps it onto a 503 with Retry-After, so a doc page opened
    during a Yahoo/Supabase blip retries and heals, rather than showing
    made-up numbers or a permanent-looking error.
    """
    measurement = _find(measurement_id)

    try:
        frontmatter = load_doc(measurement).get("frontmatter", {})
        return build_example(measurement, frontmatter)
    except DocError as exc:
        raise HTTPException(500, str(exc)) from exc


def _find(measurement_id: str):
    """Look up a registered measurement, or 404.

    A 404 is a stable answer the frontend will not retry — the right
    behaviour for an id that will never exist, as opposed to an upstream
    failure, which is a 503.
    """
    measurement = next((m for m in ALL_MEASUREMENTS if m.id == measurement_id), None)
    if measurement is None:
        raise HTTPException(404, f"No measurement with id '{measurement_id}'")
    return measurement
