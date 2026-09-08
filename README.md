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
  and ETF holdings for everything tracked. Runs on a cron via the "Daily
  ticker data fetch" GitHub Action.

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
1st of the month — not a trading day. Anything reading a long window is
therefore reading buckets, not days, which is why the portfolio simulator
scales each return by the trading time it actually covers rather than
assuming one row is one day.

### Measurements

Every column in the holdings table is a measurement plugin: a self-contained
class that fetches its own inputs, computes a value per holding, and decides
how that value is drawn. Official ones live in
`backend/measurements/official_measurements/`, plugged-in ones in
`addon_measurements/`; the registry discovers both and the frontend builds
its columns from what it finds, so adding a measurement needs no frontend
change.

Each measurement documents itself in an `.mdx` file **next to its own
module** — `correlation.py` → `correlation.mdx` — which the app serves at
`/docs/<measurement id>`. Keeping the doc beside the plugin is what lets an
addon ship its own documentation.

Copy `backend/measurements/DOC_TEMPLATE.mdx` to start one. The file is YAML
frontmatter followed by MDX:

```mdx
---
title: Correlation to Fund
summary: How closely a holding has moved with the rest of the fund.
example_etf: SMH        # optional
example_stock: NVDA     # optional
---

## What it measures
...
```

- `title` and `summary` are **required**. Unknown keys are rejected rather
  than ignored, so a typo fails loudly instead of silently doing nothing.
- `example_etf` / `example_stock` choose the fund and holding the worked
  example is computed against, when a particular one illustrates the
  measurement better than the defaults (`DOCS_EXAMPLE_ETF` /
  `DOCS_EXAMPLE_STOCK` in `backend/config.py`). A measurement class can
  declare the same two attributes; the doc's frontmatter wins.
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

`backend/services/portfolio.py` is the arithmetic and the full statement of
the model. Every number on screen depends on the decisions below, and none
of them is guessable from the UI.

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
  divided by the root of the trading time it actually covers. For a window
  of daily rows that is exactly the textbook "daily standard deviation
  times root 252". The scaling matters the moment a window spans storage
  tiers: annualising a weekly bucket as though it were a day reported 54%
  on a real basket whose true figure was 35%.
- **Drawdown is measured on the total**, the only series a holder
  experiences. A single holding can fall much further without the portfolio
  noticing.
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

**`POST /api/portfolio/simulate`** — value a basket over a window. A POST
with a body rather than a GET because a basket of holdings does not belong
in a URL, even though it reads nothing and changes nothing. Nothing is
stored: the portfolio arrives in the request and leaves in the response.

```jsonc
// request
{
  "holdings": [                      // 1–100 entries, tickers unique
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
  }
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
fact about right now, and the frontend retries it.

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

## Frontend

```bash
cd app
npm install
npm run dev
```

Runs at http://localhost:5173 (or the port Vite reports) and talks to the
backend at `http://localhost:8000` by default. Set `VITE_API_BASE` in
`app/.env` to point a build at a different backend — see `.env.example`.

## Running both

Start the backend and frontend in separate terminals, in either order, then
open the frontend URL in your browser.
