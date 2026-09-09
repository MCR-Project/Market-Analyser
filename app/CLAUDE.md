# app — React frontend

React 19, Vite 8, Tailwind 4, `react-router` 8. No state library, no component
library, no test runner.

```bash
npm install
npm run dev      # or preview_start {name: "app"} — prefer that
npm run lint     # ESLint: react-hooks + react-refresh. The only automated check here.
npm run build
```

Talks to `http://localhost:8000/api` unless `VITE_API_BASE` is set (see
`.env.example`). `app/dist/` is build output and is not tracked.

## Layout

```
src/main.jsx                 router; every route wrapped in one AppLayout
src/App.jsx                  the dashboard shell (/etf/:etfId/:view)
src/index.css                design tokens, theme, keyframes, scrollbar styling
src/utils/api.js             the whole API client: dedup, TTL cache, ApiError
src/hooks/                   data fetching and view state
src/store/                   useEtfStore (URL-backed), portfolioStorage, portfolioLink
src/views/                   one file per route or tab panel
src/components/
  layout/    AppLayout, Header
  ui/        Loading, ErrorState, Overlay, ViewTabs, TimeframeTabs, MdxCell, MeasurementPicker, DocLink, Logo
  charts/    AreaChart, BrushOverlay, ChartTooltip
  etf/       EtfDashboard, EtfPicker, SectorZone
  stock/     StockPopup
  docs/      DocsSidebar, MeasurementDoc, DocMdx, WorkedExample
  portfolio/ the portfolio simulator UI — see its own CLAUDE.md
```

## The URL is the state

There is no global store. Anything that should survive a reload or travel in a
link lives in the URL, and there is only ever one copy of the answer:

| In the URL | Read by |
| --- | --- |
| `/etf/:etfId/:view` | `useEtfStore`, `App` |
| `/docs/:measurementId` | `DocsPage` |
| `/portfolio/:portfolioId` | `PortfolioPage` |
| `/portfolio/shared?p=…` | `portfolioLink.decodePortfolio` |
| `?window=` / `?start=&end=` | `useSimulationWindow` |
| `?compare=` / `?benchmark=` | `useComparison` |

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
- **A transient failure auto-retries every 3s**; a stable one never does.
  "Transient" is `isTransientError`: a network `TypeError`, or 429/5xx. This is
  what makes a cold start heal itself — the backend binds its port well before
  Yahoo or Supabase will answer it, so the requests that lose that race come back
  503, not as connection failures. A 404 is a stable answer and must not retry.
- `retry(true)` marks that one attempt as forced, recorded against the attempt
  number rather than as a consumable flag — StrictMode invokes the effect twice
  and a consumed flag left the second (the one the UI shows) unforced.

`useMeasurements` fetches outside `useFetch` (one request per active measurement,
keyed off a diff) and therefore reimplements the same retry rule by hand. If you
add another such path, reimplement it too — inheriting no retry is how columns
stayed permanently blank after a cold start.

**Never render stale or invented data on failure.** Gate on `loading`/`error`,
show `<Loading>` then `<ErrorState {...describeFetchError(error)} onRetry={retry} />`.
`describeFetchError` distinguishes 404 ("check the symbol, this will not resolve
on its own") from 5xx ("the backend is running, the source behind it did not
answer, retrying") — sending someone to check a server that is already up is a
dead end.

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

## MDX: two vocabularies, deliberately separate

Both compile backend-authored source into real React components at runtime, which
is safe **only** because measurement code and doc files are first-party and
reviewed like any other code. Never build either from fetched or user text.

- `components/ui/MdxCell.jsx` — `Bar`, `Stat`, `Badge`. Designed for a ~110px
  table cell; expected to keep changing with the table. The backend picks *what*
  to render, this file owns how it looks, so every measurement looks consistent
  without the frontend branching on a format field. Compiled components are cached
  by source string; a failed compile is evicted so a transient failure does not
  poison the cache.
- `components/docs/DocMdx.jsx` — `Note`, `Warning`, `Formula`, `WorkedExample`,
  plus the prose elements MDX produces. **A stable contract**: adding a component
  is fine, changing or removing one breaks every doc already written. Doc MDX
  never references the cell vocabulary — except inside `<WorkedExample />`, whose
  whole claim is "this is what the table shows".

The docs route is `lazy()`-loaded in `main.jsx`: KaTeX and its fonts are about a
third of the bundle and are only needed once someone opens a measurement's
documentation.

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

## Accessibility

Every full-screen dialog goes through `components/ui/Overlay.jsx`, which supplies
`role="dialog"`, `aria-modal`, an accessible name, Escape-to-close from any
descendant, a Tab/Shift+Tab focus trap, and focus restoration to the trigger on
unmount (issue #24). Do not hand-roll a backdrop.

`DocLink` is always a **sibling** of the control it sits beside, never nested
inside it — the column header is a sort button and an anchor inside a button is
both invalid HTML and a reliable way to sort a column you meant to read about.
