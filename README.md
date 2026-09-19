# Market Analyser

ETF correlation dashboard. React/Vite frontend + FastAPI backend, live market
data via yfinance.

## Backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --port 8000 --reload
```

API docs: http://localhost:8000/docs

By default the API accepts cross-origin requests only from the local
frontend dev ports (`http://localhost:5173`, `http://localhost:3456`). Set
`CORS_ORIGINS` (comma-separated) in `backend/.env` to allow other origins,
e.g. a deployed frontend — see `.env.example`.

### Data pipeline

The tracked universe lives in Supabase (`etfs`, `ticker`, `etf_holdings`,
`prices` tables) — there is no hardcoded list. Three scripts maintain it
(all run from `backend/`, needing `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`
in `.env` — see `.env.example`):

- `python scripts/add_ticker.py NVDA "AAPL:Apple Inc."` — manually add or
  update tickers.
- `python fetcher/vaneck.py --output vaneck_holdings.json [--limit N]` —
  run from the repo root (deps in `fetcher/requirements.txt`, plus a
  one-time `playwright install chromium`; no API key): scrapes the
  provider's website for its full ETF holdings and writes them as JSON
  (schema in `fetcher/common.py`). Each fetcher talks to its provider
  through `fetcher/common.py`'s `BrowserSession`, a Playwright-backed
  session — a real browser context for every provider, not just the ones
  that need it, which is what makes `fetcher/invesco.py` possible: unlike
  the others, invesco.com blocks plain HTTP clients outright, and only a
  real page load (not just a normal HTTP request, even with borrowed
  cookies) gets past it. One fetcher per provider lives in `fetcher/`
  (`vaneck.py`, `spdr.py`, `ark.py`, `ishares.py`, `vanguard.py`,
  `invesco.py`).
- `python scripts/complete_database.py --holdings-json ../vaneck_holdings.json
  [--dry-run] [--etfs SMH]` — complete the ETFs already in the `etfs` table
  from a holdings JSON: fill missing metadata, validate each new constituent
  ticker (yfinance must return price history — non-US Bloomberg-style
  tickers are skipped), insert it, backfill its full price history, and
  upsert the full holdings with weights. Only stocks weighing at least 1%
  in one of their ETFs are tracked (`--min-weight` to override); lighter
  ones are skipped on insert and pruned from the DB if already present.
  Idempotent; both stages run end-to-end via the "Fetch holdings and
  complete database (manual)" GitHub Action.
- `python scripts/fetch_daily.py` — daily refresh of prices, stock metadata,
  ETF holdings, and the tracked risk-free rate (`risk_free_rate` table,
  issue #103 — see "Scoring against a risk-free rate" below) for everything
  tracked. Runs on a cron via the "Daily ticker data fetch" GitHub Action.

#### How prices are stored

Two properties of `prices` decide what every number computed from it means,
so they are worth knowing before reading any of them.

**Prices are adjusted, always.** Both the backfill and the live fallback
call yfinance with `auto_adjust=True`, so `prices` holds split- and
dividend-adjusted OHLC exclusively and no reader needs adjustment logic of
its own (issue #13, `backend/sql/003_store_adjusted_prices.sql`). Before
that the two paths disagreed, and NVDA's 2024 10:1 split read as a
one-day return that corrupted its correlation against every peer. Dividend
and split events stay as a separate sparse record in the `dividends` and
`splits` tables, unadjusted, which is what makes the income in
[Dividends](#dividends) recoverable at all.

**History is tiered by age** (issue #10,
`backend/sql/001_optimize_prices_storage.sql`). Rows under a year old are
daily; one to five years old are weekly OHLC buckets; older than five are
monthly. A row carries a `granularity` of `D`, `W` or `M`, and a coarse
row's `date` is its **bucket anchor** — the Monday of the ISO week, or the
1st of the month — not a trading day, while its `close` is the bucket's
**last** close. Those are different days, which matters to anything
aligning another series to this one. Anything reading a long window is
therefore reading buckets, not days, which is why the portfolio simulator
scales each return by the trading time it actually covers rather than
assuming one row is one day.

**A basket only partly held in Supabase is completed live.** `get_closes`
answers from the database where it can, and any requested ticker with no
rows there — every ETF, since those live in `etfs`, and anything resolved
live — is fetched from yfinance and put onto the calendar the database
frame already uses, taking each bucket's last live close. One granularity
across every column is what keeps a mixed basket comparing like with like;
the cost is that a holding merged onto a coarse calendar is sampled as
coarsely as its basket-mates, so it reports slightly less volatility than
the same holding simulated on its own daily rows. Before this, a partial
answer was returned short and the simulator read the missing column as a
holding that had not listed yet — valuing an ETF at zero for a whole run
(issue #86).

### Measurements

Every column in the holdings table comes from a measurement plugin: a
self-contained class that fetches its own inputs, computes a value per holding,
and decides how that value is drawn. Official ones live in
`backend/measurements/official_measurements/`, plugged-in ones in
`addon_measurements/`; the registry discovers both and the frontend builds
its columns from what it finds, so adding a measurement needs no frontend
change.

A plugin usually provides one column, but may instead declare several from a
single computation — upside and downside capture, say, rather than running the
same fetch twice for two halves of one comparison. Either way the picker lists
columns, not plugins: a multi-column plugin's name and description appear once,
with each of its columns individually toggleable beneath, and adding a second
column to an existing plugin still needs no frontend change.

A plugin whose number *means* a stretch of history — volatility, a trailing
return, a rolling correlation — declares support for a shared window instead
of leaving that unstated: one control above the holdings table, not one per
column, so two window-aware columns can never claim different periods. Every
such column names its window in its header and on its own doc page, including
the worked example; a plugin that declares no window (every official one,
today) is entirely unaffected and takes none.

**Every column carries a cost rating** — Short, Medium, Long or Extremely
long (issue #115) — shown as a badge in the picker, the column header and
the doc page. It is *derived*, never hand-declared: `backend/measurements/
cost.py` reads only what a plugin already states for other reasons — which
`measurements/inputs/*` getters it uses (`uses_inputs`) and how each of
those scales with holding count (a flat per-fund lookup, a read that grows
with the basket, or a pairwise sweep across every holding), whether it can
ever need a live upstream call, and how much price history it reads — and
sums those into a score:

| Score | Rating |
| --- | --- |
| 0–6 | Short |
| 7–11 | Medium |
| 12–17 | Long |
| 18+ | Extremely long |

A correlation-derived column rates heavier than a weight-derived one, and
days to liquidate (which reads volume for the whole basket) rates among the
heaviest, without either plugin declaring so itself — and because the score
includes how much history a windowed input reads, widening the shared
window control can visibly move a column's own rating from Short toward
Extremely long. This issue is informational only: nothing about a rating
gates, defers or warns before a column is enabled.

Each measurement documents itself in an `.mdx` file **next to its own
module** — `correlation.py` → `correlation.mdx` — which the app serves at
`/docs/<measurement id>` and which every column that plugin provides shares.
Keeping the doc beside the plugin is what lets an addon ship its own
documentation.

Copy `backend/measurements/DOC_TEMPLATE.mdx` to start one. The file is YAML
frontmatter followed by MDX:

```mdx
---
title: Correlation to Fund
summary: How closely a holding has moved with the rest of the fund.
example_etf: SMH        # optional
example_stock: NVDA     # optional
author: Jane Doe        # optional (issue #114)
author_url: https://…   # optional
version: "1.0"            # optional — quote it, or YAML reads it as a number
---

## What it measures
...
```

### How a holding relates to its fund

ρ alone says how tightly two things move together, and nothing about
magnitude, about how much of the fund's own risk a holding actually drives,
about whether the relationship holds up on the days it matters, or about
whether it is strengthening or fading. Seven columns — six from issue #107,
plus Rolling Correlation from issue #110 — answer those questions instead,
all official measurements next to `correlation.py`:

- **Risk Contribution** — each holding's own share of the fund's variance
  (`wᵢ·Cov(rᵢ, r_fund) ÷ Var(r_fund)`), summing to 100% across the fund.
  Reuses `services.stats.risk_contribution` directly — the same Euler
  decomposition the fund-level variance-share metric (issue #105) already
  shares — rather than a second implementation.
- **Beta / R² / Idiosyncratic Volatility** — one plugin, three columns:
  sensitivity to the fund, how much of a holding's own variance the fund
  explains, and the annualised volatility left over once that's removed.
  R² and idiosyncratic volatility are computed from the **same** underlying
  correlation in one pass — `idiosyncratic_volatility` accepts an
  already-computed R² result rather than measuring the relationship twice.
- **Tail Correlation** — ρ computed only over the fund's own worst decile of
  periods by return: does a holding still move with the fund on the days
  that hurt, or does the relationship come apart exactly when it would
  matter most. Its own doc page states the granularity caveat plainly: for
  a window answered in weekly buckets (most windows on this table), "worst
  decile" means worst *weeks*, not worst days.
- **Upside / Downside Capture** — one plugin, two columns: how much of the
  fund's own compounded return a holding captured over exactly the periods
  the fund rose, and over exactly the periods it fell.
- **Correlation to Fund (Rolling)** — ρ computed separately over consecutive,
  non-overlapping 30-return blocks across the window (30 is `services.stats`'
  own `MIN_OVERLAPPING_RETURNS` — the bar this app already draws for "enough
  returns to trust a correlation at all", reused as "how long one rolling
  reading should span" rather than a second, unexplained number), instead of
  once over the whole thing. An ordinary correlation is an average, and an
  average hides its own history: a holding whose ρ climbed from 0.3 to 0.9
  and one whose fell from 0.9 to 0.3 can both average 0.6 and be opposite
  findings. The cell draws the resulting path with `<Spark>` (issue #106) —
  the column this component exists for — while the column itself sorts and
  filters by the *change*, the last block's ρ less the first's, since a path
  needs a single number to rank by the same as any other column, and "is
  this relationship strengthening or weakening" is a more useful question
  than "what does it read right now".

All six read a common benchmark, the fund's own weighted-return index
(`measurements/inputs/fund_index.py`, issue #107) — built once from
whichever tracked holdings have a complete price history over the window,
weights renormalised to sum to 100% so the untracked share isn't silently
treated as cash earning nothing. A holding missing any date in the window is
excluded from the index and from every column built on it (still counted in
`% of ETF`) rather than narrowing the whole fund's window down to fit it —
the same reasoning the fund-level card (issue #105) states for the same
problem. Every column here is window-aware, sharing the same table-wide
control every other window-aware column already does (issue #101).

This is also the first time an **official** measurement declares several
columns from one plugin (issue #100's own mechanism, previously proven only
by test stand-ins) — which is what pushed `examples.py` and
`WorkedExample.jsx`'s worked-example machinery to actually grow multi-column
support: a doc page for one of these now shows one "computed value + cell"
pair per column, not just the first.

- `title` and `summary` are **required**. Unknown keys are rejected rather
  than ignored, so a typo fails loudly instead of silently doing nothing.
- `example_etf` / `example_stock` choose the fund and holding the worked
  example is computed against, when a particular one illustrates the
  measurement better than the defaults (`DOCS_EXAMPLE_ETF` /
  `DOCS_EXAMPLE_STOCK` in `backend/config.py`). A measurement class can
  declare the same two attributes; the doc's frontmatter wins.
- `author` / `author_url` / `version` (issue #114) say who wrote this plugin,
  where to read more about them, and which release it is. Same precedence as
  `example_etf` above — the class declares a default, the doc's frontmatter
  overrides it — but **no third, repo-wide fallback**: a plugin declaring
  neither is shown as unattributed, in the measurement picker and at the head
  of its own doc page, never credited to whoever owns this repository.
  Portfolio and fund metrics (issue #104) carry the same three fields and are
  shown with the same card, since both registries share one mechanism.
- The body is not validated. The section headings in the template are a
  convention that keeps every measurement reading the same way, not a
  schema.

Beyond standard markdown (including GitHub-style tables), a doc may use four
components:

| Component | For |
| --- | --- |
| `<Note>` | An aside worth reading — context, a definition, a gotcha |
| `<Warning>` | A caveat that changes how the number should be read |
| `<Formula>` | A typeset LaTeX formula; `inline` for one mid-sentence |
| `<WorkedExample />` | The measurement run against real data — its inputs, computed values, and rendered cells |

`<WorkedExample />` is appended automatically if the body doesn't place it,
so it costs nothing to omit and can be positioned deliberately when it reads
better next to the formula. Write formulas as
``<Formula tex={String.raw`\rho_{ij}`} />`` so backslashes survive.

This vocabulary is a stable contract: components may be added, but changing
or removing one breaks docs already written against it. Docs are compiled
and executed as real JSX in the browser, which is safe only because they are
first-party files reviewed like any other code here — never build one from
external data.

A measurement never calls the data layer directly — it fetches through
`backend/measurements/inputs/`, one getter per distinct piece of data, each
declaring what it quietly defaults so a doc page can say so. Alongside a
fund's holdings, its own metadata and the correlation matrix, three getters
reach prices, volume, stock metadata and dividends for a fund's whole basket
of holdings in bulk (issue #102): `price_frame` (close prices, and volume
wherever the database has it — `null`, never `0`, for a holding with no
`prices` rows at all, such as an ETF held inside another ETF), `stock_info`
(each holding's own name, sector and market cap) and `dividend_events`
(dividend history alongside whether the holding is tracked at all, the same
"tracked and paid nothing" versus "no record here" distinction the
[Dividends](#dividends) section below describes for the simulator).
`price_frame` defaults to the same window the correlation matrix reads, so
a doc page or measurement using both shares one cached read rather than
asking Supabase twice for the same tickers.

### A holding's own price history

Every column described so far says something about a holding's place
inside its fund — its weight, its correlation, its relation to the fund's
own risk. None of them describe the holding on its own terms. Four more
columns (issue #108), across two official measurement plugins, read
nothing but a holding's own price history:

- **Volatility** — annualised standard deviation of the holding's own
  returns over the window, through `services.stats.volatility` — the same
  function the portfolio simulator's own Volatility metric applies to a
  portfolio's series, applied here to one holding's.
- **Max Drawdown** — the deepest peak-to-trough fall in the holding's own
  price over the window, negative or zero, never positive.
- **1Y Return & Momentum** — one plugin, two columns. Return is the
  window's own total return on adjusted closes, so income is already
  inside it. Momentum is that same return with the most recent month
  skipped — from the window's start to one month before its end rather
  than all the way to the end — which for the default 1-year window is the
  standard "12-minus-1-month" factor. The skip is deliberate: a very
  recent month is the one most prone to reversing itself, and leaving it
  out is what keeps Momentum from simply restating Return.

All four go through `services/stats.py` — no local reimplementation of
annualisation or drawdown — and are window-aware, sharing the same
table-wide control every other window-aware column already does (issue
#101). A holding with fewer than two priced dates over the window reports
null with a reason on every one of these, not zero: `total_return` and
`momentum` are new `stats.py` functions added alongside this issue,
`total_return` a plain `last / first - 1` with no time dimension (the same
reason `cagr` carries no `granularity`), `momentum` finding whichever row
falls one calendar month before the window's last one and reading the same
ratio up to there — which *does* carry a `granularity`, since which row
counts as "one month before the end" depends on how coarsely that stretch
of the window happens to be bucketed (issue #10).

### Metadata and income, per holding

Two more official measurements (issue #109), across three columns, neither
of them window-aware — each answers a question about right now or about a
fixed trailing stretch, not about the table's shared lookback:

- **Market Cap** — straight from `stock_info`, converted to billions so it
  reuses Value Held's own $/B/T thresholds rather than every reader
  converting the exponent by hand.
- **Cap-Weight Tilt** — a holding's fund weight less the weight a passive,
  cap-weighted basket of the same *tracked* holdings would have given it
  (`wᵢ − capᵢ ÷ Σ cap`). The denominator can only sum over holdings this
  app actually tracks (weighing at least 1% — `measurements/inputs/
  holdings.py`'s own rule), not a fund's full constituent list, so tilts
  sum to only approximately zero across a fund, not exactly.
- **Dividend Yield & Income Share** — one plugin, two columns, both fixed
  to the trailing twelve months rather than the table's window control.
  Yield is declared dividends over that stretch divided by the holding's
  last close. Income Share is that same income measured against the
  holding's total return over the identical stretch — price change plus
  income — so a reader can see how much of what a holding made came from
  being paid rather than from its price moving. Dividend amounts are read
  exactly as `dividends` stores them: unadjusted, the same choice the
  [Dividends](#dividends) section below states for the simulator's own
  income figure, and for the same reason — the closes behind the price
  change are always adjusted, so summing the two is a readable
  approximation of where a return came from, not a strict decomposition.

**Absence is never zero, on any of the three.** An ETF holding, or
anything resolved outside the tracked universe, has no row in `ticker` and
reports null with a reason for yield and income share — the same
`incomeUnknownFor` distinction the simulator draws — rather than a 0.00%
that would claim it pays no dividend. A holding with no market cap on
record is null on both Market Cap and Cap-Weight Tilt, and excluded from
the tilt denominator entirely rather than treated as zero-weight.

### Whether a position can be sold

Value Held says a fund holds $61.8B of something. It says nothing about
whether that position could actually be sold, which for a thinly traded
constituent of a large fund is the more interesting fact. **Days to
Liquidate** (issue #111) answers it in the plainest possible unit: value
held ÷ the holding's own average daily dollar volume (`close × volume`,
averaged across the window) — days of normal trading it would take to
exit the fund's entire position, at that position's own recent pace. Value
held reuses Value Held's own arithmetic (fund AUM × weight) exactly, so
the two columns cannot disagree.

This is the first official column to actually read `prices.volume` — the
`price_frame` input getter's own bulk, volume-widened read (issue #102),
until now fetched by nothing. One trap is specific to it: a coarse row's
volume is a bucket **sum**, not one day's (roughly 21 trading days for a
monthly bucket — `sql/001_optimize_prices_storage.sql`'s own reason
`volume` stayed a `bigint`), so averaging bucketed rows straight would
read a monthly sum as a single day's, overstating every position's
liquidity by about the width of its bucket. `services.stats.
average_bucketed_daily_value` divides each row by the trading days the
gap back to the row before it actually covers before averaging — the same
conversion every other bucket-spanning figure in this app already uses —
so a window mixing daily, weekly and monthly rows corrects each one by
its own bucket's width rather than a single blanket adjustment.

Null with a reason, not zero, for a holding `prices` has no rows for at
all (every ETF, and anything resolved outside the tracked universe) or
priced for fewer than two dates, the same case `price_frame`'s own volume
field is already null for. The doc states plainly that this is a scale
assuming today's volume continues, not a plan — a real sale of that size
would itself move the price, which nothing here models.

## Portfolio simulator

A portfolio here is **a simulation, not an account**: a basket of tickers,
the share of the money each one takes, and a stretch of history to value it
over. Nothing is bought, nothing is connected to a broker, and nothing
here tracks anything anybody owns. "What would this basket have done" is
the only question it answers.

### Where portfolios live, and why there is no account

In the browser that authored them, under the `localStorage` key
`market-analyser.portfolios`, and nowhere else.

That is a consequence of how the rest of the project is authenticated, not
a stage on the way to accounts. There is no sign-in, so the backend has no
idea who is asking; its only Supabase credential is the **service key**,
which is precisely the credential that bypasses row-level security. A
server-side `portfolios` table would therefore be one shared,
world-editable list — every visitor able to read and overwrite every
other visitor's portfolios, with nothing in the request to tell them
apart. Storing them client-side is the honest option, and the simulation
itself is stateless, so nothing else needs to know.

The trade is stated plainly in the UI: portfolios do not follow you to
another browser or another machine, deleting one cannot be undone, and a
private window keeps nothing. [Share links](#sharing-a-portfolio) are the
way one travels.

`app/src/store/portfolioStorage.js` is the whole storage layer. Every read
is normalised through one migration function and every failure — storage
blocked, quota full, a half-written value — is returned as a state the UI
can explain rather than thrown, because none of those may white-screen a
page over a feature the visitor has not opened yet.

### The conventions

`backend/services/portfolio.py` is the full statement of the model. The
return and risk arithmetic underneath it - a year, a trading day, what a
coarse row means, CAGR, volatility, drawdown - lives in
`backend/services/stats.py` instead, shared with every metric that needs the
same arithmetic applied to a single holding rather than to a whole portfolio;
its module docstring is the exact, single statement of those conventions, not
restated here. Every number on screen depends on the decisions below, and
none of them is guessable from the UI.

**The model:**

- **Weights are ratios, and are normalised.** Any non-negative numbers
  describe the basket by their proportions, so 30/30/30 and
  33.33/33.33/33.33 are one portfolio and must simulate identically. A
  total under 100 is scaled up rather than treated as part-cash; a total
  over 100 is scaled down, and the UI says so rather than refusing it.
  Negative weights are refused outright — shorting is not modelled, and
  coercing −5 to 5 or to 0 would both invent an intention nobody expressed.
- **Buy and hold is the default.** The weights buy shares once and each
  holding then drifts with its own price. That drift is the thing worth
  looking at: a winner visibly taking over a portfolio is invisible under
  continuous rebalancing.
- **A rebalance restores the target weights** from the then-current total,
  monthly, quarterly or yearly. It happens on **the first row of each new
  period**, not on a fixed calendar date — the 1st of a month is often not
  a trading day, and an old enough window has no daily rows at all, so
  "the first row the period actually has" is the only definition that
  holds across the whole of history.
- **An allocation is cash until its holding lists.** A ticker with no price
  yet cannot be bought, and pretending otherwise would either invent a
  price or silently drop the allocation. It sits in cash, earning nothing,
  and buys in at the first close it has — at exactly that price, so the
  portfolio's total does not move on the day it happens.
- **The calendar is the union of the dates the price rows cover**, not the
  intersection: one holding missing one day must not delete that day for
  the others. A gap inside a holding's own history is forward-filled, since
  its last known close still describes what it is worth. Note that `prices`
  tiers history by age (see the data pipeline above), so a window reaching
  years back is a calendar of monthly buckets rather than trading days —
  the simulation is only ever as fine-grained as the rows underneath it.

**How a run is scored** — a number is worth only as much as the convention
behind it:

- **Returns are simple, not logarithmic**, taken between consecutive rows
  of the run's own calendar.
- **Returns are total returns.** `prices` stores adjusted closes, so
  dividends are already inside every value. See
  [Dividends](#dividends) below.
- **A year is 365.25 days, and CAGR compounds over elapsed calendar time**
  — not over a row count. The same year answered in twelve monthly buckets
  and in 250 daily rows annualises to the same rate.
- **Volatility is annualised to 252 trading days**, with each return first
  divided by the root of the trading time it actually covers - see
  `backend/services/stats.py` for exactly how that scaling works and why it
  is not a refinement: annualising a weekly bucket as though it were a day
  reported 54% on a real basket whose true figure was 35%.
- **Drawdown is measured on the total**, the only series a holder
  experiences. A single holding can fall much further without the portfolio
  noticing.
- **Time under water, pain index, Calmar, Sharpe and Sortino (issue #112)
  are all read off the same flow-free unit value** total return, CAGR,
  volatility and drawdown already are, so a deposit never reads as
  performance in any of them either. Time Under Water is the longest
  single stretch below a prior peak, in calendar days, with Share Under
  Water naming what fraction of the whole window that and every other
  stretch together came to; Pain Index is the time-weighted mean
  drawdown depth across the window, where — like Max Drawdown — 0% is a
  real answer, not a missing one. Calmar is CAGR over the absolute
  depth of the worst drawdown. Sharpe and Sortino divide the run's own
  annualised mean excess return (the arithmetic mean of period returns,
  not CAGR — the same mean volatility's own dispersion is built from, so
  numerator and denominator are measured the same way) by annualised
  volatility and by downside deviation respectively; both are null with
  a reason, not scored against an assumed zero, whenever no risk-free
  rate is available for the run's own window and no override was given.
- **A holding's gain is its final value less every dollar put into it** —
  the `contribution` field per holding, labelled GAIN in the UI. Once a
  rebalance starts moving money between holdings, a final value says
  nothing about which holding earned it, so the flows have to net out. The
  per-holding gains sum to the portfolio's.
- **A figure the run cannot support is `null`, not `0`.** Two days of
  history has no growth rate and no volatility, and reporting zero would
  claim a portfolio held for two days was riskless.

### What is deliberately not modelled

Their absence is a decision, not an oversight. None of the following is
simulated, and no number here accounts for any of it:

- **Fees and commissions** — no trading costs, no expense ratios, no
  spread. A rebalance is free, which real ones are not.
- **Taxes** — no capital gains, no dividend withholding, no wash-sale
  rules, and no jurisdiction.
- **Shorting and leverage** — weights are non-negative and the portfolio is
  never geared. A negative weight is refused rather than interpreted.
- **Currency** — everything is USD. Every tracked ticker is US-listed and
  no conversion is applied, so a foreign listing would be valued in its own
  currency and silently added to dollars.
- **Cash yield** — an allocation waiting for a holding to list earns
  nothing at all, where real cash would earn something.
- **Real index constituents** — there is no index option. An index is
  copied by copying an **index-tracking ETF** (SPY for the S&P 500, say),
  which is that fund's holdings and not the index itself. Only
  constituents weighing at least 1% of their fund are tracked, and the
  weights are the fund's **current** ones — so a backdated copy is
  survivorship-biased and the panel says so.
- **Corporate actions beyond price adjustment** — splits and dividends
  arrive through the adjusted closes; spin-offs, mergers and delistings are
  whatever yfinance's adjusted series makes of them.

### Recurring contributions

A portfolio can be funded once at the start, or paid into on a schedule —
`{"amount": 100, "frequency": "monthly"}` beside the holdings, with
`quarterly` and `yearly` also available. It is **off by default**: an
absent contribution, a null one, and an amount of zero are all the same
request, and all three simulate exactly as a single lump sum.

Money arrives on **the first row of each new period after the start**, not
on a fixed calendar date. The 1st of a month is frequently not a trading
day, and `prices` tiers older history into weekly and monthly buckets
(see the data pipeline above), so "the first row the month actually has"
is the only rule that holds across the whole of history. A payment is
never skipped for landing on a weekend; it moves to the next row there is.
The window's own first row is the opening amount and never takes a
contribution, so a year of monthly payments is the twelve times money
arrived *after* the start. Each payment is spread across the target
weights at that row's prices, and any part of it belonging to a holding
that has not listed yet waits in cash exactly as the opening allocation
does.

**Two families of number, and the split is the point.** A deposit is not a
gain: paying $100 into a $1,000 portfolio moves the total 10% on a day the
market did nothing, and a metric read straight off the total records that
as performance.

- **Total return, CAGR, volatility and max drawdown describe the
  portfolio.** They are time-weighted — computed on a unit value that only
  moves when prices do — so they answer "what would a dollar left alone in
  this have done".
- **Paid in, contributed, gain and money-weighted return describe the
  account.** The money-weighted return is the internal rate of return: the
  annual rate that reconciles every deposit, discounted from the day it
  arrived, with the final value.

With no contributions the two agree exactly, which is why switching the
feature off leaves every existing result unchanged. With contributions
they can differ a lot, and neither is wrong — a holding can gain 54% over
a window while the money in it earns 21% a year, because the later
payments were working for less of it.

The UI labels both families, shows the paid-in line as a staircase over
the stacked chart so the gap to the top of the stack is the gain, and adds
a money-weighted column to the comparison table as soon as any line is
funded this way.

### Dividends

**Every return the simulator reports is already a total return.** `prices`
stores split- and dividend-adjusted closes (issue #13 and
`sql/003_store_adjusted_prices.sql`), so income is inside every value —
treated as reinvested in more of the same holding the moment it arrived.
That is correct but invisible, which is why the income is also reported
on its own: `metrics.dividendIncome`, `metrics.dividendYield`, and an
`income` figure per holding.

It is **reported, never added**. Adding the cash on top of a value that
already contains it would count the same money twice, and the UI says so
rather than leaving a reader to wonder why the two do not sum.

Income is computed from the sparse `dividends` event table — one row per
ex-date per ticker, holding the cash amount as declared, deliberately
unadjusted. A dividend is paid on **the shares held at the last row before
its ex-date**, which is what the holder owned going into it. That is not
the same as the shares held at the start: buy and hold lets a position
drift, a rebalance resets it, and a contribution grows it, so the same
dividend schedule pays three different amounts under the three models.

**Silence is not zero.** A tracked holding with no dividend rows in the
window genuinely paid nothing and reports `0`. A holding with no row in
the `ticker` table at all — every ETF, since those live in `etfs`, and
anything resolved live — reports `null` and is named in
`metrics.incomeUnknownFor`. Answering the second case with the first would
state, in a figure, that SPY pays no dividend. The value and the return
still include that income; only the income figure cannot see it.

### Scoring against a risk-free rate

Sharpe and Sortino (issue #112) are the first metrics this app needs a
risk-free rate for, and a single hardcoded figure would be meaningfully
wrong: the windows this app can already simulate span years over which
short rates moved several points, and a ratio computed against the wrong
one is wrong by exactly that gap. So the rate is tracked like everything
else the pipeline tracks — its own database table
(`risk_free_rate`, issue #103), refreshed daily alongside prices and
dividends — never a constant in application code. Not even the upstream
symbol is hardcoded: it lives in `risk_free_rate_source`, a one-row table
seeded once by its migration, the same "database decides, not code" rule
the tracked ETF/stock universe already follows.

The rate is an assumption about how a run is **scored**, not a property of
the basket being run, which is the same reasoning that puts the simulation
window in the query string rather than in the portfolio (see "Choosing the
window" below): `?rf=` overrides the tracked series for one run, surviving
a reload and travelling in a shared link the same way `?window=` does, via
`useRiskFreeRate.js`. An unusable value (missing, not a number) falls back
to the tracked series rather than erroring — a bad link should open the
app, not a complaint about itself. Read for the run's **own window**, not
a single point value: the tracked series' own average over the exact
stretch a run covers, or the override if one was given — never a rate
from some other, unrelated stretch of history.

`metrics.riskFreeRate` and `metrics.riskFreeRateSource` ("tracked" or
"override") echo exactly which rate produced Sharpe and Sortino, so a
reader can always tell — surfaced in each ratio's own worked example
rather than inline on the tile itself, since a control for choosing it
does not exist yet (see `useRiskFreeRate.js`). A run neither the tracked
series nor an override can answer for reports a null with a reason for
both ratios, never one computed against an assumed zero.

### Choosing the window, and comparing

The window belongs to the view rather than to the portfolio — the same
basket is worth looking at over a year and over a decade, and neither
reading is the portfolio's own property — so it lives in the query string,
the way the dashboard's fund and view live in the path. Two shapes:

| Query | Meaning |
| --- | --- |
| `?window=ytd\|1y\|5y\|max` | A preset, relative to today and staying relative — "the last year" means the last year whenever the link is opened |
| `?start=…&end=…` | An exact window, absolute, which does not move |

`1y` is the default. `max` is the one preset with no dates of its own:
how far back a basket reaches is a fact about its holdings, so it travels
to the backend as a period and comes back as the window it turned out to
be. Anything unusable in the URL — a malformed date, an end before a
start, an end in the future, a preset that does not exist — falls back to
the default rather than erroring, because a bad link should open the app
and not a complaint about itself. Dragging across either chart sets an
exact window, and **Reset** restores what the drag replaced.

`?compare=<portfolio ids>` and `?benchmark=<symbols>` put other lines on
the chart, up to six in total. A benchmark is deliberately not a portfolio:
answering "did this beat SPY" should not require creating and then deleting
a portfolio called SPY, so a benchmark is a ticker that lives in the URL,
is simulated as a basket of one, and never touches the library. It is
given the open portfolio's own amount and contribution schedule, so the
comparison is like with like. Portfolio ids only mean something in the
browser that minted them, so a shared comparison link shows the ids it can
find and drops the rest rather than erroring.

### Sharing a portfolio

A portfolio is a name, an amount, a method and a handful of tickers and
weights — a few hundred bytes — so it travels **inside** the link rather
than behind it: `/portfolio/shared?p=<payload>`, with no server-side
storage and no account. A three-holding portfolio makes a link of about
190 characters; a hundred-holding one encodes to roughly 1.8 kB, and
anything over 8 kB is refused before it is decoded.

The payload is JSON with single-letter keys, UTF-8, base64url, and it
carries its own version independent of the storage schema — it is a wire
format other people's browsers have to read, so it changes for its own
reasons. Version 2 added the contribution schedule; version 1 is still
read as a portfolio that has none. The window and any benchmarks ride
along as ordinary query parameters, because reproducing the sender's
*result* means reproducing the dates too. Comparison ids do not: they name
portfolios that only exist in the sender's browser.

Decoding is the opposite of the storage migration next door.
`migratePortfolio` salvages what it can, because the alternative is
silently losing work somebody did; a link is untrusted input whoever sent
it, so `decodePortfolio` refuses the **whole payload** on the first thing
that is wrong — shape, version, name, amount, method, ticker pattern,
weight, duplicate ticker, size — with the size ceiling checked before
anything is decoded. Showing three quarters of somebody's portfolio under
their name is worse than an error message.

A shared link opens **read-only**: it simulates, charts and reads exactly
like a saved portfolio — that is the whole promise — but every control
that would write something is removed rather than disabled. Nothing
touches storage until **Save a copy**, which mints an ordinary new
portfolio with its own id and timestamps and opens it on the window that
was on screen. It is a snapshot: the portfolio is in the link, not behind
it, so there is nothing on a server for the sender to update and it will
not follow their later changes. The UI says so.

### The endpoints

There is no account and no API key, so every request is anonymous — see
"Bounding one anonymous client" below for what that means for how much any
one caller can ask for.

**`POST /api/portfolio/simulate`** — value a basket over a window. A POST
with a body rather than a GET because a basket of holdings does not belong
in a URL, even though it reads nothing and changes nothing. Nothing is
stored: the portfolio arrives in the request and leaves in the response.

```jsonc
// request
{
  "holdings": [                      // 1–50 entries, tickers unique
    { "ticker": "TXN", "weight": 60 },
    { "ticker": "MSFT", "weight": 40 }
  ],
  "value": 10000,                    // USD at the start date, > 0
  "period": "1y",                    // 1y, 5y, max… — excludes start/end
  "start": null,                     // or an explicit ISO window instead
  "end": null,                       //   of a period, never both
  "rebalance": "none",               // none | monthly | quarterly | yearly
  "contribution": {                  // optional; omit for a single lump sum
    "amount": 100,
    "frequency": "monthly"           // monthly | quarterly | yearly
  },
  "rate": null                       // risk-free rate override, % p.a. (issue
                                      //   #103), scoring Sharpe/Sortino (issue
                                      //   #112); omit for the tracked series.
}
```

```jsonc
// response — series are columnar and all the same length as `dates`
{
  "start": "2025-09-08",             // the window actually simulated, which
  "end": "2026-09-04",               //   for "max" is narrower than asked
  "startValue": 10000.0,
  "rebalance": "none",
  "contribution": { "amount": 100.0, "frequency": "monthly" },  // or null

  "dates": ["2025-09-08", …],
  "total": [10000.0, …],             // portfolio value per date
  "cash": [0.0, …],                  // allocations still waiting to buy in
  "invested": [10000.0, …],          // running sum of money paid in
  "unitValue": [10000.0, …],         // flow-free series the metrics use;
                                     //   null when there are no contributions

  "metrics": {
    "startValue": 10000.0,
    "finalValue": 14017.3,
    "totalReturn": 26.2299,          // time-weighted, percent
    "cagr": 26.5765,
    "volatility": 29.3332,           // annualised, percent
    "maxDrawdown": { "value": -17.4831,
                     "peakDate": "2026-01-28", "troughDate": "2026-03-30" },
    "timeUnderWater": 83,            // longest stretch below a prior peak, days
    "shareUnderWater": 22.6027,      // that time as a percent of the window
    "painIndex": 3.4998,             // time-weighted mean drawdown depth, percent
    "calmar": 3.4521,                // cagr / |maxDrawdown|
    "sharpe": 1.6987,                // excess return over volatility
    "sortino": 2.5931,               // excess return over downside deviation
    "riskFreeRate": 3.7186,          // % p.a. Sharpe/Sortino were scored against
    "riskFreeRateSource": "tracked", // "tracked" or "override" (the request's `rate`)
    "contributed": 1200.0,           // recurring contributions only
    "totalInvested": 11200.0,        // startValue + contributed
    "gain": 2817.3,                  // finalValue − totalInvested
    "moneyWeightedReturn": 27.0779,  // IRR, percent
    "dividendIncome": 229.92,        // reported, never added to the value
    "dividendYield": 2.0529,         // on totalInvested, percent
    "incomeUnknownFor": []           // holdings with no dividend record
  },

  "holdings": [{
    "ticker": "TXN",
    "weight": 60,                    // the share simulated, 0–100
    "firstDate": "2025-09-08",       // null if never priced in the window
    "values": [6000.0, …],
    "return": 42.6828,               // the holding's own price return
    "finalValue": 9433.45,
    "share": 67.2986,                // percent of the finished portfolio
    "contribution": 2713.45,         // dollars of the portfolio's gain
    "income": 198.36                 // dividends; null if not on record
  }]
}
```

Errors follow the convention used everywhere else here: **400** for a
request that cannot be simulated, **404** for a holding that does not
exist, **503** when the price source could not be reached. The first two
are facts about the request and are not worth retrying; the third is a
fact about right now, and the frontend retries it. A caller who simulates
faster than its own limit allows (below) gets **429** instead, with the
same retry treatment as a 503.

One edge is worth knowing, because the two are not distinguished as
cleanly as that suggests. A basket where *some* holdings price and one
does not answers **404** naming the ticker —
`no price history for 'ZZZZQQ' - it may not be a real ticker`. A basket
where *nothing* prices — a single holding that is a typo, say — never gets
as far as that check and answers **400**
`no price data in the requested window - it may contain no trading days`,
which blames the window for what is really a bad symbol.
`GET /api/tickers/{symbol}` answers 404 for the same symbol, and the UI
resolves a ticker there before adding it, so the misleading message is
mostly unreachable from the app.

**`POST /api/portfolio/risk`** (issue #113) — how independently a
basket's own holdings actually move. The same body `simulate` takes
(`value`, `rebalance`, `contribution` and `rate` are accepted for shape
parity — a caller can send it the exact request it built for `simulate`
— but unused: this is a question about the basket's price history, not
about a value simulated over it), its own endpoint rather than folded
into `simulate`'s response, because a correlation matrix over the basket
is a second, wider price read than a value simulation needs and making
every run pay for it would slow down every simulation for the sake of
the ones somebody actually asked a risk question of.

```jsonc
// response
{
  "start": "2025-09-08",             // the window actually used
  "end": "2026-09-04",
  "averageCorrelation": 0.42,        // mean pairwise ρ; lower is more diversified
  "effectiveBets": 1.9763,           // 1..holding count; 1 for a basket of one
  "riskShare": { "TXN": 62.3, "MSFT": 37.7 },  // percent of variance per holding, sums to 100
  "reasons": {}                      // present only when a figure above is null
}
```

`riskShare` is the Euler decomposition of the basket's variance
(`services.stats.risk_contribution`) — not the same thing as dollar
weight, and a holding whose own moves reliably offset the rest of the
basket's can carry a genuinely negative share, which is real rather than
an error. `effectiveBets` is the inverse Herfindahl of each holding's own
risk-share *magnitude* (`services.stats.effective_n`) rather than its
signed value, which is what keeps the figure a guaranteed `[1, holding
count]` rather than one that only usually lands there. All three are
null together, with a `reasons` entry each, when fewer than two holdings
have a complete price history over the window or the basket has no
measurable variance at all once aligned — the same two conditions the
fund metrics card's own diversification ratio reports null for (see
"Fund metrics" below). Reads nothing and stores nothing, and is bounded
by the same `MAX_HOLDINGS` as `simulate`; the same 400/404/503 contract
applies, so a caller already handling `simulate`'s errors handles this
endpoint's too.

**`GET /api/tickers/search?q=&limit=`** — find something to add to a
basket. This is the as-you-type path, so it answers from a cached snapshot
of the `ticker` and `etfs` tables and never calls yfinance and never
touches the network per keystroke.

Matches are ranked symbol-exact, then symbol-prefix, then symbol-contains,
then name-start, then a word in the name starting with the query — a name
does not match mid-word, or two keystrokes of "NV" pulls up Invesco QQQ.
An empty `q` lists the universe. `limit` defaults to 20 and must be 1–50;
outside that FastAPI rejects the request with a 422. Returns an array,
empty when nothing matches, which is not an error.

```jsonc
[{ "symbol": "NVDA", "name": "NVIDIA", "kind": "stock", "tracked": true,
   "sector": "Technology", "sectorTag": "TECH", "category": "", "logo": "" }]
```

A real but **untracked** symbol will not appear here, which is why there
are two endpoints rather than one:

**`GET /api/tickers/{symbol}`** — resolve one symbol, tracked or not, once
somebody has chosen it. Same shape plus `firstDate`, the earliest date
there is a price for, which is what lets the UI warn that a holding will
sit in cash for part of the window. **404** when upstream has no history
for the symbol — a fact about the symbol, and not one to retry.

### Portfolio metrics

Every tile in the portfolio summary — Final Value, Total Return, CAGR,
Volatility, Max Drawdown, the four account-side tiles that appear once
something is actually contributed, and the six optional risk tiles issue
#112 added (Time Under Water, Share Under Water, Pain Index, Calmar,
Sharpe, Sortino) — comes from a metric registry
(`backend/portfolio_metrics/`, issue #104), the same self-describing-plugin
pattern `backend/measurements/` already uses for the holdings table.

A metric class declares its id, name, family (`portfolio` — time-weighted,
or `account` — money-weighted), formula, null rule and which of a small
fixed set of display formats it wants (currency, percent, a signed
variant of either, the drawdown object's `{value, peakDate, troughDate}`
shape, a bare list, a plain ratio such as Calmar's — `1.42×` — a count
of days such as Time Under Water's — `45d`, issue #112's own two
additions — or a bare signed decimal such as Average Correlation's —
`0.42` — issue #113's own addition, never tone-coloured since a negative
reading there is not a loss the way a negative return is). `GET
/api/portfolio-metrics` returns every registered metric plus the two
families' own labels — `PortfolioSummary` reads its two row headers off
that response rather than hardcoding them. Adding a metric to the
registry is enough for it to appear in the enable/disable dialog and, for
any of the formats above, to render correctly as a tile — no frontend
change required (except a `computed_from="risk"` entry, which neither
`PortfolioSummary` nor the fund metrics card renders at all — see
"Portfolio risk" below for the one place that does).

**The arithmetic never moves.** A metric's `value()` reads its own figure
back out of the same `POST /api/portfolio/simulate` response
`services/portfolio.py`'s `_metrics()` has always produced — response keys
and rounding are unchanged. The dividend trio
(`dividendIncome`/`dividendYield`/`incomeUnknownFor`) is a full registry
entry with its own doc page for each, but declares `tile: false`: the
dividend note stays prose under the tile grid rather than becoming a
toggleable tile of its own (see "Dividends" above).

**Which tiles are on lives in the query string**, `?metrics=`, a
comma-separated id list read and written through `withParams` exactly the
way `?window=` and `?rf=` are — it survives a reload and travels in a
share link. An unusable value (a stale id from an old link, or none at
all) falls back to the registry's own default set.

**Every metric class carries the same `author`/`author_url`/`version`
attribution a measurement plugin does** (issue #114 — see "Measurements"
above for the doc frontmatter that overrides them), resolved onto its
manifest row the same way and shown by the same `AttributionCard`, reused
in the metrics dialog and at the head of the metric's doc page. A metric
declaring neither shows as unattributed rather than crediting whoever owns
this repository.

**A metric can be computed from a simulation run, from a fund, or from
the basket's own risk endpoint.** Eighteen metrics read
`run["metrics"][id]` — the original twelve plus issue #112's time under
water, share under water, pain index, Calmar, Sharpe and Sortino; three
(issue #105 — see "Fund metrics" below) read `services/fund_metrics.py`
instead, keyed by `etf_id` rather than by a completed run; three more
(issue #113 — see "Portfolio risk" below) read `POST /api/portfolio/risk`
instead of `simulate`'s own response, for the same "this would slow down
every run" reason that response never grew these fields itself.

Each metric documents itself the same way a measurement does: an `.mdx`
file next to its module (`cagr.py` → `cagr.mdx`), served at
`/docs/<metric id>` under its own "Portfolio metrics" sidebar group, with
a worked example computed live — against `DOCS_EXAMPLE_PORTFOLIO`
(`backend/config.py`) for a run-based *or* a risk-based metric (the
latter run through `compute_portfolio_risk` instead of `simulate_
portfolio`, but the same basket, so a reader sees one example basket
throughout), a funded basket so both families' tiles have a real,
non-null number to show; against `DOCS_EXAMPLE_ETF` for a fund-based
one. Copy `backend/portfolio_metrics/DOC_TEMPLATE.mdx` to start one.

### Fund metrics

A second, smaller registry entry reuses the exact same mechanism for
figures that describe a whole fund's basket rather than any one holding
or any one simulated run: **diversification ratio** (how much smaller
the fund's own volatility is than the weighted average of its holdings'
individual volatilities, once their correlations are counted in),
**variance share of the top five** (how much of the fund's own variance
its five largest *risk contributors* — not necessarily its five largest
*positions* — account for), and **tracked weight coverage** (how much of
the fund's weight its tracked, ≥1%-weighted holdings add up to — the
caveat every copied portfolio already carries in prose, `etf_weight`'s
own `total_weight`, given its own tile).

These three are `computed_from: "etf_id"` entries in the same
`backend/portfolio_metrics/` registry the twelve run-based tiles above
live in — "different metrics, one mechanism" was issue #105's own
decision, so they share its manifest, its family declarations
(`diversification`, `coverage`), and its doc/worked-example machinery
rather than standing up a second registry. What differs is where the
value comes from: `GET /api/portfolio-metrics/{etf_id}` runs
`services/fund_metrics.compute_fund_metrics`, which reads the fund's
tracked holdings and prices them over the same window the correlation
matrix uses, then hands the aligned series to `services/stats.py`'s
`diversification_ratio` and `risk_contribution` — the same Euler
variance decomposition a future per-holding risk-contribution column
would share, per that function's own docstring.

**A holding missing any close in the window is excluded from the ratio
and the variance share, but still counts toward coverage.** The
correlation matrix can lean on pandas' own pairwise-complete-observations
trick and let a newly listed holding keep its own shorter history,
because it computes one pair at a time; a basket's variance decomposition
needs one joint covariance matrix built from every holding's returns
aligned to the *same* stretch of dates at once, so narrowing the fund's
whole window to whatever its newest holding has traded would be the wrong
trade. Both figures come back null, with a reason, when fewer than two of
the fund's tracked holdings have a complete history over the window, or
when the basket they do share has no measurable variance at all.

On screen, this is its own card under `EtfDashboard` — deliberately not
squeezed into the identity card's `NET ASSETS / HOLDINGS / AVG ρ` row,
which is already tight — with its own enable/disable dialog and its own
query-string key, `?fundMetrics=`, so it can never collide with the
portfolio page's `?metrics=` even though both are comma-separated id
lists read through the same `withParams`/`readList` helpers.

### Portfolio risk

A third registry entry (issue #113), reusing the same mechanism a third
time: how independently the *simulated basket's own* holdings move,
rather than a whole run's performance or a fund's published weights.
Three `computed_from: "risk"` entries — **average correlation** (the
mean pairwise ρ among the basket's holdings), **effective bets** (the
inverse Herfindahl of the basket's own risk shares — how many genuinely
independent positions the basket behaves like) and **risk share** (each
holding's own percent of the basket's variance, an Euler decomposition
that sums to 100 and can go negative for a holding that hedges the
rest) — read from `POST /api/portfolio/risk` rather than from
`simulate`'s response, for the cost reason that section states: a
correlation matrix is a second, wider price read than a value simulation
needs, so folding it into every run would slow down every simulation for
the sake of the ones somebody actually asked a risk question of.

Average correlation and effective bets are optional tiles on their own
card, `PortfolioRiskCard`, below the portfolio summary — a fourth
independent consumer of the `backend/portfolio_metrics/` manifest,
filtered to `computed_from: "risk"` the way the fund metrics card filters
to `"etf_id"`. `usePortfolioRisk` only issues the request once a tile on
that card is actually switched on, and settles it independently of
`usePortfolioSimulation`'s own fetch (the same `Promise.allSettled`
independence `useComparisonRuns` already gives each comparison line), so
a 503 from this endpoint costs only these two tiles and never touches the
run's own chart or its other tiles. `?risk=` is its own query-string key,
the same "never collide" rule `?metrics=`/`?fundMetrics=` already follow.
Risk share has no tile at all — a per-holding breakdown does not fit a
single number — but still ships a full doc page and worked example, the
same "no tile, still documented" decision the dividend trio made.

### Bounding one anonymous client

There are no accounts here (see "Where portfolios live, and why there is no
account" above) and never will be, so a public deployment answers every
request without knowing who sent it. Three independent limits bound what one
caller can cost:

- **A general rate limit on every `/api/*` request**, and a separate,
  tighter one on `POST /api/portfolio/simulate` specifically — both per
  client, both answering **429** with a `Retry-After` when exceeded, and
  both configurable via `RATE_LIMIT_PER_MINUTE` /
  `SIMULATE_RATE_LIMIT_PER_MINUTE` (defaults 120 and 20 per minute — see
  `.env.example`). Ordinary use of the dashboard, including comparing
  several portfolios, stays well under either.
- **`?refresh=true` is throttled per ETF**, not per client: it reaches
  Yahoo at most once every five minutes for a given fund, however many
  people ask for it in that window. A refresh inside that window is served
  the normal cached answer rather than refused.
- **A simulation, or a risk read, is capped at 50 holdings** — the same
  `MAX_HOLDINGS`, shared rather than duplicated. Comfortably more than any
  real portfolio built here has needed, and well inside what a single
  request from an unauthenticated caller should be able to ask for.

## Frontend

```bash
cd app
npm install
npm run dev
```

Runs at http://localhost:5173 (or the port Vite reports) and talks to the
backend at `http://localhost:8000` by default. Set `VITE_API_BASE` in
`app/.env` to point a build at a different backend — see `.env.example`.

### The correlation matrix and its clusters

The Matrix tab draws the pairwise correlation of a fund's top holdings
(Pearson ρ of daily returns over the past year, `GET /api/correlation/{etf}`),
and groups the holdings that moved together (issue #143). The tab always asks
for the past year; the endpoint's `period` parameter would move the window the
clusters are computed over along with the matrix.

**How the groups are found.** Every holding in the fund is clustered once, by
the backend, on the distance 1 − ρ: start with each holding alone, keep joining
the two groups whose members are on average the most correlated, and stop when
the best remaining pair averages below **ρ 0.4** (`CLUSTER_MIN_AVG_CORRELATION`
in `backend/config.py`). Average linkage rather than nearest-pair, so one stray
link cannot chain two unrelated groups into one. The response carries the
result as `clusters`: a list of groups of two or more tickers. The level is a
judgement call, set at 0.4 after sweeping 0.3–0.7 over the tracked funds. At 0.4
the other six funds split into 5–12 groups, but a tightly-knit fund barely splits:
the two semiconductor funds come out as one group holding all (SOXX) or nearly
all (SMH) of their holdings, which is a fair reading of holdings that move
together, if a coarse one. A higher level (0.6) splits those into blocks of 5–10
at the cost of leaving more of a broad fund in no group at all.

**What a cluster does not mean.**

- **It is not a sector.** It is a statement about how prices moved over the past
  year, not about what the companies do; two software firms can sit in different
  clusters and a chipmaker and a lender in the same one.
- **It is not a forecast.** The groups are recomputed from the last year of
  returns and can shift as that window rolls forward.
- **"On average" is not "every pair".** Groups are joined by their *average* ρ, so
  a cluster can contain one pair below the threshold.
- **A missing pair is not a zero.** A pair with too little shared history has no
  correlation (issue #97), and clustering skips it rather than treating it as
  unrelated. Two groups with no computed pair between them are never joined; a
  holding with no computed pair to anyone is in no cluster and is labelled *No
  history*.

**How it is drawn.** The clusters come from the whole fund, but the matrix shows
only the top *N* holdings by weight (the "stocks" slider), so a holding's cluster
never changes as the slider moves. In the default *cluster* order each cluster is
a labelled, outlined block on the diagonal — named after its heaviest holding
("NVDA group"), with "4 of 6" when part of it is off screen — ordered by the
cluster's total fund weight, and within a block by weight or A–Z. A holding
whose cluster has no other member on screen goes into an *Others* band instead of
a block of one; that is a display rule only, and hovering its label still names
its real cluster. Colour keeps meaning ρ and nothing else, so blocks are marked
with neutral outlines and labels, never a hue. The *A–Z* and *Weight* orders draw
no blocks, so a clustered holding carries a small dot on its labels instead
(accented when it shares a cluster with the selected stock).

The choice lives in the URL: `?matrixOrder=cluster|alpha|weight` and
`?matrixWithin=weight|alpha`, each omitted at its default, an unrecognised value
read as the default.

## Running both

Start the backend and frontend in separate terminals, in either order, then
open the frontend URL in your browser.

## Running it with Docker

The commands above stay the primary, documented way to run this locally.
Docker is an alternative for a one-command start or a clean machine — it
does not replace them.

```bash
docker compose up
```

builds and starts the backend and frontend in dev mode (hot reload on both —
uvicorn `--reload`, Vite HMR — with each folder's source bind-mounted into
its container). Backend on http://localhost:8000, frontend on
http://localhost:5173, same as running them natively.

A few things about this setup are load-bearing and worth knowing before you
touch it:

- **The frontend calls `http://localhost:8000/api`, not a compose service
  name.** `VITE_API_BASE` in `docker-compose.yml` is deliberately the host's
  published port. The app runs in your browser on the host, not inside the
  compose network, so `http://backend:8000` would resolve for the backend
  container and for nothing else.
- **A missing `backend/.env` is fine.** `env_file` is marked optional, so a
  fresh clone with no Supabase credentials still comes up — degraded to live
  yfinance fallbacks and `stale: true`, exactly as a native run without
  `.env` does (see "The data pipeline" above). Add `backend/.env` (from
  `.env.example`) for the real, full-universe data.
- **`app`'s `node_modules` is a named volume, not part of the bind mount.**
  A host-installed `node_modules` carries platform-native esbuild/rollup
  binaries; overlaying the container's own Linux-built copy with the bind
  mount would make Vite fail to start.

`fetcher` and `tests` are one-shot tools rather than long-running services,
so they sit behind the `tools` compose profile and `docker compose up` never
starts them:

```bash
# Run one provider's holdings scraper; JSON lands in fetcher/output/
# (gitignored) on the host. Same --output/--tickers/--limit/--delay flags
# as running the script directly - see "The data pipeline" above.
docker compose run --rm fetcher vaneck --tickers SMH GDX --limit 5

# Full test suite (backend/tests + tests/), or pytest args passed through
docker compose run --rm tests
docker compose run --rm tests -k portfolio

# The frontend's ESLint, in the same image
docker compose run --rm tests lint
```

The fetcher image needs no Supabase credentials — it only writes holdings
JSON; loading that into Supabase with `scripts/complete_database.py` stays a
separate, manual step, as it is without Docker. The tests image needs
neither Supabase nor Chromium: fetcher tests parse checked-in fixtures and
backend tests patch their network/Supabase seams — no test may touch either,
in or out of Docker (see `CLAUDE.md`).

Both `backend/Dockerfile` and `app/Dockerfile` also have a `prod` build
target (nginx serving a static build, for `app`) for building production
images. `docker compose up` always runs the `dev` target — see "Deploying on
Render" below for where the `prod` target actually goes.

## Deploying on Render

`render.yaml` at the repo root is a
[Render Blueprint](https://render.com/docs/blueprint-spec): it deploys the
backend's `prod` Docker target as a web service and the frontend as a static
site, both on the free plan. GitHub Actions keeps fetching and refreshing
data exactly as it does today (see "Data pipeline" above) — Render only
serves the API and the app, and does not run a cron job or a fetcher.

To deploy for the first time:

1. In the Render dashboard, **New → Blueprint**, and point it at this repo
   (a private repo needs the Render GitHub app approved for the org first).
2. Render prompts for every `sync: false` variable in `render.yaml`: enter
   `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` from `backend/.env`. Leave
   `CORS_ORIGINS` and `VITE_API_BASE` blank for now — neither service's URL
   exists yet.
3. Once both services have deployed once and you know their URLs (Render
   may suffix the names in `render.yaml` if they were already taken):
   - Set `CORS_ORIGINS` on the API to the static site's exact origin
     (`https://<name>.onrender.com`, no trailing slash) — see
     [`main.py`](backend/main.py) for what this controls.
   - Set `VITE_API_BASE` on the static site to
     `https://<api name>.onrender.com/api`, then use the dashboard's
     **Save, rebuild, and deploy** — Vite inlines this into the bundle at
     build time (`app/src/utils/api.js`), so a plain restart will not pick
     up the change.

A few things are worth checking after that, and worth knowing if something
looks wrong:

- **A green health check does not mean Supabase is connected.**
  `get_client_optional()` (see "Environment and secrets" below) never
  raises on bad credentials — the API boots and quietly serves yfinance's
  top-~10 holdings with `stale: true` instead. Check
  `GET /api/etf/SPY` for `"stale": false` to confirm the real thing is
  wired up.
- **A wrong `CORS_ORIGINS` or `VITE_API_BASE` looks like a permanently
  loading dashboard, not an error.** The browser reports a CORS rejection
  as `fetch`'s own network-level `TypeError`, which `isTransientError`
  (`app/src/utils/api.js`) treats the same as a backend that has not
  finished booting — so it retries forever instead of failing loudly. Open
  the browser console; the real cause is there.
- **The free plan sleeps the API after 15 minutes idle** and takes about a
  minute to wake up. The frontend's existing cold-start retry (see
  "The endpoints" above) already covers that wait with no changes needed.
- **An ETF's price series is always a live yfinance call** — ETFs live in
  `etfs`, not `prices`, so they never have DB rows to answer from. That
  makes `GET /api/series/SPY?period=1mo` a quick way to check whether
  Yahoo answers requests from Render's IP at all.
