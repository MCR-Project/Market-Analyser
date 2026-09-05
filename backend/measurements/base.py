"""
Base class for all measurement plugins.

Every measurement is a self-describing unit that declares:
  - What it computes (id, name, description)
  - How to reach it (route) — always scoped by etf_id alone; a
    measurement fetches its own inputs (via measurements/inputs/*) using
    whatever internal defaults it wants, never parameters the frontend
    has to know to supply
  - How it appears in the table (column_key, column_label)
  - Whether it's filterable and what filter UI to show (filterable, filter_type, filter_options)
  - Where its long-form documentation lives (doc_path) — a .mdx file next
    to its own module, loaded by measurements/docs.py
  - How to sort it (sort_type, sort_order)
  - How to render a single value for display (render_cell) — a small MDX/
    JSX snippet using the frontend's shared component vocabulary (Bar,
    Stat, Badge — see app/src/components/ui/MdxCell.jsx), so the frontend
    never needs format-specific rendering logic; it just compiles and
    displays whatever component tree is returned

The registry auto-discovers all subclasses (official + addon), registers
their routes on the FastAPI router, and exposes a manifest so the
frontend can discover what measurements are available at runtime.
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
    # How this measurement's per-ticker value appears as a column
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

    # ── Schemas ──────────────────────────────────────────────────────────
    # input_schema is now always just {"etf_id": ...} in practice — kept
    # for API introspection (shown in the frontend's measurement picker).
    input_schema: dict = {}
    output_schema: dict = {}

    # ── Lifecycle ────────────────────────────────────────────────────────

    @abstractmethod
    def fetch_inputs(self, etf_id: str, **_) -> dict:
        """Gather the raw data needed for computation.

        Must use this measurement's own measurements/inputs/* getters
        (holdings, etf_info, correlation_matrix, ...) rather than calling
        services.market_data directly. `etf_id` is the only thing ever
        supplied by the caller — any other knobs (lookback period,
        thresholds, etc.) are this measurement's own fixed choice, not
        something the frontend passes in.
        """
        ...

    @abstractmethod
    def compute(self, inputs: dict) -> dict:
        """Run the measurement logic on fetched inputs.

        Must return a dict with at least a "per_ticker" key:
          {"per_ticker": {"NVDA": value, "AAPL": value, ...}, ...extra_data}
        Values here are raw (numbers, strings) — used for sorting and
        filtering. Display formatting happens separately, in render_cell.
        """
        ...

    @abstractmethod
    def render_cell(self, ticker: str, value) -> str:
        """Render one ticker's raw value as a small MDX/JSX snippet, using
        the frontend's shared component vocabulary, e.g.:
          <Bar value={0.35} label=".35" />
          <Stat text="7.9%" />

        This is the only place formatting logic lives. The frontend
        receives this string per ticker (see run()'s "per_ticker_mdx"),
        compiles it, and renders the resulting component tree directly —
        it never needs to know this measurement's `format` or branch on
        it. Return "—" (or similar) for a missing/None value.

        This executes as real JSX in the browser, so only ever build this
        string from measurement-authored literals and already-computed
        numeric/string values — never interpolate unescaped external text
        (e.g. a fetched company description) into it.
        """
        ...

    def run(self, **params) -> dict:
        """Full pipeline: fetch inputs → compute → render each cell → return result."""
        inputs = self.fetch_inputs(**params)
        result = self.compute(inputs)
        per_ticker = result.get("per_ticker", {})
        result["per_ticker_mdx"] = {
            ticker: self.render_cell(ticker, value)
            for ticker, value in per_ticker.items()
        }
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
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }
