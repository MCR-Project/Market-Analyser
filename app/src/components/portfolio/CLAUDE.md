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
| `store/portfolioBackup.js` | export a library or one portfolio to a Backup file, and `planImport` — what importing one would do (issue #148); the one unit-tested module |
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
`SharedNotice`, `StorageNotice`) and, for Backups (issue #148),
`ImportBackupButton` and `ImportResultDialog`. `MetricsPicker`, the tile enable/disable
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

## Three readers of a portfolio — different rules on purpose

- `migratePortfolio` (storage) **salvages what it can.** The alternative is
  silently losing work somebody did. Unknown fields are preserved, so a portfolio
  written by a newer build and opened by an older one comes back intact.
- `decodePortfolio` (link) **refuses the whole payload on the first thing that is
  wrong** — shape, version, name, amount, method, ticker pattern, weight,
  duplicate ticker, size — with the size ceiling checked *before* anything is
  decoded. A link is untrusted input whoever sent it, and showing three quarters
  of somebody's portfolio under their name is worse than an error message.
- `planImport` (Backup, issue #148) **sits between the two**: the file is the
  owner's own choice but may have been edited or passed on. It salvages *per
  entry* through `migratePortfolio`, unchanged, then holds each result to the
  limits migration deliberately does not enforce — 50 holdings
  (`MAX_LINK_HOLDINGS`), no ticker twice, every ticker matching `TICKER_PATTERN`,
  and not both a recurring contribution and a recurring withdrawal (#150) —
  so a portfolio never imports happily and then fails to simulate. A failing entry
  is skipped and *named with its reason*, never quietly trimmed.

**A record with both schedules, in each reader (issue #150, ADR 0002).** A
portfolio pays in or draws out, never both, and the three readers answer a record
that says otherwise the way each already answers anything it cannot take at its
word: `migratePortfolio` drops *both* (a schedule that cannot be read is no
schedule, and preferring either would change the numbers of a portfolio whose
owner never chose to), `decodePortfolio` refuses the whole payload, and
`planImport` skips the entry with a named reason. Migration erases the evidence,
so `planImport` asks `hasBothSchedules` of the entry *as the file wrote it*,
before migrating it — otherwise it would import quietly as a lump sum.
`scheduleFields(portfolio)` is the one place a request's schedule fields are built:
the one the portfolio has, nothing when it has none (never a null, so a portfolio
that never had a schedule keys the same cached request it always did). Only a file that
  is not a Backup, is over 2 MB (checked before it is read), or has nothing
  importable in it is refused whole, and then nothing is written.

The link's readers return a *definition*, never something stored: nothing about a
shared link touches storage until **Save a copy**, which mints an ordinary new
portfolio through `makePortfolio`. A Backup is the opposite in kind — the owner's
own portfolios at full fidelity (id, dates, `source`, unknown fields), which become
ordinary saved portfolios as they are.

### Backups: export, and an import that only adds

`ADR 0001` records the decision; the rules are in `portfolioBackup.js`'s docstring.

- **One envelope**, `{ format, exportedAt, portfolios }`, for the whole library or
  one portfolio (a list of one), so there is one way in. A bare list is also
  accepted — it is what `localStorage` holds. **No envelope version:** each
  portfolio has its own `schemaVersion` and the migration upgrades it, so a second
  number could only disagree with the first. That is the opposite of
  `LINK_VERSION`, which exists because *other people's browsers* read a link.
- **Import never replaces or deletes** — deleting cannot be undone here, and an
  overwrite would let a stale file erase newer work silently. Same id and every
  field equal → skipped and reported. Same id, different content → added under a
  fresh id, so no two rows share a URL. Different id → a different portfolio,
  however alike (a Duplicate is not a repeat). A taken name gets `-2`, `-3`, …
  appended as it stands; the check runs against the library *plus everything
  already added from the same file*.
- **Nothing about view state travels** — window, benchmark, comparison and metrics
  live in the URL, not on the portfolio.
- **The plan is pure; the hook applies it.** `usePortfolios.importFile` reads the
  file, plans against the library as it stands *after* the read, and writes once
  through `mutate`. A refused write keeps the portfolios in the session like any
  other change (principle 3), and the result dialog says they are not being saved.
- **No confirmation before an import** (it only adds), but **always a result
  dialog after one** — added, renamed, skipped-as-identical, failed with reasons —
  because otherwise a successful import looks like nothing happened. Exactly one
  portfolio added opens it, on close; several stay put.
- **Where the controls are:** *Export library* and *Import* pinned under New
  portfolio in the sidebar (Export is off for an empty library); *Export* beside
  Share on an open portfolio; *Import a backup* on the empty landing page. A
  shared portfolio has no Export — it is not yours to back up until it is kept.
  `StorageNotice` points at Export library in `full` and `unavailable` only, when
  the file is the only place what is on screen can go — never in `corrupt`, which
  says nothing about what the session holds.
- **Text only:** a name or reason from a file is rendered as text and never built
  into anything, and the simulation request is built field by field, so an unknown
  field kept in the library never reaches the backend.

The link payload carries **its own version** (`LINK_VERSION`, currently 3),
independent of `SCHEMA_VERSION` — it is a wire format other people's browsers
have to read, so it changes for its own reasons. Version 3 added the recurring
withdrawal (`w`), as its own key rather than a negative contribution: a build
that predates it reads a contribution at or below zero as "no schedule" and would
show a withdrawing portfolio as a lump sum, where it refuses a version it does not
know. Version 1 is still read as a portfolio with no contribution schedule, and
version 2 as one with no withdrawal; a payload carrying both `c` and `w` is
refused whole. Adding a field means bumping
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
a single decision, made once. So does the **Money flow** (issue #150): one
control — None, Pay in or Withdraw, then a frequency and an amount — rather than a
control each, because a portfolio does one or the other (ADR 0002) and with two the
state "both" would need explaining. Every change writes *both* keys at once, the one
it sets and the one it clears (`update` spreads its changes, so `undefined` clears),
which is what keeps the library from ever holding two. Switching direction keeps
the amount and frequency; turning it on from None fills in a placeholder amount and
monthly, the way the old frequency-led control did. The amount commits on blur.

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
  not by the manifest**: it only renders once `metrics.contributed > 0` or
  `metrics.withdrawn > 0` (issues #67 and #150) — a fact about *this run*, not
  something a metric declares about itself. So is which of the Contributed and
  Withdrawn tiles is worth drawing: a portfolio does one or the other, so the
  unused one is a permanent zero and is left out.
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
  simulated as a basket of one, given the open portfolio's own amount and schedule
  (a contribution or a withdrawal, whichever it has, issue #150) so the comparison
  is like with like, and never written to the library.
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
- **Money taken out is read, not drawn** (issue #150). A portfolio drawn on has no
  staircase — what was paid in never rises — and net of withdrawals the line would
  fall below zero on a long drawdown and leave the plot. The stack steps down as
  money leaves, which is the picture; the tooltip and legend carry the running
  `withdrawn` figure, and the tooltip reads the gain as
  `total + withdrawn − paidIn`, because money spent was still earned.

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
- **Two families of number, and the split is the point** once money is paid in
  or taken out. Total return, CAGR, volatility and max drawdown are time-weighted
  and describe *the portfolio*; paid in, contributed (or withdrawn), gain and
  money-weighted return describe *the account*. `PortfolioSummary` splits into two
  labelled rows and `ComparisonSummary` grows a money-weighted column, only when
  some line is actually paid into or drawn on. With nothing beyond the opening
  amount the two agree exactly.
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

`ImportResultDialog` (issue #148) is shown after *every* import and lists only the
groups that apply. It names what was skipped rather than counting it — "3 skipped"
would leave somebody unsure whether the one they wanted was among them — and it
says when the write was refused, since "Added 3 portfolios" is a promise the next
reload would break.

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
