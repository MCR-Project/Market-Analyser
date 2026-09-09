# backend/measurements — the column plugin system

Every column in the dashboard's holdings table is a measurement plugin: a
self-contained class that fetches its own inputs, computes a value per holding,
decides how that value is drawn, and ships its own documentation. The registry
discovers them and the frontend builds its columns from the manifest, so **adding
a measurement requires no frontend change at all.**

```
base.py                       MeasurementBase — the contract
registry.py                   auto-registers routes, serves the manifest and the docs
__init__.py                   ALL_MEASUREMENTS = official + addon, each tagged with its origin
official_measurements/        first-party plugins (correlation, etf_weight, value_held) + their .mdx
addon_measurements/           plugged-in plugins; currently empty
inputs/                       one getter per distinct piece of fetched data, each self-describing
docs.py                       .mdx loading and frontmatter validation
examples.py                   the worked example behind a doc page
DOC_TEMPLATE.mdx              copy this to start a doc
```

## Adding a measurement

1. Create `official_measurements/volatility.py` (or `addon_measurements/` for a
   plugged-in one).
2. Subclass `MeasurementBase`. Fill in the identity (`id`, `name`, `description`,
   `route`), the column config (`column_key`, `column_label`, `column_width`,
   `default_enabled`), the filter and sort config, and the schemas.
3. Implement `fetch_inputs(etf_id, **_)`, `compute(inputs)` and
   `render_cell(ticker, value)`.
4. Name every `inputs/` getter it draws on in `uses_inputs`. Imports cannot be
   introspected, so this list is what lets a doc page say where the numbers came
   from — and naming a getter that does not exist **fails the test suite**.
5. Add the instance to `OFFICIAL_MEASUREMENTS` (or `ADDON_MEASUREMENTS`).
6. Copy `DOC_TEMPLATE.mdx` to `volatility.mdx` **next to the module** and fill it
   in. Shipping no doc is supported — the page falls back to the manifest
   metadata — but it leaves the column unexplained.

## The three methods

**`fetch_inputs`** must go through `measurements/inputs/*`, never
`services.market_data` directly. `etf_id` is the **only** thing a caller ever
supplies; any other knob (a lookback period, a threshold) is the measurement's
own fixed choice, not a query parameter the frontend has to know about. That is
why every measurement route is `/{something}/{etf_id}` or takes no params at all,
and why `registry._make_handler` only generates those two signatures.

**`compute`** returns a dict with at least `per_ticker`:
`{"per_ticker": {"NVDA": 0.72, …}, …extra}`. These values are **raw** — numbers
and strings — because they are what the frontend sorts and filters on. No
formatting here.

**`render_cell`** returns a small MDX/JSX string using the shared cell
vocabulary — `<Bar value={0.35} label=".35" />`, `<Stat text="$61.8B" />`,
`<Badge text="…" />` (implemented in `app/src/components/ui/MdxCell.jsx`). This is
the **only** place formatting lives; the frontend compiles the string and renders
the tree without ever branching on a per-measurement `format`. Return `"—"` for a
missing value.

That string is executed as real JSX in the browser. Build it only from
measurement-authored literals and already-computed numbers or strings — never
interpolate fetched text (a company description, an API field) into it.

`run()` ties the three together and adds `per_ticker_mdx` alongside `per_ticker`.

## Inputs

`inputs/` exists so a measurement can fetch everything from an `etf_id` while its
documentation can still state what the getter quietly assumed — nothing in the UI
says a correlation is a year of daily returns.

Each module exports a getter **and** an `INPUT_SPEC` with three keys:

- `description` — one paragraph a reader can act on.
- `defaults` — the internal choices (`{"period": "1y", "interval": "1d"}`).
- `sample(etf_id, tickers)` — the real value for one ETF, for the worked example.

Register it in `inputs/__init__.py`'s `INPUT_REGISTRY`; the keys there are what
`uses_inputs` names.

`correlation_matrix`'s sampler is the odd one: it takes tickers rather than an
`etf_id`, and it must be given the **full** holdings list. Its averages and hub
are properties of the whole set — recomputing them over the five sample tickers
would print numbers contradicting the measurement's own output on the same page.

## Documentation files

A measurement's doc lives beside its module, named after it: `correlation.py` →
`correlation.mdx`. `doc_path` resolves from the concrete subclass's own file, so
an addon dropped into `addon_measurements/` gets the convention for free with
nothing central to register. The app serves it at `/docs/<measurement id>`.

Format: YAML frontmatter, then free-form MDX.

- `title` and `summary` are **required**.
- `example_etf` / `example_stock` are optional and choose what the worked example
  computes against. Precedence, most specific first: the doc's frontmatter, then
  the measurement class's attributes, then `DOCS_EXAMPLE_ETF` /
  `DOCS_EXAMPLE_STOCK` in `config.py`.
- **Unknown keys are rejected, not ignored** — a typo like `exemple_etf` fails
  loudly at the moment it is introduced rather than doing nothing forever.
- Every value must be a string; quote anything that looks like a number or date.
- The body is **not** validated. The five sections in `DOC_TEMPLATE.mdx` are a
  convention that keeps every measurement reading the same way, not a schema.

Available components, beyond standard markdown including GFM tables:
`<Note>`, `<Warning>`, `<Formula>` and `<WorkedExample />`. Write formulas as
``<Formula tex={String.raw`\rho_{ij}`} />`` so backslashes survive.
`<WorkedExample />` is appended automatically when the body does not place it, so
it costs nothing to omit and can be positioned deliberately.

**This vocabulary is a stable contract.** Adding a component is fine; changing or
removing one breaks every doc already written against it. It is defined in
`app/src/components/docs/DocMdx.jsx`, deliberately separate from the cell
vocabulary in `MdxCell.jsx` — cell components are designed for a 110px table cell
and will keep changing, documentation is written once and read for years. The one
exception is `<WorkedExample />`, which *should* track `MdxCell`, because its
whole claim is "this is what the table shows".

Docs are compiled and executed as real JSX in the browser. Safe only because they
are first-party files reviewed like any other code — never build one from
external data.

## Worked examples (`examples.py`)

Two properties are load-bearing:

- **The computed values are real.** `per_ticker` comes from running the
  measurement exactly as the dashboard runs it, over the whole fund, and is only
  *sliced* to the sample tickers afterwards.
- **Everything is truncated, and says so.** Samples are cut to the same few
  tickers, long lists and strings are capped, and anything dropped sets
  `truncated` so the page can say so rather than implying it shows everything.
  Filtered structures come back in `sample_tickers` order, so a reader can follow
  one ticker straight down through input, value and rendered cell.

Nothing here fetches anything the dashboard does not already fetch, so a doc page
view rides the same caches and costs no extra upstream requests.

## Registry and routing

`registry.py` parses each `route` for path params, generates a handler with the
right signature, and mounts it. It also serves:

- `GET /api/measurements` — the manifest.
- `GET /api/measurement-docs/{id}` — parsed frontmatter + raw MDX body.
- `GET /api/measurement-docs/{id}/example` — the worked example.

The doc endpoints are **not** at `/api/measurements/{id}/doc` on purpose: plugin
routes live under the same `/api` prefix, and
`/measurements/correlation/{etf_id}` would happily match `etf_id="doc"`,
shadowing the endpoint for exactly one measurement.

Three outcomes for a doc request, deliberately distinct: no such measurement →
404 (stable, do not retry); measurement with no `.mdx` → 200 with
`has_doc: false` and synthesised frontmatter; `.mdx` present but malformed → 500
naming the file and the problem, because it was hand-written to be read and
failing loudly beats dropping it.

`DataUnavailable` and `SymbolNotFound` are re-raised untouched from every handler
so `main.py` maps them to 503/404. Swallowing them into a generic 500 made
`useMeasurements` retry three columns against a non-existent ticker every three
seconds, long after the ETF request itself had correctly given up.
