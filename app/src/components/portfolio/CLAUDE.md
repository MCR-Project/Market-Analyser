# app/src/components/portfolio — the portfolio simulator UI

The largest feature in the frontend, and the one with the most conventions that
are invisible from the code alone. Read `README.md`'s "Portfolio simulator"
section and `backend/services/portfolio.py`'s module docstring before changing
anything here — every number on screen is defined by them.

## Where the feature actually lives

It is spread across four directories, so a change often touches all of them:

| File | Role |
| --- | --- |
| `views/PortfolioPage.jsx` | the route: sidebar + panel, saved vs shared, dialogs |
| `store/portfolioStorage.js` | the whole storage layer — read, migrate, write, name |
| `store/portfolioLink.js` | encode/decode a portfolio into a share link |
| `hooks/usePortfolios.js` | the library as React state, write-through |
| `hooks/usePortfolioSimulation.js` | the open portfolio's run |
| `hooks/useComparisonRuns.js` | one run per line on the comparison chart |
| `hooks/useSimulationWindow.js` | the window, held in the query string |
| `hooks/useRiskFreeRate.js` | `?rf=`, an override for Sharpe/Sortino's rate (issue #103) — no visible control yet |
| `hooks/usePortfolioMetrics.js` | the portfolio metric registry manifest, and `?metrics=` (issue #104) |
| `hooks/usePortfolioRisk.js` | the `computed_from="risk"` entries of that same registry, `?risk=`, and the (gated) fetch of `POST /api/portfolio/risk` (issue #113) |
| `hooks/useComparison.js` | `?compare=` and `?benchmark=` |
| `hooks/useChartBrush.js` | dragging a window out of either chart |
| `components/portfolio/*` | everything below |

Components here: `PortfolioPanel` (the container, ~700 lines), `PortfolioSidebar`,
`HoldingsTable`, `HoldingChartPopup` (issue #137), `AddHolding`, `TickerSearchField`, `PortfolioChart`,
`ComparisonChart`, `PortfolioSummary`, `PortfolioRiskCard` (issue #113),
`ComparisonSummary`, `WindowControls`,
`BenchmarkBar`, and the dialogs/notices (`CreatePortfolioDialog`,
`ApplyWeightsDialog`, `DeletePortfolioDialog`, `SharePortfolioDialog`,
`SharedNotice`, `StorageNotice`). `MetricsPicker`, the tile enable/disable
dialog, lives in `components/ui/` (issue #105 moved it there once the ETF
dashboard's fund metrics card needed the same dialog PortfolioSummary
already had).

**`HoldingChartPopup`** (issue #137) is a Holding's own price chart, opened
by clicking its ticker in `HoldingsTable`. It deliberately does not reuse
`components/stock/StockPopup` — that component's correlation-explorer pane
needs an ETF's correlation matrix and full constituent list, and a Holding
has neither (it may not belong to any ETF at all). It duplicates StockPopup's
timeframe-tabs-plus-`AreaChart` pattern rather than sharing it, trading a
little duplication for zero regression risk to the ETF analyzer. Its header
shows the Holding's own WEIGHT/VALUE from the current Run, dimmed under the
same `stale` condition the table's own columns use — no correlation pane, no
income figure, and available identically on read-only (shared) portfolios
since it writes nothing.

## Three principles

**1. A portfolio is a simulation, not an account.** Nothing is bought, nothing is
connected to a broker, and nothing tracks anything anybody owns. Copy that framing
into any new copy you write; the landing text and `SharedNotice` are the model.

**2. Portfolios live in this browser and nowhere else.** `localStorage`, key
`market-analyser.portfolios`. That is a consequence of the backend holding only a
Supabase service key with no sign-in — a server-side table would be one shared,
world-editable list — not a stage on the way to accounts. The trade is stated
plainly in the UI: they do not follow you to another browser, deleting cannot be
undone, a private window keeps nothing. **Do not add a server-side store.**

**3. Storage failure must never white-screen the page.** `portfolioStorage.js`
returns every failure as a status (`ok` / `unavailable` / `corrupt` / `full`) that
`StorageNotice` explains, and never throws — even reading `window.localStorage` is
inside a `try`, because that access is itself what throws when site data is
blocked. A refused write does **not** roll the change back: the session keeps
working with what it has and the page says it is not being saved.

## Migration vs decoding — opposite rules on purpose

- `migratePortfolio` (storage) **salvages what it can.** The alternative is
  silently losing work somebody did. Unknown fields are preserved, so a portfolio
  written by a newer build and opened by an older one comes back intact.
- `decodePortfolio` (link) **refuses the whole payload on the first thing that is
  wrong** — shape, version, name, amount, method, ticker pattern, weight,
  duplicate ticker, size — with the size ceiling checked *before* anything is
  decoded. A link is untrusted input whoever sent it, and showing three quarters
  of somebody's portfolio under their name is worse than an error message.

Both return a *definition*, never something stored. Nothing about a shared link
touches storage until **Save a copy**, which mints an ordinary new portfolio
through `makePortfolio`.

The link payload carries **its own version** (`LINK_VERSION`, currently 2),
independent of `SCHEMA_VERSION` — it is a wire format other people's browsers
have to read, so it changes for its own reasons. Version 1 is still read as a
portfolio with no contribution schedule. Adding a field means bumping
`LINK_VERSION`, adding it to `READABLE_VERSIONS` handling, and keeping the old
shape readable.

Encoding is JSON with single-letter keys, UTF-8, base64url — not
`encodeURIComponent` (percent-escaping roughly doubles a payload that is mostly
braces, and chat clients stop underlining a link at the first character they do
not recognise), and not compressed (a dependency and a second thing that can be
wrong about a hostile input, to save a couple of hundred bytes).

## Read-only is the same component

A shared portfolio renders through `PortfolioPanel` with `readOnly`, not a second
component. It has to simulate, chart and read exactly like a saved one — that is
the whole promise of the link — and two components drawing the same portfolio
would drift. Every control that would write something is **removed rather than
disabled**: a disabled row of buttons invites the reader to work out why they
cannot use them, when the answer is that this portfolio is not theirs yet.

## Editing: applied vs immediate

The amount and the rebalancing method apply as soon as they are chosen — each is
a single decision, made once.

**Weights are not.** They are worked out by comparison across the whole table
("this one up, that one down, does the total still make sense"), so they are
edited freely and applied together with **Recompute**, through
`ApplyWeightsDialog`. A table that re-simulated on every keystroke would spend its
time answering half-written questions, and twenty holdings would cost twenty runs
on the way to one answer. Everything on screen still reacts immediately — the
running total, the over-100 card, Normalize — because those read the numbers being
typed, not the saved ones.

`usePortfolioSimulation`'s 120ms debounce is therefore **not** absorbing a
keystroke storm; it collapses the bursts left over (an amount committed and a
method changed in the same breath, React's dev double-render). `stale` says the
numbers describe the portfolio as it was a moment ago, so the table can dim them
rather than pretend they are current.

A portfolio with nothing to invest — no holdings, or every weight zero — is not
simulated at all. The backend rightly rejects it, and an error card is a strange
way to say "add something".

## The window

Lives in the query string, because it belongs to the view rather than to the
portfolio: the same basket is worth looking at over a year and over a decade, and
neither reading is the portfolio's own property. Three controls write the same
window — presets, the two date boxes, and dragging on either chart — and there is
never a second window that disagrees. Choosing a preset fills the dates; editing a
date drops the preset.

- A date is only sent once it is a **usable** window. A half-typed year is a
  legitimate state of a date input, not a request worth making; an end before its
  start is a 400 the backend would answer. `windowProblem()` mirrors the backend's
  `resolve_window` rules so both are said next to the boxes instead.
- `max` is the one preset with no dates of its own. It travels as a period and
  comes back as the window it turned out to be.
- A drag is applied **on release**, and one shorter than `MIN_ROWS` (4) is refused
  — below that the window is mostly rounding, and a stray click is a zero-length
  drag that would otherwise wipe the window out. The refusal is shown *during* the
  drag (warning colour) rather than sprung at the end.
- Presets push history; retyping a date replaces, so the back button stays useful.

## The portfolio metric registry (issue #104)

`PortfolioSummary` no longer hand-draws its own tiles. Every one — its
label, its family, whether it shows by default, how to draw its value —
is declared by a backend metric class (`backend/portfolio_metrics/`), the
same self-describing-plugin pattern `backend/measurements/` already uses
for the holdings table columns. `usePortfolioMetrics` fetches the
manifest once; `PortfolioSummary` groups the active entries by `family`
and draws each one according to its declared `format`
(`currency`/`currency_signed`/`percent`/`percent_signed`/`drawdown`/`list`)
— it does not know what CAGR means, only that it is `"percent_signed"`.
**Adding a metric to the registry needs no change here** as long as its
shape fits one of those six formats.

- **The two family row headers are also declared data.** `families` in
  the manifest response carries each family's label and note; the
  `THE PORTFOLIO · TIME-WEIGHTED, ...` / `THE ACCOUNT · MONEY-WEIGHTED, ...`
  text on screen is that data, not a hardcoded string.
- **The account row's visibility is the one thing still decided here,
  not by the manifest**: it only renders once `metrics.contributed > 0`
  (issue #67, unchanged) — a fact about *this run*, not something a
  metric declares about itself.
- **The dividend family is never a tile**, on purpose (issue #68): its
  three entries (`dividendIncome`/`dividendYield`/`incomeUnknownFor`)
  declare `tile: false`, so `usePortfolioMetrics`'s `tileMetrics` never
  offers them to the dialog or the grid — `DividendNote` keeps reading
  `metrics.dividendIncome` etc. directly, same as before this issue.
- `?metrics=` is a comma-separated id list, read/written through
  `withParams`/`readList` exactly like every other multi-value URL param
  here — never by replacing the whole query string. An id that is stale,
  unknown, or not `tile`-eligible is filtered out rather than erroring;
  an empty result falls back to the registry's own default set.
- `MetricsPicker` (in "Dialogs" below) is the enable/disable dialog — it
  only ever lists `tileMetrics`, grouped by family.
- **The registry also holds three `computed_from="etf_id"` entries**
  (diversification ratio, top-5 variance share, tracked weight coverage
  — issue #105), fetched from the same `/api/portfolio-metrics` manifest
  but filtered out of `tileMetrics` here — they have no value in a run's
  own response, so offering them in this dialog would toggle on a tile
  that can only ever show a dash. The fund metrics card
  (`app/src/components/etf/FundMetricsCard.jsx`, `hooks/useFundMetrics.js`)
  is the independent consumer that filters the same manifest down to
  those three instead. "Different metrics, one mechanism" is #105's own
  phrase for it — one backend registry, two frontend consumers that each
  filter it to the half they can actually use.
- **A third consumer, `PortfolioRiskCard`/`usePortfolioRisk.js` (issue
  #113), filters the same manifest a third time**, to the three
  `computed_from="risk"` entries (average correlation, effective bets,
  risk share — the last with `tile: false`, so it never reaches this
  card either). Unlike the fund metrics card, its values fetch is
  gated: `usePortfolioRisk` only calls `POST /api/portfolio/risk` once a
  tile on the card is actually switched on, since that read is a wider
  price fetch than `simulate` needs and issue #113's whole reason for
  giving it its own endpoint is to spare a run nobody asked a risk
  question of from paying for it. The fetch is also independent of
  `usePortfolioSimulation`'s own — the same `Promise.allSettled`
  independence "Comparison" below gives each comparison line — so a 503
  here costs only this card's own tiles, never the chart or
  `PortfolioSummary`.

## Comparison

`?compare=<ids>&benchmark=<symbols>`, up to `MAX_LINES` (6) lines including the
primary. Every line is a run of the same endpoint over the same window, which is
what lets a benchmark's return, CAGR, volatility and drawdown sit next to a
portfolio's in one table without any of them meaning something slightly different.

- A **benchmark is deliberately not a portfolio**: a ticker that lives in the URL,
  simulated as a basket of one, given the open portfolio's own amount and
  contribution schedule so the comparison is like with like, and never written to
  the library.
- **Portfolio ids only mean something in the browser that minted them**, so a
  shared comparison link shows the ids it can find and drops the rest rather than
  erroring — and `compare` is deliberately excluded from what a share link carries.
- Runs are fetched together but **settled apart** (`Promise.allSettled`): a
  benchmark whose ticker upsets the price source costs the chart that one line.
  A failed line keeps its row in `ComparisonSummary` and says so — a missing row
  would read as "not compared" when what happened was "could not be priced".
- Results are positional, so a stale set of a different length is not merged; it
  would attach a run to the wrong line for a frame.

## Charts

`PortfolioChart` is a stacked area, one band per holding plus cash, summing to the
total at every date. Four decisions:

- **Colour follows the ticker, not the ranking.** Bands stack largest-first so the
  shape reads bottom-up, but that order changes with the window; colour that
  changed with it would make two windows of one portfolio look like two
  portfolios.
- **Small holdings are grouped, not dropped** — past `MAX_BANDS` (10) the thin
  ones are unreadable and unclickable, so the smallest become one "Other" band
  that still carries their value. Nothing leaves the stack, or it would stop
  adding up.
- **No text inside the SVG** (`preserveAspectRatio="none"` would distort it);
  every label is HTML over the top.
- **Money paid in is a line, not a band.** A funded portfolio climbs whether or not
  anything went up; the paid-in staircase over the stack is what makes the gap to
  the top read as the gain.

`ComparisonChart` defaults to **percent**, and has to: a $1,000 portfolio beside a
$100,000 one is a flat line under a mountain in dollars, and the flat one is not
flat. The dollar toggle is a re-draw of data already in hand, not a refetch.

Its harder constraint: **lines do not share a calendar.** `prices` tiers by age, so
a basket of tracked stocks answers weekly for the 1–5 year band while an ETF
benchmark — no rows of its own, answered live — answers daily throughout; over
five years that is 461 rows against 1254. Each line is positioned **by its dates**,
drawn through its own observations, and read at a hovered date as of its last
observation. Snapping every line onto one shared index left the weekly one as a few
hundred isolated points — an SVG moveto with no lineto draws nothing, so the line
vanished while its values still appeared under the cursor.

## Vocabulary traps

- The API's per-holding `contribution` field is labelled **GAIN** in
  `HoldingsTable`, because the panel above now has contributions in the other
  sense (money paid in on a schedule). Two columns inches apart called the same
  word and meaning opposite things is worse than a label differing from its field.
- **Two families of number, and the split is the point** once contributions are
  on. Total return, CAGR, volatility and max drawdown are time-weighted and
  describe *the portfolio*; paid in, contributed, gain and money-weighted return
  describe *the account*. `PortfolioSummary` splits into two labelled rows and
  `ComparisonSummary` grows a money-weighted column, only when some line is
  actually funded that way. With no contributions the two agree exactly.
- **Dividend income is reported, never added.** It is already inside every value
  through the adjusted closes, so the UI says why the two do not sum rather than
  leaving a reader to wonder.
- **A copied fund is not the fund.** Only constituents weighing ≥1% are tracked,
  and the weights are the fund's *current* ones, so a backdated copy is
  survivorship-biased. `CreatePortfolioDialog` and `PortfolioPanel` say so, and
  `WHOLE_FUND_COVERAGE` (99) is the threshold below which the coverage note
  appears.
- **`null` is not `0`.** A run that cannot support a figure returns null and the UI
  shows a dash. Zero would be a claim, and the wrong one. When the backend can
  say why (`metrics.reasons`, issue #99), `PortfolioSummary`'s `Stat` and
  `ComparisonSummary`'s `ReasonedValue` give that dash a tooltip **and** real
  `sr-only` accessible text — the same convention `MdxCell` follows for a
  measurement column's dash, since a native `title` alone is not reliably
  announced to a screen reader.

## Dialogs

All go through `Overlay` for Escape, focus trap and focus restoration (issue #24).
Each names the specific thing being decided rather than asking "are you sure?"
about nothing in particular — `DeletePortfolioDialog` names the portfolio and says
the delete cannot be undone; `ApplyWeightsDialog` shows old → new per row with the
total before and after.

`SharePortfolioDialog` **shows** the link rather than only copying it: clipboard
writes fail for reasons unrelated to this app (permission, an insecure origin),
and a button reporting success it did not have is worse than no button.

`MetricsPicker` (issue #104; now `components/ui/MetricsPicker.jsx` — issue
#105 moved it there once the ETF dashboard's fund metrics card needed the
same dialog) mirrors `MeasurementPicker.jsx` in that same directory,
simplified: a metric never groups several tiles under one plugin, so
every row is a plain toggle — no schema preview, no multi-column grouping —
grouped by family instead, with the group header read off the manifest's
`families` the same way `PortfolioSummary`'s own row headers are. It stays
available on a read-only (shared) portfolio, unlike the write-action buttons
beside it: choosing which tiles to look at is a view preference, not a write.
Its `eyebrow`/`subtitle`/`ariaLabel`/`emptyText` props default to this
page's own copy; the fund metrics card passes its own.
