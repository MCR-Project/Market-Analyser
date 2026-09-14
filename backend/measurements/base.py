"""
Base class for all measurement plugins.

Every measurement is a self-describing unit that declares:
  - What it computes (id, name, description)
  - How to reach it (route) — scoped by etf_id alone, plus a window for a
    plugin that declares one (window_options — issue #101); a measurement
    fetches its own inputs (via measurements/inputs/*) using whatever
    internal defaults it wants otherwise, never parameters the frontend
    has to know to supply beyond those two
  - How it appears in the table — one column (column_key, column_label,
    ...) or several (columns — issue #100); resolved_columns normalises
    either into the same list every other method reads from
  - Whether it's filterable and what filter UI to show (filterable, filter_type, filter_options)
  - Where its long-form documentation lives (doc_path) — a .mdx file next
    to its own module, loaded by measurements/docs.py, shared by every
    column this plugin provides
  - How to sort it (sort_type, sort_order)
  - How to render a single value for display (render_cell) — a small MDX/
    JSX snippet using the frontend's shared component vocabulary (Bar,
    Stat, Badge — see app/src/components/ui/MdxCell.jsx), so the frontend
    never needs format-specific rendering logic; it just compiles and
    displays whatever component tree is returned. Told which column it is
    rendering, since a multi-column plugin's columns can read the same
    raw value differently
  - Optionally, why a given holding's value is null (compute()'s
    per_ticker_reason — issue #99), so a dash on a sixty-row table with
    twenty-five columns says which of "too little history", "not listed
    yet", "no row in ticker" or the like it is, instead of leaving that to
    be guessed at

A plugin providing several columns from one computation (upside/downside
capture, a return and its own momentum) declares `columns` instead of
the single-column attributes, and its `compute()` keys `per_ticker` (and,
where present, `per_ticker_reason`) one level deeper, by column key
first. See `columns`/`resolved_columns` and `run()` below for the exact
shape either way — a single-column plugin's own code is unaffected by
any of this (issue #100): it declares `column_key` and returns a flat
`per_ticker` exactly as it always has.

A plugin whose number *means* a stretch of history (volatility, a
trailing return, a rolling correlation) declares `window_options` and
`window_default` instead of leaving `window_options` empty (issue #101).
`etf_id` is no longer the only parameter a caller supplies to such a
plugin — the registry generates a `window` query parameter for it, one
shared value the whole table sends to every window-aware column at once,
never a per-plugin one. `run()` validates whatever `window` it is handed
(falling back to `window_default` rather than erroring) before it ever
reaches `fetch_inputs`, so a plugin's own code can trust the value is
always one of its own `window_options` — and must fold it into whatever
cache key its own inputs read through, or two different windows will
silently share one cached answer. A plugin that declares no window (every
official one, today) is entirely unaffected: no query parameter is
generated for it, and `fetch_inputs` never receives one.

The registry auto-discovers all subclasses (official + addon), registers
one route per plugin on the FastAPI router, and exposes a manifest with
one entry per column so the frontend can discover what is available at
runtime without ever needing to know which plugin provides it.
"""

import inspect
from abc import ABC, abstractmethod
from pathlib import Path


class MeasurementBase(ABC):
    """Abstract base for measurement plugins."""

    # ── Identity ─────────────────────────────────────────────────────────
    id: str = ""
    name: str = ""
    description: str = ""
    route: str = ""

    # Which set this plugin was registered in — "official" or "addon".
    # Set by measurements/__init__.py when it builds ALL_MEASUREMENTS,
    # since that barrel is the only place that knows; the documentation
    # page groups its sidebar on it.
    origin: str = ""

    # ── Documentation ────────────────────────────────────────────────────
    # Long-form docs live in a .mdx file next to this measurement's module
    # (correlation.py → correlation.mdx); see measurements/docs.py for the
    # file format. Shipping no doc file is supported — the page falls back
    # to the metadata above.
    #
    # Optional overrides for the ETF/stock a doc's worked example is
    # computed against, for measurements a specific fund illustrates
    # better than the repo-wide DOCS_EXAMPLE_* defaults in config.py. A
    # doc's own frontmatter overrides these in turn.
    example_etf: str = ""
    example_stock: str = ""

    # Which measurements/inputs/* getters fetch_inputs() draws on, by
    # registry name (see inputs/__init__.py). Imports alone can't be
    # introspected, so this is what lets a doc page say where the numbers
    # came from and what those getters quietly default to. Naming a getter
    # that doesn't exist fails the test suite.
    uses_inputs: list = []

    # ── Table column config ──────────────────────────────────────────────
    # How this measurement's per-ticker value appears as a column. A
    # single-column plugin declares the five attributes below, exactly as
    # every measurement did before issue #100. A plugin providing several
    # columns from one computation declares `columns` instead — a list of
    # dicts, each shaped like {"key", "label", "width", "default_enabled",
    # "filterable", "filter_type", "filter_options", "filter_min",
    # "filter_max", "filter_step", "sort_type", "sort_order"} — the same
    # fields as below, one dict per column. Read `resolved_columns`, never
    # these attributes or `columns` directly, so the two declaration styles
    # are indistinguishable to every caller.
    columns: list[dict] = []

    column_key: str = ""          # field name in the per-ticker output dict
    column_label: str = ""        # short header text for the table column
    column_width: int = 110       # column width in px
    default_enabled: bool = False # whether this measurement is active on load

    # ── Filter config ────────────────────────────────────────────────────
    # Defines what filter UI the frontend renders in the filter row.
    # Filtering always compares against the raw `per_ticker` value, never
    # the rendered markdown, so the frontend still needs no format-specific
    # logic here — it just compares numbers/strings.
    filterable: bool = False
    filter_type: str = "none"     # "range", "choices", "search", "none"
    filter_options: list = []     # for "choices": [{value, label}, ...]
    filter_min: float = 0         # for "range": min slider value
    filter_max: float = 1         # for "range": max slider value
    filter_step: float = 0.05     # for "range": slider step

    # ── Sort config ──────────────────────────────────────────────────────
    # Defines how the frontend may order rows by this column (again,
    # always against the raw `per_ticker` value).
    #   "numerical"   — compare per_ticker values as numbers (default)
    #   "alphabetical" — compare per_ticker values as strings
    #   "custom"      — use `sort_order` to rank categorical values
    sort_type: str = "numerical"
    # For sort_type="custom": the row order to use for a *descending* sort,
    # e.g. ["LOW", "MED", "HIGH"]. Ascending sort is the reverse of this list.
    sort_order: list = []

    # ── Window config (issue #101) ──────────────────────────────────────
    # Empty by default: `etf_id` is the only thing this plugin needs, and
    # the registry generates no `window` query parameter for it. A plugin
    # whose number means a stretch of history opts in by setting both to
    # real values — typically `config.MEASUREMENT_WINDOW_OPTIONS` /
    # `MEASUREMENT_WINDOW_DEFAULT` outright, so it shares the one
    # vocabulary the frontend's single table-wide control offers, though a
    # metric that genuinely cannot answer over part of that range may
    # declare a narrower subset instead. Same shape as `filter_options`:
    # [{"value": "1y", "label": "1Y"}, ...].
    window_options: list[dict] = []
    window_default: str = ""

    def window_label(self, window: str) -> str:
        """The display label for one of this plugin's `window_options`
        values, or the raw value itself if it names none of them — a
        caller handed something outside `window_options` has already
        strayed from the contract `run()` otherwise guarantees, and
        showing it verbatim beats hiding the mismatch."""
        return next((o["label"] for o in self.window_options if o["value"] == window), window)

    # ── Schemas ──────────────────────────────────────────────────────────
    # input_schema is now always just {"etf_id": ...} in practice — kept
    # for API introspection (shown in the frontend's measurement picker).
    # Describes the plugin as a whole, so every column it provides shares
    # the same schema in the manifest.
    input_schema: dict = {}
    output_schema: dict = {}

    @property
    def resolved_columns(self) -> list[dict]:
        """This plugin's columns, normalised to one shape regardless of
        which way it declared them.

        A `columns` list, when the subclass provides one, is returned
        exactly as declared — that is the multi-column case (issue #100).
        Otherwise the five single-column attributes above are wrapped
        into a list of one, which is what makes declaring `column_key`
        the way every measurement did before this issue exactly
        equivalent to a `columns` list of length one: nothing here or in
        `run()` treats the two declarations differently once past this
        property.
        """
        if self.columns:
            return self.columns
        return [{
            "key": self.column_key,
            "label": self.column_label,
            "width": self.column_width,
            "default_enabled": self.default_enabled,
            "filterable": self.filterable,
            "filter_type": self.filter_type,
            "filter_options": self.filter_options,
            "filter_min": self.filter_min,
            "filter_max": self.filter_max,
            "filter_step": self.filter_step,
            "sort_type": self.sort_type,
            "sort_order": self.sort_order,
        }]

    # ── Lifecycle ────────────────────────────────────────────────────────

    @abstractmethod
    def fetch_inputs(self, etf_id: str, **_) -> dict:
        """Gather the raw data needed for computation.

        Must use this measurement's own measurements/inputs/* getters
        (holdings, etf_info, correlation_matrix, ...) rather than calling
        services.market_data directly. `etf_id` is the only thing every
        caller supplies; a plugin that declares `window_options` (issue
        #101) additionally receives `window` — already validated against
        those options by `run()`, so this can trust it rather than
        re-checking — and must include it in whatever cache key its own
        reads use, or two different windows will answer from one shared
        cache entry. Anything else (a threshold, an interval) is this
        measurement's own fixed choice, not something the frontend passes
        in.
        """
        ...

    @abstractmethod
    def compute(self, inputs: dict) -> dict:
        """Run the measurement logic on fetched inputs.

        A single-column plugin (the `column_key` shorthand — see
        `resolved_columns`) must return a dict with at least a
        "per_ticker" key, keyed directly by ticker, exactly as every
        measurement did before issue #100:
          {"per_ticker": {"NVDA": value, "AAPL": value, ...}, ...extra_data}

        A plugin declaring `columns` (two or more) keys "per_ticker" one
        level deeper, by column key first — one fetch and one compute
        serving every column at once, which is the entire point of
        letting a plugin declare several (issue #100):
          {"per_ticker": {"up_capture": {"NVDA": v, ...},
                          "down_capture": {"NVDA": v, ...}}, ...extra_data}

        Either way, values are raw (numbers, strings) — used for sorting
        and filtering. Display formatting happens separately, in
        render_cell.

        May also return "per_ticker_reason" (issue #99), the same shape
        per_ticker_mdx already has and nested the same way per_ticker is
        for a multi-column plugin:
          {"per_ticker_reason": {"NVDA": "fewer than 30 overlapping daily
                                  returns (12 available)", ...}}
        One entry per ticker whose per_ticker value is null, naming why —
        optional, since a measurement with nothing useful to say about its
        own nulls returns none. run() keeps only the entries that actually
        line up with a null per_ticker value (within the same column, for
        a multi-column plugin); a reason beside a real value would be
        misleading, since the frontend takes a reason's presence as proof
        the value is absent rather than re-checking per_ticker itself.

        A reason reaches the browser exactly as written and is rendered
        into the same MDX/JSX path per_ticker_mdx is (see render_cell,
        and app/src/components/ui/MdxCell.jsx) — build it only from
        measurement-authored literals and already-computed values, never
        from fetched or user text.
        """
        ...

    @abstractmethod
    def render_cell(self, ticker: str, value, column_key: str) -> str:
        """Render one ticker's raw value as a small MDX/JSX snippet, using
        the frontend's shared component vocabulary, e.g.:
          <Bar value={0.35} label=".35" />
          <Stat text="7.9%" />

        This is the only place formatting logic lives. The frontend
        receives this string per ticker (see run()'s "per_ticker_mdx"),
        compiles it, and renders the resulting component tree directly —
        it never needs to know this measurement's `format` or branch on
        it. Return "—" (or similar) for a missing/None value.

        `column_key` is which of this plugin's `resolved_columns` is being
        rendered — a single-column plugin's own `column_key` every time,
        so its implementation can accept and ignore the parameter. A
        multi-column plugin uses it to read the same value differently
        per column (issue #100): upside capture might colour green above
        100%, downside capture green below it.

        This executes as real JSX in the browser, so only ever build this
        string from measurement-authored literals and already-computed
        numeric/string values — never interpolate unescaped external text
        (e.g. a fetched company description) into it.
        """
        ...

    def run(self, **params) -> dict:
        """Full pipeline: fetch inputs → compute → render each cell → return result.

        A single-column plugin's response is completely unaffected by
        issue #100 - flat "per_ticker"/"per_ticker_mdx" keyed directly by
        ticker, exactly as before. A multi-column plugin's "per_ticker"
        (see compute()) is already keyed by column, so per_ticker_mdx is
        built the same way, one column at a time, each with its own
        render_cell(..., column_key) call; per_ticker_reason, where
        present, is filtered within each column independently, against
        that column's own nulls rather than another column's.

        per_ticker_reason (issue #99) is left out of the result entirely
        when compute() doesn't set one — every official measurement,
        today — so a plugin that has nothing to say about its own nulls
        returns exactly the response it always has. When compute() does
        set one, it is filtered down to tickers whose per_ticker value is
        actually null: a reason attached to a ticker that also has a real
        value would contradict what the frontend is entitled to assume
        (that a reason means the value beside it is absent), so a
        measurement author's mistake there is dropped rather than shipped.

        For a plugin declaring `window_options` (issue #101): whatever
        `window` this was called with is validated here, once, before
        `fetch_inputs` ever sees it - missing, unrecognised, or simply
        absent because the caller (examples.py, a test, the HTTP route
        for a plugin with no window at all) never passed one, all resolve
        to `window_default` rather than raising. That is the fallback the
        acceptance criteria ask for, and centralising it here means
        `fetch_inputs` can treat `params["window"]` as already trustworthy
        instead of re-validating it. The resolved value is echoed back as
        the top-level "window" key, which is what lets a caller (the
        table, a doc page's worked example) state which window actually
        produced the numbers it is showing. A plugin with no window
        options is untouched: no "window" key in, none out.
        """
        if self.window_options:
            allowed = {option["value"] for option in self.window_options}
            window = params.get("window")
            params = {**params, "window": window if window in allowed else self.window_default}

        inputs = self.fetch_inputs(**params)
        result = self.compute(inputs)
        if self.window_options:
            result["window"] = params["window"]
        per_ticker = result.get("per_ticker", {})
        columns = self.resolved_columns

        if len(columns) == 1:
            key = columns[0]["key"]
            result["per_ticker_mdx"] = {
                ticker: self.render_cell(ticker, value, key)
                for ticker, value in per_ticker.items()
            }
            if "per_ticker_reason" in result:
                result["per_ticker_reason"] = {
                    ticker: reason
                    for ticker, reason in (result["per_ticker_reason"] or {}).items()
                    if per_ticker.get(ticker) is None
                }
            return result

        per_ticker_reason_in = result.get("per_ticker_reason") or {}
        per_ticker_mdx: dict[str, dict] = {}
        per_ticker_reason_out: dict[str, dict] = {}
        for column in columns:
            key = column["key"]
            column_values = per_ticker.get(key, {})
            per_ticker_mdx[key] = {
                ticker: self.render_cell(ticker, value, key)
                for ticker, value in column_values.items()
            }
            column_reasons = per_ticker_reason_in.get(key)
            if column_reasons:
                per_ticker_reason_out[key] = {
                    ticker: reason
                    for ticker, reason in column_reasons.items()
                    if column_values.get(ticker) is None
                }
        result["per_ticker_mdx"] = per_ticker_mdx
        if per_ticker_reason_out:
            result["per_ticker_reason"] = per_ticker_reason_out
        return result

    # ── Documentation ────────────────────────────────────────────────────

    @property
    def doc_path(self) -> Path:
        """Where this measurement's .mdx doc lives: its own module, .mdx.

        Resolved from the concrete subclass's module file rather than from
        a declared path, so an addon author gets the convention for free —
        drop volatility.mdx next to volatility.py and it is picked up.
        """
        return Path(inspect.getfile(type(self))).with_suffix(".mdx")

    @property
    def has_doc(self) -> bool:
        """Whether a doc file actually exists. Shipping none is supported."""
        return self.doc_path.is_file()

    def manifest(self) -> dict:
        """Return the self-describing metadata for the registry endpoint."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "route": self.route,
            "origin": self.origin,
            "has_doc": self.has_doc,
            "uses_inputs": self.uses_inputs,
            "column_key": self.column_key,
            "column_label": self.column_label,
            "column_width": self.column_width,
            "default_enabled": self.default_enabled,
            "filterable": self.filterable,
            "filter_type": self.filter_type,
            "filter_options": self.filter_options,
            "filter_min": self.filter_min,
            "filter_max": self.filter_max,
            "filter_step": self.filter_step,
            "sort_type": self.sort_type,
            "sort_order": self.sort_order,
            "window_options": self.window_options,
            "window_default": self.window_default,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }
