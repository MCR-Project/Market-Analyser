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

A portfolio here is a simulation, not an account: a basket of tickers, the
share of the money each one takes, and a stretch of history to value it
over. Nothing is bought and nothing is connected to a broker. Portfolios
live in the browser that authored them — there is no sign-in and no
server-side copy — and reach the backend whole, in the request body of
`POST /api/portfolio/simulate`, which stores nothing.

`backend/services/portfolio.py` is the arithmetic and the full statement of
the model. In outline: weights are ratios and are normalised, so 30/30/30
and 33.33/33.33/33.33 are one portfolio; buy and hold is the default and a
rebalance restores the target weights on the first row of each new period;
an allocation waits in cash until its holding lists, and buys in at that
day's close so the total does not jump.

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
