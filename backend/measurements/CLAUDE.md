# backend/measurements — the column plugin system

Every column in the dashboard's holdings table comes from a measurement plugin: a
self-contained class that fetches its own inputs, computes a value per holding,
decides how that value is drawn, and ships its own documentation. The registry
discovers them and the frontend builds its columns from the manifest, so **adding
a measurement requires no frontend change at all.**

A plugin usually provides one column, declaring `column_key` directly — but it
may instead declare `columns`, a list of several (issue #100), when more than one
comes out of a single computation it would otherwise have to run twice: upside
and downside capture, a return and its own momentum, the two halves of a
correlation comparison. Whichever way a plugin declares its columns, the manifest
still ends up with one entry per column and **adding a second column to an
existing plugin still requires no frontend change** — see "Multiple columns from
one plugin" below.

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
   `default_enabled`), the filter and sort config, and the schemas — or, for more
   than one column, `columns` instead (see below). If the number means a stretch
   of history, also set `window_options`/`window_default` (see "Choosing a
   window" below) — most plugins leave these empty and take none.
3. Implement `fetch_inputs(etf_id, **_)`, `compute(inputs)` and
   `render_cell(ticker, value, column_key)`.
4. Name every `inputs/` getter it draws on in `uses_inputs`. Imports cannot be
   introspected, so this list is what lets a doc page say where the numbers came
   from — and naming a getter that does not exist **fails the test suite**.
5. Add the instance to `OFFICIAL_MEASUREMENTS` (or `ADDON_MEASUREMENTS`).
6. Copy `DOC_TEMPLATE.mdx` to `volatility.mdx` **next to the module** and fill it
   in. Shipping no doc is supported — the page falls back to the manifest
   metadata — but it leaves the column unexplained.
7. Optionally, declare `author`/`author_url`/`version` on the class (or in the
   doc's own frontmatter, which wins — issue #114). A plugin declaring neither
   shows as unattributed in the picker and on its doc page, not credited to
   whoever owns this repository — attribution is opt-in, not assumed.

## The three methods

**`fetch_inputs`** must go through `measurements/inputs/*`, never
`services.market_data` directly. `etf_id` is the thing every caller supplies;
any other knob (a threshold, an interval) is the measurement's own fixed
choice, not a query parameter the frontend has to know about — with one
exception. A plugin whose number *means* a stretch of history declares
`window_options` (issue #101) and additionally receives `window`, already
validated by `run()` before `fetch_inputs` ever sees it. That is why every
measurement route is `/{something}/{etf_id}`, optionally plus `window`, or
takes no path params at all, and why `registry._make_handler` generates
exactly those four signatures. See "Choosing a window" below.

**`compute`** returns a dict with at least `per_ticker`:
`{"per_ticker": {"NVDA": 0.72, …}, …extra}`. These values are **raw** — numbers
and strings — because they are what the frontend sorts and filters on. No
formatting here. A plugin declaring `columns` (two or more) nests this one level
deeper, by column key first — see "Multiple columns from one plugin" below.

It may also return `per_ticker_reason` (issue #99): `{"NVDA": "fewer than 30
overlapping daily returns (12 available)", …}`, one entry per ticker whose
`per_ticker` value is `null`, naming why. Optional — a measurement with
nothing useful to say about its own nulls returns none, which is every
official measurement today; adding one is not "changing what counts as
null", only explaining a null that already exists. `run()` keeps an entry
only where it actually lines up with a null `per_ticker` value, so a stray
reason next to a real value never reaches the response. A reason string
reaches the browser exactly as written and down the same MDX rendering path
`render_cell`'s output does (`app/src/components/ui/MdxCell.jsx`) — build it
only from measurement-authored literals and already-computed values, never
from fetched or user text, the same rule the root `CLAUDE.md`'s invariant 6
states for `render_cell` itself.

**`render_cell`** returns a small MDX/JSX string using the shared cell
vocabulary — `<Bar value={0.35} label=".35" />`, `<Stat text="$61.8B" />`,
`<Badge text="…" />`, `<Spark values={[...]} baseline={0} label="…" />` (issue
#106 — see "Spark: a path, not a level" below) — implemented in
`app/src/components/ui/MdxCell.jsx`. This is the **only** place formatting
lives; the frontend compiles the string and renders the tree without ever
branching on a per-measurement `format`. Return `"—"` for a missing value.
`column_key` is which column is being rendered — a single-column plugin's own
key every time, so its implementation can accept and ignore the parameter; a
multi-column plugin uses it to read the same raw value differently per column.

Unlike the documentation vocabulary in `app/src/components/docs/DocMdx.jsx`
(a stable contract — see that page's own docs, and `app/CLAUDE.md`'s "MDX:
two vocabularies, deliberately separate"), **this one is expected to keep
changing.** Adding a component here is a normal, low-risk change; nothing
downstream depends on the set staying fixed the way a written doc does.

That string is executed as real JSX in the browser. Build it only from
measurement-authored literals and already-computed numbers or strings — never
interpolate fetched text (a company description, an API field) into it.

### Spark: a path, not a level (issue #106)

`Bar`/`Stat`/`Badge` each draw one number. Some metrics are not levels but
paths — two holdings can both return 42% over a year, one grinding upward and
the other flat for ten months before a jump, and as a single number they are
interchangeable. `<Spark values={[...]} baseline={0} label="…" />` draws the
series itself as a small line, no text inside the SVG (`preserveAspectRatio=
"none"` would distort any glyph, the same rule every chart in this app
follows — see `app/CLAUDE.md`'s "No text inside a stretched SVG").

**The scalar-companion rule: a `<Spark>` column still needs a plain number in
`per_ticker` to sort and filter by.** `TableView.jsx`'s sort/filter logic
reads only `per_ticker` — it has no idea `per_ticker_mdx` exists, let alone
that one column's snippet happens to carry a series — so a plugin rendering
`<Spark>` must decide what single number represents that path for ranking
purposes (a final value, a slope, an average) the same way every other
column already has to. This is not new machinery, just a rule worth stating
once here rather than leaving each plugin author to rediscover it: nothing
about a series-valued cell changes `compute()`'s contract, which still
returns exactly one scalar per ticker in `per_ticker`.

`label` is a plugin-authored sentence describing the path in words (e.g.
`"rose from .05 to .34, mostly in Q3"`) — there is nothing legible to put
inside the SVG itself, so this is the only text associated with the cell,
surfaced as a tooltip and real accessible text, not a glyph. An unavailable
series is handled exactly like any other null value: `render_cell` returns
`"—"` rather than a `<Spark>` with nothing to draw — there is no
Spark-specific null case to implement.

`run()` ties the three together and adds `per_ticker_mdx` alongside `per_ticker`
(and `per_ticker_reason`, filtered down to actual nulls, when `compute` set one).

**When the scalar genuinely isn't enough to draw the path** (issue #110's
Rolling Correlation, the first official measurement to actually hit this):
`run()`'s generic dispatch calls `render_cell(ticker, value, column_key)`
with *only* `per_ticker[ticker]` — there is no second channel for a series
`compute()` may have worked out along the way. A plugin needing one
returns it as an extra, undocumented key in `compute()`'s own result dict
(`rolling_correlation.py`'s `"_rolling_series"`) — `run()` never touches or
strips keys it doesn't know about, so it survives untouched — and overrides
`run()` itself to call `super().run(**params)` first (reusing its window
resolution and reason-filtering exactly as every other plugin gets it for
free), then pops that private key and rebuilds `per_ticker_mdx` from the
real series instead of the generic one-scalar-at-a-time pass. `render_cell`
still has to exist (the ABC requires it) and still has to produce something
sensible on its own — `rolling_correlation.py`'s reconstructs an honest,
if degenerate, two-point line straight from the scalar it *was* given,
never a fabricated shape — since nothing stops it being called in
isolation. Never reach for `self` to smuggle a series from `compute()` to
`render_cell` instead: a plugin instance is one shared singleton serving
every request (`measurements/__init__.py`'s `OFFICIAL_MEASUREMENTS`), and
`registry.py`'s route handlers are plain `def`s, which Starlette runs in a
threadpool — two concurrent requests for different ETFs really can
interleave, and instance state one of them writes is state the other can
read mid-request.

## Multiple columns from one plugin (issue #100)

Upside and downside capture, a return and its own momentum, the two halves of a
correlation comparison — several of the metrics this system is growing to hold
come in pairs from a single computation. Forcing each half into its own plugin
would mean a duplicated identity block, a duplicated `.mdx`, and a duplicated
upstream fetch for data a sibling already has in hand. A plugin declares
`columns` instead when this applies:

```python
columns = [
    {"key": "up_capture", "label": "UP CAPTURE", "width": 100,
     "default_enabled": True, "filterable": True, "filter_type": "range",
     "filter_options": [], "filter_min": 0, "filter_max": 2, "filter_step": 0.05,
     "sort_type": "numerical", "sort_order": []},
    {"key": "down_capture", "label": "DOWN CAPTURE", "width": 110,
     "default_enabled": False, "filterable": False, "filter_type": "none",
     "filter_options": [], "filter_min": 0, "filter_max": 2, "filter_step": 0.05,
     "sort_type": "numerical", "sort_order": []},
]
```

Never read `columns` (or the single-column attributes) directly — call
`self.resolved_columns` instead, which normalises either declaration style into
the same list of dicts. That is what makes the two styles indistinguishable to
`run()`, and it is why a single-column plugin's own code is completely
unaffected by any of this: declaring `column_key` the way every measurement did
before this issue is exactly equivalent to a `columns` list of length one.

`compute()`'s shape follows `resolved_columns`' length: one column keeps
`per_ticker` flat, exactly as always; two or more nests it one level deeper, by
column key first, computed together in one `fetch_inputs`/`compute` pass rather
than one per column. `run()` mirrors the same nesting into `per_ticker_mdx`
(calling `render_cell(ticker, value, column_key)` once per cell) and, where
present, `per_ticker_reason` — each column's reasons are filtered against that
column's *own* nulls, so a real value in one column is never shadowed by a
reason that belongs to its sibling.

`registry._column_manifest_entries` is what the manifest actually sends: one row
per column, built from the plugin's own `manifest()` with that column's fields
overlaid, plus `measurement_id` naming the plugin that computes it. A
single-column plugin's one row keeps `id` equal to the plugin's own id —
already unique — which is the entire reason the three official measurements'
manifest rows are unaffected by this beyond the addition of `measurement_id`
itself; a multi-column plugin's rows are namespaced `f"{plugin.id}.{column
key}"` so its own columns cannot collide with each other or an unrelated
plugin. The route stays **one per plugin** (`_make_handler` is unchanged) — only
the manifest fans out, which is what lets the frontend toggle columns
individually while still fetching each plugin exactly once
(`app/src/hooks/useMeasurements.js` groups active columns back into the set of
plugins that actually need fetching before it issues a single request per one).

## Choosing a window (issue #101)

Nothing in the UI used to say the CORRELATION column was a year of daily
returns — `inputs/correlation_matrix.py` itself notes as much. That is fine
for one column; it stops being fine the moment there are columns for
volatility, a trailing return and momentum, where the window *is* the
meaning of the number. "Volatility 31%" over an unstated period is not a
fact anyone can use.

A plugin opts in by setting `window_options` and `window_default` — normally
straight from `config.MEASUREMENT_WINDOW_OPTIONS` /
`MEASUREMENT_WINDOW_DEFAULT`, so it shares the one vocabulary the frontend's
single table-wide control offers, though a metric that genuinely cannot
answer over part of that range may declare a narrower subset instead:

```python
from config import MEASUREMENT_WINDOW_DEFAULT, MEASUREMENT_WINDOW_OPTIONS

class VolatilityMeasurement(MeasurementBase):
    window_options = MEASUREMENT_WINDOW_OPTIONS
    window_default = MEASUREMENT_WINDOW_DEFAULT
```

**One shared control for the whole table, not one per column.** Two
window-aware columns must never describe different periods — a "1Y"
volatility beside a "5Y" one would be two different claims wearing the same
kind of header. `app/src/hooks/useMeasurementWindow.js` holds the one value
every window-aware column is sent; a column with no `window_options` at all
(every official measurement, today) never receives it and behaves exactly as
it always has.

**`run()` validates the window once, before `fetch_inputs` ever sees it.**
Missing, unrecognised, or simply absent because the caller never passed one
(a test, `examples.py`'s worked example, the HTTP route for a plugin with no
window at all) — all of it resolves to `window_default` rather than raising.
A plugin's own `fetch_inputs` can therefore trust `window` is always one of
its own `window_options`, and **must fold it into whatever cache key its own
reads use** — `services/market_data.py`'s own functions already key on
`period`, so passing `window` straight through as `period` is usually enough,
but a plugin that caches anything itself has to include it explicitly, or two
different windows will silently share one answer. The resolved value comes
back as the response's own `"window"` key, present only for a window-aware
plugin — which is what lets the table's column header and a doc page's
worked example both state which window actually produced the numbers they
show, via `window_label(value)`.

`registry._make_handler` generates the query parameter (`window: str =
Query(measurement.window_default)`) only for a plugin whose `window_options`
is non-empty; `_column_manifest_entries` carries `window_options`/
`window_default` onto the manifest unchanged (a plugin-level declaration, not
a per-column one, so no per-column overlay is needed the way `column_key` and
friends get).

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

Three more getters reach prices, volume, stock metadata and dividends
(issue #102) — `price_frame`, `stock_info` and `dividend_events` all take a
resolved ticker list rather than an `etf_id`, the same way `correlation_matrix`
does: a measurement first resolves holdings via `inputs.holdings.get_holdings`,
then passes the resulting tickers to whichever of these it also needs, rather
than each getter re-resolving the fund on its own.

- **`price_frame.get_price_frame(tickers, period=DEFAULT_PERIOD,
  include_volume=False)`** — close prices, and optionally volume, for a
  whole fund's holdings in one bulk `services.market_data.get_price_frame`
  read. `DEFAULT_PERIOD` is `config.CORRELATION_PERIOD` — the same window
  the correlation matrix reads — specifically so the two share a cache
  entry (`_price_frame_bundle` in `services/market_data.py`) instead of
  each issuing its own query for the same tickers and window; a plugin
  wanting a different window (a window-aware column — issue #101) pays
  for a genuinely separate read, not a redundant one. `volume` is left off
  the response by default and added only when asked, so a plain
  price-history metric's worked example isn't cluttered with a field it
  never reads. Volume has **no live fallback** — the same reasoning
  `get_dividends` already states applies here too — so it comes back
  `None`, not `0`, for a holding the database has no `prices` rows for at
  all: every ETF, and anything resolved outside the tracked universe. A
  coarse row's volume is a bucket **sum**, not one day's (~21 trading days
  for a monthly bucket — `sql/001_optimize_prices_storage.sql`), so each
  volume entry carries its own `granularity` alongside `date`/`volume`; a
  metric averaging across rows of mixed granularity must divide each by
  the trading time it actually covers (`services/stats.py`'s
  `trading_days`) rather than treat every row as one day's volume.
  `price_frame.get_aligned_closes(tickers, period)` (issue #107) is the
  rectangular sibling: `get_price_frame`'s ragged per-ticker `[[date,
  close], ...]` shape, restricted to the tickers priced for every date in
  the window and aligned to one shared date list — the shape a joint
  calculation (`fund_index`, `risk_contribution`) needs, that neither
  `get_price_frame` nor `services.market_data.get_closes` returns as-is.
- **`stock_info.get_stock_info(tickers)`** — each holding's own name,
  sector, market cap, currency and exchange, one `services.market_data.
  get_stock_info` call per ticker (already cached per ticker, so this is a
  loop of cache lookups rather than a query per holding — there is no
  bulk read to widen here the way `price_frame`'s was).
- **`dividend_events.get_dividend_events(tickers)`** — wraps
  `services.market_data.get_dividends` together with `tracked_tickers`
  rather than exposing either alone: `get_dividends`' own "absent means no
  events in the window" is ambiguous by itself, since a tracked holding
  that genuinely paid nothing and an untracked one (every ETF, and
  anything resolved outside the tracked universe) both come back the same
  way. Returns `{ticker: {"events": [[date, amount], ...], "tracked":
  bool}}` so a measurement can tell the two apart without remembering to
  ask `tracked_tickers` itself — the same distinction
  `services/portfolio.py`'s own `income`/`incomeUnknownFor` already makes
  for the simulator. No window: a measurement wanting a fund's whole
  dividend history reads it in one call rather than one bounded to
  whatever window a price-based column happens to be showing.
- **`fund_index.get_fund_index(tickers, weights, period)`** (issue #107) —
  the fund's own weighted-return index: every "how does this holding relate
  to its fund" column (`risk_contribution`, `fund_relation`,
  `tail_correlation`, `capture_ratio`) needs the same `r_fund` series to
  compare a holding against, and this builds it once rather than each
  plugin constructing (and potentially disagreeing about) its own. Built on
  `price_frame.get_aligned_closes(tickers, period)` — the rectangular
  `(dates, values_by_ticker)` shape a joint calculation needs, restricted to
  tickers priced for every date in the window's own calendar (taken as
  whichever requested ticker has the most priced dates, not their
  intersection — narrowing to the newest holding's own shorter history
  would shrink a year-old fund's window to a few weeks the moment it gained
  one new position, the same reasoning `services/fund_metrics.py` states
  for the same problem, issue #105) — then `services.stats.weighted_index`,
  called directly since `stats.py` is explicitly the one `services/` module
  a measurement may reach past the `measurements/inputs/*` layer for (its
  own docstring states this, issue #98). Weights are renormalised to sum to
  100% over exactly the tickers that made the cut, so a fund whose tracked
  weights sum to less than 100% still gets an index representative of what
  *is* tracked. Returns `{"dates", "values_by_ticker", "fund_values"}` -
  `fund_values` is `None` when fewer than two tickers have a complete
  history to build an index from, which is what every column reading this
  input reports as its own null case for every ticker.

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
- `author` / `author_url` / `version` are optional (issue #114) — who wrote this
  plugin, where to read more about them, and which release it is. Same two-level
  precedence as the examples above (doc's frontmatter, then the class attribute)
  but **no third, repo-wide fallback**: a plugin declaring neither stays
  unattributed rather than defaulting to whoever owns this repository —
  `MeasurementBase.author`/`author_url`/`version` default to `""`, and
  `resolve_attribution` never fills an absent one in from anywhere else. Read the
  resolved value, never `measurement.author` directly, which is why
  `registry.py`'s `_column_manifest_entries` overlays `_resolved_attribution`
  onto every manifest row rather than leaving the class's own raw attribute to
  leak through.
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

For a window-aware plugin (issue #101), `build_example` calls `run()` with no
`window` at all, which resolves to `window_default` — a doc page is never wired
to the table's own control — and copies the resolved `"window"` and its
`window_label(...)` onto the payload, so `WorkedExample.jsx` can say which
window actually produced the numbers on the page rather than leaving the
reader to assume it matches whatever the table happens to be showing.

**A multi-column plugin (issue #100) needs its own branch here** — issue
#107's fund-relation and capture-ratio plugins are the first *official*
measurements to declare `columns`, which is what surfaced this: the original
`build_example` assumed `per_ticker`/`per_ticker_mdx`/`per_ticker_reason`
were flat `{ticker: value}` dicts, the single-column shape, and would have
silently produced an empty or wrong payload for one that nests by column key
first. `_build_multi_column_result` mirrors `_build_single_column_result`
but keys everything by column, and adds a `columns` array (`{key, label}`
per column) so the frontend knows there is more than one series to show per
ticker at all — `WorkedExample.jsx` renders one "computed value + cell" pair
of sub-columns per declared column when it sees that array, instead of the
single flat pair. Which tickers make the sample is still decided once,
across every column together: a ticker earns its row if *any* column has a
real value or a reason for it.

## Registry and routing

`registry.py` parses each `route` for path params, generates a handler with the
right signature — including a `window` query parameter for a plugin that
declares one (issue #101) — and mounts it: one route per **plugin**,
regardless of how many columns it provides. It also serves:

- `GET /api/measurements` — the manifest, one entry per **column**
  (`_column_manifest_entries`, issue #100), not per plugin.
- `GET /api/measurement-docs/{id}` — parsed frontmatter + raw MDX body, by
  plugin id (`measurement_id`) — a doc is shared by every column a plugin
  provides, so there is one `.mdx` per plugin, not per column.
- `GET /api/measurement-docs/{id}/example` — the worked example, likewise by
  plugin id.

The doc endpoints are **not** at `/api/measurements/{id}/doc` on purpose: plugin
routes live under the same `/api` prefix, and
`/measurements/correlation/{etf_id}` would happily match `etf_id="doc"`,
shadowing the endpoint for exactly one measurement.

**`_column_manifest_entries` also resolves attribution (issue #114)**, once per
plugin via `_resolved_attribution` (not once per column — every column a
multi-column plugin provides carries the identical author/author_url/version,
which is what lets the frontend's `AttributionCard` group them under one card
rather than crediting a two-column plugin's halves separately). It loads the
plugin's own doc the same way `GET /api/measurement-docs/{id}` does, but catches
`DocError` and falls back to the class's own unresolved attribution rather than
letting one malformed `.mdx` 500 the whole manifest — that failure belongs to
this one plugin's own doc endpoint, which every other plugin's picker does not
depend on.

Three outcomes for a doc request, deliberately distinct: no such measurement →
404 (stable, do not retry); measurement with no `.mdx` → 200 with
`has_doc: false` and synthesised frontmatter; `.mdx` present but malformed → 500
naming the file and the problem, because it was hand-written to be read and
failing loudly beats dropping it.

`DataUnavailable` and `SymbolNotFound` are re-raised untouched from every handler
so `main.py` maps them to 503/404. Swallowing them into a generic 500 made
`useMeasurements` retry three columns against a non-existent ticker every three
seconds, long after the ETF request itself had correctly given up.
