"""
Measurement documentation — loading and validating the .mdx doc that sits
next to each measurement plugin.

A measurement's long-form documentation lives beside its module, named
after the file:

    official_measurements/correlation.py  →  official_measurements/correlation.mdx

Keeping the doc next to the plugin rather than in the frontend is what
lets an addon dropped into addon_measurements/ ship its own
documentation, with no frontend change and no central list to edit.

File format — YAML frontmatter, then a free-form MDX body:

    ---
    title: Correlation to Fund
    summary: How closely a holding moves with the rest of the fund.
    example_etf: SMH        # optional
    example_stock: NVDA     # optional
    ---

    Free-form MDX body.

`title` and `summary` are required. Unknown keys are rejected rather than
silently ignored, so a typo (`exemple_etf`) fails loudly at the point it
is introduced instead of quietly doing nothing forever. The body is NOT
validated: which sections a doc should contain is a written convention,
not something enforced here.

A measurement with no .mdx file at all is a normal, supported state — see
`load_doc`. Only a doc that exists and is malformed is an error.
"""

from pathlib import Path

import yaml

from config import DOCS_EXAMPLE_ETF, DOCS_EXAMPLE_STOCK

# ── Frontmatter schema ───────────────────────────────────────────────────────

REQUIRED_KEYS = ("title", "summary")
OPTIONAL_KEYS = ("example_etf", "example_stock")
ALLOWED_KEYS = REQUIRED_KEYS + OPTIONAL_KEYS

FRONTMATTER_FENCE = "---"


class DocError(ValueError):
    """A doc file exists but cannot be used.

    Always names the offending file (and, where relevant, the offending
    key) so the message alone is enough to fix it.
    """


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_doc(text: str, source: str) -> tuple[dict, str]:
    """Split raw doc text into (frontmatter, body) and validate the frontmatter.

    `source` is only used to name the file in error messages.
    """
    stripped = text.lstrip("﻿").lstrip()
    if not stripped.startswith(FRONTMATTER_FENCE):
        raise DocError(
            f"{source}: missing YAML frontmatter — the file must open with a "
            f"'{FRONTMATTER_FENCE}' line followed by at least "
            f"{' and '.join(REQUIRED_KEYS)}."
        )

    # Split on the closing fence: everything between the two fences is
    # YAML, everything after is the MDX body.
    rest = stripped[len(FRONTMATTER_FENCE):].lstrip("\r\n")
    parts = rest.split(f"\n{FRONTMATTER_FENCE}", 1)
    if len(parts) != 2:
        raise DocError(
            f"{source}: frontmatter is never closed — expected a second "
            f"'{FRONTMATTER_FENCE}' line after the metadata block."
        )

    raw_frontmatter, body = parts
    try:
        parsed = yaml.safe_load(raw_frontmatter)
    except yaml.YAMLError as exc:
        raise DocError(f"{source}: frontmatter is not valid YAML — {exc}") from exc

    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise DocError(
            f"{source}: frontmatter must be a block of key: value pairs, "
            f"got {type(parsed).__name__}."
        )

    return _validate_frontmatter(parsed, source), body.lstrip("\r\n")


def _validate_frontmatter(parsed: dict, source: str) -> dict:
    """Check the frontmatter against the schema above, or raise DocError."""
    missing = [key for key in REQUIRED_KEYS if not str(parsed.get(key) or "").strip()]
    if missing:
        raise DocError(
            f"{source}: frontmatter is missing required "
            f"{'key' if len(missing) == 1 else 'keys'} "
            f"{', '.join(repr(k) for k in missing)}."
        )

    unknown = [key for key in parsed if key not in ALLOWED_KEYS]
    if unknown:
        raise DocError(
            f"{source}: frontmatter has unknown "
            f"{'key' if len(unknown) == 1 else 'keys'} "
            f"{', '.join(repr(k) for k in unknown)} — allowed keys are "
            f"{', '.join(ALLOWED_KEYS)}."
        )

    for key, value in parsed.items():
        if not isinstance(value, str):
            raise DocError(
                f"{source}: frontmatter key {key!r} must be text, got "
                f"{type(value).__name__}. Quote the value if it looks like a "
                f"number or a date."
            )

    return {key: value.strip() for key, value in parsed.items()}


# ── Loading ──────────────────────────────────────────────────────────────────

def load_doc(measurement) -> dict:
    """Return the full doc payload for one measurement.

    A measurement with no .mdx file is not an error — it gets
    `has_doc: False`, a null body, and frontmatter synthesised from the
    metadata it already declares, so the documentation page can still
    render everything it knows (name, summary, schemas, config, worked
    example) with a note that no prose has been written yet.

    A doc file that exists but is malformed IS an error (DocError): it was
    written by hand and is meant to be read, so failing loudly beats
    serving a page that silently drops it.
    """
    path: Path = measurement.doc_path

    if path is not None and path.is_file():
        frontmatter, body = parse_doc(path.read_text(encoding="utf-8"), path.name)
        has_doc = True
    else:
        frontmatter, body, has_doc = _synthesised_frontmatter(measurement), None, False

    return {
        "id": measurement.id,
        "origin": measurement.origin,
        "has_doc": has_doc,
        "frontmatter": {**frontmatter, **resolve_examples(measurement, frontmatter)},
        "mdx": body,
    }


def _synthesised_frontmatter(measurement) -> dict:
    """Stand-in frontmatter for a measurement that ships no .mdx file."""
    return {
        "title": measurement.name or measurement.id,
        "summary": measurement.description,
    }


def resolve_examples(measurement, frontmatter: dict) -> dict:
    """Work out which ETF/stock this measurement's worked example should use.

    Precedence, most specific first: what the doc's own frontmatter asks
    for, then what the measurement class declares, then the repo-wide
    default in config.py. The doc wins over the class because it is the
    more specific statement — it is about how to *explain* this
    measurement, which is exactly what the example is for.
    """
    return {
        "example_etf": (
            frontmatter.get("example_etf")
            or measurement.example_etf
            or DOCS_EXAMPLE_ETF
        ),
        "example_stock": (
            frontmatter.get("example_stock")
            or measurement.example_stock
            or DOCS_EXAMPLE_STOCK
        ),
    }
