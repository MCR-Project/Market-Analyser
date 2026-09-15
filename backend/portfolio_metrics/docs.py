"""
Portfolio metric documentation — loading and validating the .mdx doc that
sits next to each metric class (issue #104).

Deliberately its own small module rather than a shared one with
measurements/docs.py: the two file formats look alike (YAML frontmatter,
then MDX) but validate against different keys (a metric's `example_etf`
is a fallback for a *future* etf_id-based entry, issue #105 - there is no
`example_stock` here at all, since a portfolio metric has no single
holding to feature), and duplicating the ~150 lines this needs was judged
cheaper than coupling two otherwise-independent registries to one shared
parser neither can change alone.

File format, same shape as a measurement's:

    ---
    title: Final Value
    summary: What the portfolio is worth at the end of the window.
    example_etf: SMH        # optional, only meaningful for a future
    ---                      # computed_from="etf_id" entry (issue #105)

    Free-form MDX body.

`title` and `summary` are required. Unknown keys are rejected rather than
silently ignored, so a typo fails loudly at the point it is introduced.

A metric with no .mdx file at all is a normal, supported state - see
`load_doc`. Only a doc that exists and is malformed is an error.
"""

from pathlib import Path

import yaml

from config import DOCS_EXAMPLE_ETF

REQUIRED_KEYS = ("title", "summary")
OPTIONAL_KEYS = ("example_etf",)
ALLOWED_KEYS = REQUIRED_KEYS + OPTIONAL_KEYS

FRONTMATTER_FENCE = "---"


class DocError(ValueError):
    """A doc file exists but cannot be used - always names the offending
    file (and, where relevant, key) so the message alone is enough to fix
    it."""


def parse_doc(text: str, source: str) -> tuple[dict, str]:
    """Split raw doc text into (frontmatter, body) and validate the
    frontmatter. `source` only names the file in error messages."""
    stripped = text.lstrip("﻿").lstrip()
    if not stripped.startswith(FRONTMATTER_FENCE):
        raise DocError(
            f"{source}: missing YAML frontmatter — the file must open with a "
            f"'{FRONTMATTER_FENCE}' line followed by at least "
            f"{' and '.join(REQUIRED_KEYS)}."
        )

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


def load_doc(metric) -> dict:
    """Return the full doc payload for one portfolio metric.

    A metric with no .mdx file is not an error — it gets `has_doc: False`,
    a null body, and frontmatter synthesised from the metadata it already
    declares, exactly like a measurement with no doc.
    """
    path: Path = metric.doc_path

    if path is not None and path.is_file():
        frontmatter, body = parse_doc(path.read_text(encoding="utf-8"), path.name)
        has_doc = True
    else:
        frontmatter, body, has_doc = _synthesised_frontmatter(metric), None, False

    return {
        "id": metric.id,
        "origin": metric.origin,
        "has_doc": has_doc,
        "frontmatter": {**frontmatter, **resolve_example_etf(metric, frontmatter)},
        "mdx": body,
    }


def _synthesised_frontmatter(metric) -> dict:
    return {"title": metric.name or metric.id, "summary": metric.description}


def resolve_example_etf(metric, frontmatter: dict) -> dict:
    """Which ETF a computed_from="etf_id" entry's worked example should
    use (issue #105), by the same precedence MeasurementBase's own
    example_etf follows: the doc's frontmatter first, then the class, then
    the repo-wide default. Meaningless for a computed_from="run" entry -
    those resolve their own example basket in examples.py instead - but
    resolved uniformly here so a doc page can display it either way
    without asking which kind of metric it is looking at.
    """
    return {
        "example_etf": (
            frontmatter.get("example_etf") or metric.example_etf or DOCS_EXAMPLE_ETF
        ),
    }
