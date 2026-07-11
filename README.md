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
- `python scripts/complete_database.py [--dry-run] [--etfs SPY QQQ]` —
  complete the ETFs already in the `etfs` table: fill missing metadata from
  [financedatabase](https://pypi.org/project/financedatabase/), discover
  their constituent tickers via yfinance top holdings, validate each one
  (present in financedatabase + yfinance has price data), insert it, and
  backfill its full price history. Idempotent; also runnable on demand via
  the "Complete database (manual)" GitHub Action.
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
