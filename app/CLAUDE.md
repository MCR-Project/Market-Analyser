# app — React frontend

React 19, Vite 8, Tailwind 4, `react-router` 8, Vitest for the little that is
unit-tested. No state library, no component library.

```bash
npm install
npm run dev      # or preview_start {name: "app"} — prefer that
npm run lint     # ESLint: react-hooks + react-refresh
npm test         # Vitest, once (`vitest run`) - pure logic only, see "Tests" below
npm run build
```

Talks to `http://localhost:8000/api` unless `VITE_API_BASE` is set (see
`.env.example`). `app/dist/` is build output and is not tracked.

Alternatively, `docker compose up` from the repo root runs this with HMR in a
container (`app/` bind-mounted, `node_modules` a separate named volume — see
the README's "Running it with Docker"); `docker compose run --rm tests lint`
and `... tests frontend` run the ESLint and Vitest checks the same way
`tests`'s other CLAUDE.md documents.

## Layout

```
src/main.jsx                 router; every route wrapped in one AppLayout
src/App.jsx                  the dashboard shell (/etf/:etfId/:view)
src/index.css                design tokens, theme, keyframes, scrollbar styling
src/utils/api.js             the whole API client: dedup, TTL cache, ApiError
src/utils/candles.js         rows -> candles, and where a candle sits; chartTooltip.js builds the hover readout (both pure, both tested)
src/utils/freshness.js       what the header says about the daily fetch job: the four states and their words (pure, tested)
src/utils/windowCalendar.js  what a typed or clicked date does to the portfolio window, the calendar's month grid and keyboard (pure, tested; issue #156)
src/utils/windowPresets.js   what each window preset button means in dates, and their order (pure, tested; issue #156)
src/hooks/                   data fetching and view state
src/store/                   useEtfStore (URL-backed), portfolioStorage, portfolioLink, portfolioBackup, candlePreference (+ their tests)
src/views/                   one file per route or tab panel
src/components/
  layout/    AppLayout, Header, FreshnessBadge
  ui/        Loading, ErrorState, Overlay, ViewTabs, TimeframeTabs, SegmentedControl, MdxCell, MeasurementPicker, MetricsPicker, AttributionCard, DocLink, Logo
  charts/    PriceChart (line or candles), AreaChart, CandleChart, CandleToggle, BrushOverlay, ChartTooltip
  etf/       EtfDashboard, EtfPicker, SectorZone, FundMetricsCard
  stock/     StockPopup, StocksSidebar, StockMetricsCard (issue #159)
  docs/      DocsSidebar, MeasurementDoc, DocMdx, WorkedExample
  portfolio/ the portfolio simulator UI — see its own CLAUDE.md
```

## The URL is the state

There is no global store of what is on screen. Anything that should survive a
reload or travel in a link lives in the URL, and there is only ever one copy of
the answer (the one exception is a display preference that is neither a view of
the data nor worth a link: see "Price charts and candles"):

| In the URL | Read by |
| --- | --- |
| `/etf/:etfId/:view` | `useEtfStore`, `App` |
| `/docs/:measurementId` | `DocsPage` |
| `/portfolio/:portfolioId` | `PortfolioPage` |
| `/portfolio/shared?p=…` | `portfolioLink.decodePortfolio` |
| `/stock/:ticker` | `StockPage` (issue #158) |
| `?tf=` (on `/stock/...`) | `StockPage`'s own `useTimeframeParam` — the price chart's 1W/1M/1Y/5Y timeframe; unrelated to `?window=` below, which scores the Metrics card's Run instead |
| `?window=` / `?start=&end=` (on `/portfolio/...` **and** `/stock/:ticker`) | `useSimulationWindow` — a preset (`1m`, `3m`, `6m`, `1y`, `5y`, `ytd`, `max`) or an exact window; on the Stock page (issue #159) it scores the basket-of-one Run `StockMetricsCard` reads, the same hook and the same keys, just a different route reusing them |
| `?stockMetrics=` (on `/stock/...`) | `useStockMetrics` — which of the Stock page's metric tiles are on (issue #159); its own key so it cannot collide with `/portfolio/...`'s `?metrics=` or `/etf/...`'s `?fundMetrics=` |
| `?compare=` (on `/portfolio/...`) / `?benchmark=` | `useComparison` — `?compare=` a comma-separated list of saved portfolio ids |
| `?compare=` (on `/stock/:ticker`) | `useStockComparison` — a *different* shape behind the same key (issue #160): at most one raw ticker symbol, never a list, structurally — anything that doesn't match one symbol's shape (including a comma-separated attempt) reads as no comparison at all. The two never collide since they live on different routes with disjoint id spaces (a saved portfolio's id there, a live ticker here) |
| `?rf=` (on `/portfolio/...`) | `useRiskFreeRate` — an override for the risk-free rate a run is scored against (issue #103); absent or unusable falls back to the tracked series |
| `?risk=` (on `/portfolio/...`) | `usePortfolioRisk` — which `computed_from="risk"` tiles are on, on `PortfolioRiskCard` (issue #113); its own key so it cannot collide with `?metrics=` or `?fundMetrics=` |
| `?window=` (on `/etf/...`) | `useMeasurementWindow` — a different param of the same name, scoped to its own route; see below |
| `?fundMetrics=` (on `/etf/...`) | `useFundMetrics` — which fund metrics card tiles are on (issue #105); its own key so it cannot collide with `/portfolio/...`'s `?metrics=` |
| `?networkClusters=` (on `/etf/...`) | `useNetworkClusters` — whether the network view outlines its clusters (issue #144): `on`, absent when off (the default); anything other than `on` reads as off |
| `?matrixOrder=` / `?matrixWithin=` (on `/etf/...`) | `useMatrixOrder` — the Matrix tab's order (`cluster` default, `alpha`, `weight`) and, inside a cluster, `weight` (default) or `alpha` (issue #143); each omitted at its default, an unrecognised value read as the default via `readChoice` |

`useEtfStore` used to be a zustand store; moving it into the route param removed
the sync problem entirely — any component, however deep, calls `useEtfStore()`
and reads the same `etfId`. Follow that pattern rather than lifting state or
prop-drilling.

Two rules that come with it:

- **Never replace the whole query string.** `setSearchParams` does exactly that,
  which silently drops whatever else lives there. Always go through
  `utils/searchParams.js`'s `withParams(current, changes)`; a null/empty value
  deletes its key rather than writing an empty one.
- **Canonicalise rather than error.** `App` redirects `/etf/smh` → `/etf/SMH` and
  drops an unrecognised view slug, with `replace` so Back does not bounce off the
  URL just left. An unusable window falls back to the default preset. A bad link
  should open the app, not a complaint about itself.

## Fetching: `utils/api.js` + `useFetch`

`api.js` deduplicates by request key — the path, or `POST path body` for the
simulator, since two simulations of different portfolios hit the same URL and are
different answers. Concurrent callers share one in-flight request; a 2s TTL cache
absorbs siblings that each call their own hook on the same render.

Aborts are **ref-counted**, and the final abort is deferred by a task. One
component unmounting must not cancel a request other components are still waiting
on, and a cleanup immediately followed by a remount in the same tick (React
StrictMode's dev double-invoke) re-attaches to the live entry instead of
re-issuing. Aborting synchronously instead meant every request went out twice in
dev — the browser cancelled the first, but the server had already done the work,
doubling exactly the cold-start load that makes the upstream sources flake.

`useFetch(fetcher, deps, { fallback })` returns `{ data, loading, error, retry }`.
Three things about it:

- **`deps` must be primitives.** They are used two ways that must agree: collapsed
  into a JSON key during render to reset stale data, and spread into the effect's
  dependency array, which React compares with `Object.is`. Those only agree for
  primitives. Pass `list.join(',')`, not the list. A dev-only `console.warn`
  catches violations.
- **A transient failure auto-retries on a shared backoff schedule**
  (`utils/retrySchedule.js`, issue #92); a stable one never does. "Transient"
  is `isTransientError`: a network `TypeError`, or 429/5xx. This is what makes
  a cold start heal itself — the backend binds its port well before Yahoo or
  Supabase will answer it, so the requests that lose that race come back
  503, not as connection failures. A 404 is a stable answer and must not
  retry. The schedule starts at 3s and doubles up to a 60s cap — never
  shorter than the failed response's own `Retry-After` (`ApiError.retryAfter`
  in `utils/api.js`), which can be longer than 3s when the backend itself is
  in a rate-limit cooldown rather than merely still booting — and gives up
  after `MAX_AUTO_RETRIES` (8) consecutive failures, at which point
  `error.retriesExhausted` is set so the UI can stop claiming to retry.
  Flat 3s retries were the right fit for a cold start, which clears in
  seconds, but the wrong one for Yahoo rate-limiting the backend's shared
  cloud IP, which can take a full minute — retrying every 3s the whole time
  was exactly the traffic that kept the block in place.
- `retry(true)` marks that one attempt as forced, recorded against the attempt
  number rather than as a consumable flag — StrictMode invokes the effect twice
  and a consumed flag left the second (the one the UI shows) unforced. Any
  call to `retry()` — forced or not — also resets the auto-retry budget above,
  since a deliberate click should always get a fresh attempt.

`useMeasurements` fetches outside `useFetch` (one request per active measurement,
keyed off a diff) and therefore reimplements the same retry rule by hand,
including the shared schedule and cap — a measurement whose requests keep
failing stops retrying and renders as failed rather than staying in `loading`
forever. If you add another such path, reimplement it too — inheriting no
retry is how columns stayed permanently blank after a cold start.

`useMeasurementWindow` (issue #101) holds the one window every window-aware
column shares, and `useMeasurements(etfId, window)` is what actually decides,
per column, whether to send it — `App.jsx` wires the two together. Changing
the window is a third kind of refetch trigger alongside a toggle and an ETF
change, and the narrowest one: only the plugins behind an *active*
window-aware column refetch, found via `columnsByMeasurement` the same way
the response-shape lookup already is. `TableView`'s `MeasurementWindowControl`
only renders once some active column actually has a window to control —
before any window-aware plugin ships, it renders nothing, which is correct:
a control that changes nothing today is clutter, not a feature.

`useRiskFreeRate` (issue #103) is the same idea for the portfolio simulator's
`?rf=` override: `PortfolioPanel` merges its `request` alongside
`useSimulationWindow`'s own before calling `usePortfolioSimulation`, so a
`?rf=` already reaches the backend and travels in a share link (`PortfolioPage`'s
`SHARED_VIEW_PARAMS`) — but there is no visible control reading it yet. No
figure on screen depends on the rate today (Sharpe/Sortino are their own,
later issue), so a control here would be exactly the clutter
`MeasurementWindowControl`'s own gating avoids; it arrives once a metric
tile actually has a rate to show next to its own figure.

**Never render stale or invented data on failure.** Gate on `loading`/`error`,
show `<Loading>` then `<ErrorState {...describeFetchError(error)} onRetry={retry} />`.
`describeFetchError` distinguishes 404 ("check the symbol, this will not resolve
on its own") from 5xx, and within 5xx, whether it's still auto-retrying
("the backend is running, the source behind it did not answer, retrying") or
has given up (`error.retriesExhausted` — points at the Retry button instead of
promising a recovery the schedule has stopped chasing). Sending someone to
check a server that is already up is a dead end. A network-level failure has
no status and gets `ErrorState`'s own defaults, which are worded for the
dashboard ("Live market data could not be loaded"); a page whose content is
not market data passes `{ unreachable: { title, message } }` as the second
argument to say what it actually needs the backend for — `DocsPage` does
(issue #141). Only that case is overridable; the 404 and 5xx wording is not.

## Rendering conventions

- **Adjust state during render, not in an effect,** when it must follow a prop —
  `App` clearing the selection on ETF change, `useFetch` clearing stale data,
  `MdxCell` clearing a stale error. The linked React doc is cited at each site.
  An effect paints the stale value for a frame first.
- **`memo` the leaf components** that re-render on every parent tick
  (`AreaChart`, `DetailAside`, `MatrixView`, …), and `useCallback`/`useMemo`
  anything that feeds a `useFetch` dep array or a chart's geometry.
- **Views are self-contained.** `MatrixView` and `NetworkView` fetch their own
  ETF, correlation and sector data and own their own toolbars; only
  `selected`/`onSelect` are passed in, because the highlighted stock has to
  survive switching tabs (`ViewTabs` unmounts the inactive panel).
- **No text inside a stretched SVG.** The charts use
  `preserveAspectRatio="none"` and would distort any glyph; every label is HTML
  positioned over the top.
- **Drawings size to their measured box, not a constant** (issue #139). Growing
  a chart with CSS stretches it, so a drawing that should get *bigger* on a big
  screen measures instead: `useElementSize` for a box that fills its panel
  (`NetworkView` lays its nodes out in it, `MatrixView` sizes its cells to it),
  `useFillHeight` for a plot that should end at the bottom of the first
  screenful (`PortfolioChart`, `ComparisonChart`). Both return callback refs,
  so a view that shows a loading state first starts measuring when the real
  box mounts. The measured element must be sized by its container, never by
  what is drawn in it, or the drawing and the measurement chase each other.
- **Wide screens reflow at `2xl` (1536px), and content caps at a 2400px
  window.** Below `2xl` both the dashboard and the portfolio page keep their
  stacked order; at `2xl` the ETF card and fund metrics card share a row
  (`App.jsx`) and the portfolio panel puts its holdings beside its results
  (`PortfolioPanel.jsx`). The cap goes on the content *inside* each scrolling
  area, never on the area itself, so the sidebar stays at the window's left
  edge and the scrollbar at its right.

## Price charts and candles (issue #152)

The three charts that draw one ticker's price — `EtfDashboard`, `StockPopup` and
`portfolio/HoldingChartPopup` — all render `charts/PriceChart`, which is the one
place that picks between the line (`AreaChart`) and candles (`CandleChart`) and
owns the hover that goes with each. A host passes what `useLiveSeries` returns
(`arr`, `dates`, `candles`) and the timeframe; it does not touch `useChartHover`
or `ChartTooltip` itself. The portfolio's own charts are not price charts and do
not take part: a simulated value has no open, high or low.

- **One switch, one store.** `store/candlePreference.js` holds whether candles are
  on; `hooks/useCandles` subscribes to it; `charts/CandleToggle` is the button,
  the same one beside all three timeframe controls. Do not copy the value into a
  component's state — a popup opening over the fund card has to change the card
  behind it, and that only works because both read the store. It is deliberately
  **not in the URL** (it is a way of looking, not a view of the data, and would
  only clutter a Share Link), unlike `?networkClusters=`. `localStorage` access is
  inside a `try` and a refused write still holds for the session, the same rule as
  `portfolioStorage`. The button stays on a read-only portfolio's popup: it writes
  nothing.
- **A candle is not a row.** `utils/candles.js`'s module docstring states the model:
  one span per timeframe (day for 1W/1M, week for 1Y, month for 5Y), coarse stored
  rows covering their whole bucket, edge candles drawn with the days they actually
  hold, and a gap — never a flat candle — wherever an open, high or low is missing.
  Change the rules there and in the README's "Candles on the price charts" together.
- **The line and the figures never change with the switch.** `arr`/`dates` are one
  entry per row the API answered and everything that is not a candle reads only
  those: the header return %, the line, its colour. `buildTooltip` measures a
  candle's return since the start from the first *row's* close for the same reason.
  `candles` comes from the same request as `arr`, so the switch costs no fetch.
- **`CandleChart` and `AreaChart` are interchangeable in a slot**: same 360-unit
  plot, same hover surface, no text inside the SVG. The chart draws candles at
  `candleCentre(i, count)` and the hover finds them with `candleIndexAt` — both from
  `utils/candles.js`, so they cannot disagree about which candle is where.

## The header's freshness (issue #154)

The header says whether the data comes from a recent run of the daily fetch job.
`AppLayout` owns the fetch (`hooks/useFreshness`), `utils/freshness.js` decides
the state and the words, and `layout/FreshnessBadge` draws it beside the theme
button. Unlike the LIVE badge — a fact a page publishes through `useLiveStatus`
because it is about that page's own data — this is one figure for the whole
database, so the layout reads it itself, and only once the app is on a page that
reads prices: not on `/docs`, and no request at all if the app opens there.

- **The backend names the deadline; the browser compares.** `GET /api/freshness`
  answers `finishedAt`, `dueBy` and `failed`; `freshnessState(now, record)` asks
  whether `now` has reached `dueBy`. No schedule or calendar logic belongs in the
  client — a weekend is just a `dueBy` on Tuesday morning. `now` is the browser's
  clock when the answer arrived or when the tab last came back into view,
  whichever is later — read in the fetcher and in an event handler, never during
  render.
- **Four states, in this precedence:** unknown (grey), behind (red, `--color-danger`),
  last run had failures (amber), on schedule (green). A null in any of the three
  fields is unknown, never a guess — a null `failed` is not "nothing failed". A
  failed request reads as unknown too; nothing renders while the first request is
  in flight, so the header does not flash "unknown" on every load.
- **One request per load: no timer, no polling.** The page is reloaded well inside
  a day, the only rate this figure changes at. The cost, accepted: a tab left open
  across a late run keeps what it first read until it is reloaded. `useFetch`'s own
  503 retries still apply; `useFreshness` latches "failed once" itself, because
  `useFetch` clears `error` at the start of each retry and the badge would
  otherwise flicker between unknown and nothing.
- **Fetching once is not judging once.** The record is re-*judged* — no request —
  against the browser's clock each time the tab returns to view (`focus`,
  `visibilitychange`), so a tab left open for days turns to behind and its age
  moves on when looked at, instead of a green "Refreshed 30m ago" that stopped
  being true. That is an event handler, not a timer, and it is where the clock is
  read; never call `Date.now()` during render (`react-hooks/purity`). The hook's
  result is memoised so `Header`'s `memo` still holds.
- **The dot shows at every width; only its words hide** (`sr-only md:not-sr-only`),
  so a warning does not vanish on a phone. The tooltip's exact local time and the
  line saying this is *not the date of the latest close* are in a real `sr-only`
  span as well as the `title`, which is not reliably announced.
- **It is not the `stale` flag** on the ETF response (holdings from the live
  fallback), and not the date of the latest close: a market holiday adds no
  prices and the job still ran.

## MDX: two vocabularies, deliberately separate

Both compile backend-authored source into real React components at runtime, which
is safe **only** because measurement code and doc files are first-party and
reviewed like any other code. Never build either from fetched or user text.

- `components/ui/MdxCell.jsx` — `Bar`, `Stat`, `Badge`, `Spark` (issue #106).
  Designed for a ~110px table cell; expected to keep changing with the table —
  unlike the doc vocabulary below, adding a component here is a normal, low-risk
  change. The backend picks *what* to render, this file owns how it looks, so
  every measurement looks consistent without the frontend branching on a format
  field. Compiled components are cached by source string; a failed compile is
  evicted so a transient failure does not poison the cache. `MdxCell` also takes
  an optional `reason` prop (issue #99), a measurement-authored explanation for
  a `null` value — same trust boundary as the MDX itself, never built from
  fetched or user text — surfaced as a native `title` tooltip **and** a separate
  `sr-only` span with real text, not `title` alone: it is not reliably announced
  to a screen reader. No `reason` is a plain dash with no tooltip at all, not one
  with nothing in it. Every place that renders a `per_ticker_mdx` cell
  (`TableView`, `WorkedExample`) should pass the matching `per_ticker_reason`
  entry alongside it.
  - **`Spark` draws a series, not a single value** — a column showing a *path*
    (issue #106): two holdings can average the same return while one climbed
    steadily and the other spiked once, and `Bar` (one magnitude) can't tell
    them apart. `values` is the series in drawing order; `baseline` (default 0)
    is always included in the drawn vertical range, so a series that never
    crosses it still shows how far it stayed away rather than being rescaled to
    fill the cell. **A `<Spark>` column still needs a plain number to sort and
    filter by** — `TableView`'s sort/filter logic reads only `per_ticker`, never
    `per_ticker_mdx`, so a plugin rendering `<Spark>` names a scalar for that the
    same way every other column already does (`backend/measurements/CLAUDE.md`'s
    own "Spark: a path, not a level" section states the same rule from the
    backend side). `label` is a plugin-authored sentence describing the path in
    words; there is nothing legible to put inside the stretched SVG, so it
    surfaces as a tooltip and `sr-only` text, the same convention `reason` above
    follows, never as a glyph inside the `<svg>`. An unavailable series is an
    ordinary null: `render_cell` returns `"—"` rather than a `<Spark>` with
    nothing to draw, so there is no separate empty-series case to handle here.
- `components/docs/DocMdx.jsx` — `Note`, `Warning`, `Formula`, `WorkedExample`,
  plus the prose elements MDX produces. **A stable contract**: adding a component
  is fine, changing or removing one breaks every doc already written. Doc MDX
  never references the cell vocabulary — except inside `<WorkedExample />`, whose
  whole claim is "this is what the table shows".

The docs route is `lazy()`-loaded in `main.jsx`: KaTeX and its fonts are about a
third of the bundle and are only needed once someone opens a measurement's
documentation.

**A multi-column measurement's doc id is its plugin id, not any one column's**
(issue #107, first exercised by a real official measurement — the mechanism
existed since issue #100 but nothing had shipped `columns` yet). The manifest
carries one row per *column*, namespaced `fund_relation.beta` and so on, but
there is one `.mdx` and one worked example per *plugin* — `DocLink` in
`TableView` already links to the plugin id (`measurement_id`), so `DocsPage.jsx`
resolves `/docs/:measurementId` by exact `id` first (a portfolio metric, or a
single-column measurement, where the two are equal anyway) and falls back to
`measurement_id` — without that fallback, the exact link every multi-column
column header's "?" sends a reader to 404s. `DocsSidebar.jsx` dedupes its own
list the same way (one link per `measurement_id`, not one per column) so a
three-column plugin doesn't list its own name three times. `MeasurementDoc.jsx`
takes the *full* set of that plugin's manifest rows as `columns` so its "In the
table" reference panel can show each column's own header/sort/filter rather
than just the first one silently standing in for all of them; `WorkedExample.jsx`
does the matching thing for the result table, reading a `columns` array off the
payload (issue #107 also taught `examples.py` to send one) to render one
"computed value + cell" pair of sub-columns per declared column instead of one
flat pair.

## Styling

Tailwind 4 via `@tailwindcss/vite`, with the design system as CSS variables in
`index.css`. `@theme` holds the raw palette (`--color-neutral-*`, `--color-violet-*`,
`--color-sky-*`, semantic success/warning/danger/info), radii, durations and
fonts; `:root` and `:root[data-theme="light"]` map those onto the semantic tokens
components actually use: `--bg`/`--bg-1..3`, `--fg`/`--fg-1..3`, `--accent*`,
`--negative*`, `--border*`, `--shadow-*`.

Write `bg-[var(--bg-1)]`, `text-[var(--fg-2)]` — **never a raw hex or a bare
Tailwind colour class** in a component. `--negative` is mirrored against
`--accent` in each theme (violet accent → sky negative, and the reverse) so an
inverse correlation always reads as visually distinct from a positive one.

Dark is the `:root` default; light is opt-in via `data-theme="light"` on `<html>`,
which `index.html` sets and `useTheme` maintains. `useTheme` resolves an explicit
stored choice first, then `prefers-color-scheme`, then the passed default.

## Tests

`npm test` runs Vitest over `src/**/*.test.js`, and the suite is small on
purpose: **pure logic only**, plain `test()` functions over inline data, no DOM
environment, no component or hook tests. The first file is
`store/portfolioBackup.test.js`, which exercises `planImport` — the function that
decides what importing a Backup does — through its public interface and
round-trips Export back through it (issue #148). Issue #150 added
`store/portfolioStorage.test.js` (`migratePortfolio`, `makePortfolio` and
`scheduleFields`: what a saved portfolio's money-flow schedule may be) and
`store/portfolioLink.test.js` (`encodePortfolio` / `decodePortfolio`: a Share
Link's payload versions, and what a payload with both schedules does) — the first
tests the link module had. Issue #152 added `utils/candles.test.js` (`toCandles`,
`candleLabel` and where a candle sits), `utils/chartTooltip.test.js`
(`buildTooltip`: what hovering a line, a candle and a gap says) and
`store/candlePreference.test.js` (the one switch, including storage that throws).
Issue #154 added `utils/freshness.test.js` (`freshnessState` and `describeFreshness`:
the four states, their precedence, the boundary at `dueBy`, and the words).
Issue #156 added `utils/windowCalendar.test.js` (`editWindow`, `parseTypedDate`,
`pickableRange`, `monthGrid` and `moveFocus`: what a typed or clicked date does to the
window, which days the calendar offers and where the keyboard goes) and
`utils/windowPresets.test.js` (`presetWindow` and `PRESETS`; the date is passed in, so
nothing fakes the clock).

The pattern to follow: put the rules in a module that touches no storage, no
network and no DOM, give it one public function, and test behaviour through that
function alone — never generated ids by value, only that a fresh one differs from
every existing one. Like the backend's, a test here may not touch the network.
Hooks, dialogs and pages stay thin and are checked by using the running app.
`npm run lint` still covers everything, tests included.

## Accessibility

Every full-screen dialog goes through `components/ui/Overlay.jsx`, which supplies
`role="dialog"`, `aria-modal`, an accessible name, Escape-to-close from any
descendant, a Tab/Shift+Tab focus trap, and focus restoration to the trigger on
unmount (issue #24). Do not hand-roll a backdrop.

`DocLink` is always a **sibling** of the control it sits beside, never nested
inside it — the column header is a sort button and an anchor inside a button is
both invalid HTML and a reliable way to sort a column you meant to read about.
