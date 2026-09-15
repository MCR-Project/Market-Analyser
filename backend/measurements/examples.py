"""
Worked examples — the real numbers behind a measurement, for its doc page.

A documentation page explains a measurement far better by showing it work
than by describing it: here are the actual input values for a handful of
tickers, and here is what this measurement computed from them. This module
builds that payload.

Two things are load-bearing.

**The computed values are real.** `per_ticker` comes from running the
measurement exactly as the dashboard runs it, over the whole fund, and is
only *sliced* to the sample tickers afterwards. Computing over five
holdings instead would be cheaper and completely wrong: correlation's
average ρ is an average over every peer, so a five-ticker run would print
numbers that disagree with the table the reader is trying to understand.

**Everything is truncated.** `fetch_inputs()` legitimately returns whole
price histories and an NxN matrix — unreadable in a doc and needlessly
large over the wire. Samples are cut to the same few tickers, long lists
and strings are capped, and anything cut is flagged with `truncated` so
the page can say so rather than implying it is showing everything.

Nothing here fetches anything the dashboard doesn't already fetch, so it
rides the same caches in services.market_data — a doc page view costs no
upstream requests that a normal page view wouldn't.

**A multi-column plugin (issue #100) needs its own branch** (issue
#107 is the first to actually exercise it — no official measurement
declared `columns` before it). `run()`'s own `per_ticker`/
`per_ticker_mdx`/`per_ticker_reason` nest one level deeper by column key
for such a plugin; a worked example for it nests the same way rather
than flattening onto the single-column shape, and additionally carries
`columns` (the plugin's `resolved_columns`, key + label only) so a doc
page knows there is more than one series to show per ticker at all.
"""

from measurements.docs import resolve_examples
from measurements.inputs import INPUT_REGISTRY
from measurements.inputs.holdings import get_holdings

# How much of anything to show. Small on purpose: this is an illustration,
# not a data dump.
MAX_TICKERS = 5
MAX_LIST_ITEMS = 5
MAX_STRING_CHARS = 400


def build_example(measurement, frontmatter: dict | None = None) -> dict:
    """Build the worked-example payload for one measurement."""
    examples = resolve_examples(measurement, frontmatter or {})
    etf_id = examples["example_etf"]
    example_stock = examples["example_stock"]

    # Fetched here to rank the sample by weight, and again by the holdings
    # input spec's own sampler below. That second call is a cache hit, and
    # is worth it to keep every getter's sampler self-contained rather
    # than special-casing this one in the loop.
    holdings = get_holdings(etf_id)
    all_tickers = [row[0] for row in holdings]

    result = measurement.run(etf_id=etf_id)
    columns = measurement.resolved_columns
    multi_column = len(columns) > 1

    if multi_column:
        example = _build_multi_column_result(measurement, columns, result, all_tickers, example_stock)
    else:
        example = _build_single_column_result(result, all_tickers, example_stock)

    example["etf_id"] = etf_id
    example["inputs"] = _sample_inputs(measurement, etf_id, all_tickers, example["tickers"])
    # The window this example was actually computed over (issue #101) -
    # run()'s own default, since a worked example is never wired to the
    # table's shared control. Left out entirely for a plugin with no
    # window at all, the same way per_ticker_reason is.
    if "window" in result:
        example["window"] = result["window"]
        example["window_label"] = measurement.window_label(result["window"])
    return example


def _build_single_column_result(result: dict, all_tickers: list[str], example_stock: str) -> dict:
    per_ticker = result.get("per_ticker", {}) or {}
    per_ticker_mdx = result.get("per_ticker_mdx", {}) or {}
    per_ticker_reason = result.get("per_ticker_reason") or {}

    sample_tickers = _pick_sample_tickers(all_tickers, per_ticker, per_ticker_reason, example_stock)

    example = {
        "example_stock": example_stock if example_stock in sample_tickers else None,
        "tickers": sample_tickers,
        "per_ticker": {t: per_ticker.get(t) for t in sample_tickers},
        "per_ticker_mdx": {t: per_ticker_mdx.get(t) for t in sample_tickers},
        "truncated": len(per_ticker) > len(sample_tickers),
        "total_tickers": len(per_ticker) or len(all_tickers),
    }
    # Left out entirely when nothing in the sample has one (issue #99),
    # the same way run() leaves the key off a measurement that never sets
    # it — a doc page for a measurement with no reasons to show gets
    # exactly the payload it always has.
    if any(t in per_ticker_reason for t in sample_tickers):
        example["per_ticker_reason"] = {
            t: per_ticker_reason[t] for t in sample_tickers if t in per_ticker_reason
        }
    return example


def _build_multi_column_result(measurement, columns, result, all_tickers, example_stock) -> dict:
    """The nested counterpart of `_build_single_column_result` for a
    plugin declaring several columns (issue #100), exercised for real
    for the first time by issue #107's fund-relation and capture-ratio
    plugins.

    `per_ticker`/`per_ticker_mdx`/`per_ticker_reason` are keyed by column
    first, exactly matching `run()`'s own nesting for such a plugin,
    rather than flattened onto the single-column shape — a ticker's beta
    and its R² are different series, not one value with two names. Which
    tickers make the sample is still decided once, across every column: a
    ticker earns its row if *any* column has a real value or a reason for
    it, the same "nothing to show, skip it" rule the single-column path
    applies to its one column.
    """
    keys = [c["key"] for c in columns]
    per_ticker_by_col = result.get("per_ticker", {}) or {}
    per_ticker_mdx_by_col = result.get("per_ticker_mdx", {}) or {}
    per_ticker_reason_by_col = result.get("per_ticker_reason") or {}

    combined_values, combined_reasons = {}, {}
    for key in keys:
        for t, v in (per_ticker_by_col.get(key) or {}).items():
            if v is not None:
                combined_values[t] = v
        for t, r in (per_ticker_reason_by_col.get(key) or {}).items():
            combined_reasons[t] = r

    sample_tickers = _pick_sample_tickers(all_tickers, combined_values, combined_reasons, example_stock)

    example = {
        "example_stock": example_stock if example_stock in sample_tickers else None,
        "tickers": sample_tickers,
        "columns": [{"key": c["key"], "label": c["label"]} for c in columns],
        "per_ticker": {
            key: {t: (per_ticker_by_col.get(key) or {}).get(t) for t in sample_tickers}
            for key in keys
        },
        "per_ticker_mdx": {
            key: {t: (per_ticker_mdx_by_col.get(key) or {}).get(t) for t in sample_tickers}
            for key in keys
        },
        "truncated": len(all_tickers) > len(sample_tickers),
        "total_tickers": len(all_tickers),
    }
    per_ticker_reason = {}
    for key in keys:
        col_reasons = {
            t: (per_ticker_reason_by_col.get(key) or {})[t]
            for t in sample_tickers
            if t in (per_ticker_reason_by_col.get(key) or {})
        }
        if col_reasons:
            per_ticker_reason[key] = col_reasons
    if per_ticker_reason:
        example["per_ticker_reason"] = per_ticker_reason
    return example


def _pick_sample_tickers(all_tickers, per_ticker, per_ticker_reason, example_stock) -> list[str]:
    """Which few holdings to feature.

    The measurement's declared example stock leads when the fund actually
    holds it — a doc that says "take NVDA" should show NVDA's row — and
    the rest follow by weight, since `all_tickers` arrives weight-sorted.
    Tickers with neither a computed value nor a reason for the lack are
    skipped: a bare blank illustrates nothing, but a null the measurement
    can explain (issue #99) is exactly the case a doc page should be able
    to show, not the case to hide.
    """
    ranked = [
        t for t in all_tickers
        if not per_ticker or per_ticker.get(t) is not None or per_ticker_reason.get(t) is not None
    ]
    if not ranked:
        ranked = list(per_ticker or all_tickers)

    ordered = ([example_stock] if example_stock in ranked else []) + [
        t for t in ranked if t != example_stock
    ]
    return ordered[:MAX_TICKERS]


def _sample_inputs(measurement, etf_id, all_tickers, sample_tickers) -> list[dict]:
    """One entry per getter the measurement declares in `uses_inputs`."""
    entries = []
    for name in measurement.uses_inputs:
        spec = INPUT_REGISTRY.get(name)
        if spec is None:
            # Guarded by a test, so this is belt-and-braces: a doc page
            # should degrade rather than 500 on a stale name.
            continue

        # Sampled over the WHOLE fund, then cut down — never computed over
        # the sampled tickers. Correlation's derived statistics (each
        # ticker's average ρ, the hub, the strongest pair) are properties
        # of the full set: computing them over five holdings produces
        # numbers that contradict `per_ticker` on the very same page.
        # The measurement's own run() has already warmed the cache for
        # this, so asking for the full input costs nothing extra.
        raw = spec["sample"](etf_id, all_tickers)
        sample, truncated = truncate(raw, sample_tickers, all_tickers)
        entries.append({
            "name": name,
            "description": spec["description"],
            "defaults": spec["defaults"],
            "sample": sample,
            "truncated": truncated,
        })
    return entries


# ── Truncation ───────────────────────────────────────────────────────────────

def truncate(value, sample_tickers, all_tickers) -> tuple[object, bool]:
    """Cut `value` down to something a doc page can show.

    Returns (cut value, whether anything was dropped). Ticker-keyed
    structures are filtered to `sample_tickers` so every part of the
    example is about the same few holdings; everything else is capped by
    length. `all_tickers` is how a ticker-keyed structure is recognised:
    a dict whose keys are all holdings of this fund is an index, not a
    record with fields.

    Filtered structures come back in `sample_tickers` order rather than
    their own, so every table in a worked example lists the same holdings
    in the same order and a reader can follow one ticker across the input,
    the computed value and the rendered cell by reading straight down.
    """
    sample = set(sample_tickers)
    order = {ticker: i for i, ticker in enumerate(sample_tickers)}
    universe = set(all_tickers)

    def walk(node):
        if isinstance(node, str):
            if len(node) > MAX_STRING_CHARS:
                return node[:MAX_STRING_CHARS].rstrip() + "…", True
            return node, False

        if isinstance(node, dict):
            if node and all(isinstance(k, str) and k in universe for k in node):
                kept = {k: node[k] for k in sorted(
                    (k for k in node if k in sample), key=lambda k: order[k]
                )}
                dropped = len(kept) < len(node)
                out = {}
                for k, v in kept.items():
                    out[k], child_dropped = walk(v)
                    dropped = dropped or child_dropped
                return out, dropped
            out, dropped = {}, False
            for k, v in node.items():
                out[k], child_dropped = walk(v)
                dropped = dropped or child_dropped
            return out, dropped

        if isinstance(node, (list, tuple)):
            items = list(node)
            if items and all(
                isinstance(i, (list, tuple)) and i and i[0] in universe for i in items
            ):
                kept = sorted((i for i in items if i[0] in sample),
                              key=lambda i: order[i[0]])
                dropped = len(kept) < len(items)
            elif items and all(isinstance(i, str) and i in universe for i in items):
                kept = sorted((i for i in items if i in sample), key=lambda i: order[i])
                dropped = len(kept) < len(items)
            elif len(items) > MAX_LIST_ITEMS:
                kept, dropped = items[:MAX_LIST_ITEMS], True
            else:
                kept, dropped = items, False

            out = []
            for item in kept:
                walked, child_dropped = walk(item)
                out.append(walked)
                dropped = dropped or child_dropped
            return out, dropped

        return node, False

    return walk(value)
