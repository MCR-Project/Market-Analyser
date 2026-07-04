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
