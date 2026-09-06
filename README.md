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
