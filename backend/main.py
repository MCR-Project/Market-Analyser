"""
FastAPI application entry point.

Mounts the /api router, enables CORS for frontend dev servers,
exposes a /health endpoint for liveness checks, and maps DataUnavailable
onto 503 so a transient upstream failure reads as retryable rather than
as a bug (500) or as a missing resource (404).

Start with:  python -m uvicorn main:app --port 8000 --reload
API docs at: http://localhost:8000/docs
"""

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from api.routes import router
from measurements.registry import measurement_router
from services.market_data import DataUnavailable, SymbolNotFound

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = FastAPI(
    title="MCR-3 Correlation Dashboard API",
    description="Real-time ETF holdings, stock correlations, and market data via Yahoo Finance",
    version="1.0.0",
)

# Origins allowed to make cross-origin requests, comma-separated via
# CORS_ORIGINS (see .env.example). Defaults to the local frontend dev
# ports so `npm run dev` keeps working with no environment variables set.
_default_origins = "http://localhost:5173,http://localhost:3456"
allow_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", _default_origins).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    # POST is here for one endpoint: /api/portfolio/simulate, which reads
    # nothing and stores nothing but takes a whole portfolio in its body
    # rather than in a URL. Without it the browser's preflight fails and
    # the simulation is unreachable from the frontend, while curl works
    # fine - a confusing way to discover a one-word omission.
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(measurement_router)


@app.exception_handler(DataUnavailable)
def data_unavailable(request: Request, exc: DataUnavailable):
    """Answer 503 when a live data source failed, not 500.

    The status code is the whole point: the frontend's useFetch auto-
    retries 5xx/429 and does not retry a 404, so a Yahoo/Supabase blip
    during startup now heals itself instead of parking the dashboard on
    an error panel until someone reloads the page. Retry-After documents
    the same interval useFetch already backs off by.
    """
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc)},
        headers={"Retry-After": "3"},
    )


@app.exception_handler(SymbolNotFound)
def symbol_not_found(request: Request, exc: SymbolNotFound):
    """Answer 404 when the upstream says the symbol doesn't exist.

    The mirror of the handler above, and the reason the two exceptions are
    kept apart: useFetch retries a 5xx and never retries a 4xx, so this is
    what stops a typo'd ticker being re-requested every three seconds
    forever under a panel that claims it is about to work.
    """
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.get("/health")
def health():
    """Liveness probe — returns 200 if the server is up."""
    return {"status": "ok"}
