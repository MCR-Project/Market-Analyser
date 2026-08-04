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

### Data pipeline

The tracked universe lives in Supabase (`etfs`, `ticker`, `etf_holdings`,
`prices` tables) — there is no hardcoded list. Three scripts maintain it
(all run from `backend/`, needing `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`
in `.env` — see `.env.example`):

- `python scripts/add_ticker.py NVDA "AAPL:Apple Inc."` — manually add or
  update tickers.
- `python fetcher/vaneck.py --output vaneck_holdings.json [--limit N]` —
  run from the repo root (deps in `fetcher/requirements.txt`, no API key):
  scrapes the provider's website for its full ETF holdings and writes them
  as JSON (schema in `fetcher/common.py`). One fetcher per provider lives
  in `fetcher/` (`vaneck.py`, `spdr.py`, `ark.py`).
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

## Frontend

```bash
cd app
npm install
npm run dev
```

Runs at http://localhost:5173 (or the port Vite reports) and talks to the
backend at `http://localhost:8000`.

## Running both

Start the backend and frontend in separate terminals, in either order, then
open the frontend URL in your browser.
