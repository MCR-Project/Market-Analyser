"""
FastAPI application entry point.

Mounts the /api router, enables CORS for frontend dev servers,
and exposes a /health endpoint for liveness checks.

Start with:  python -m uvicorn main:app --port 8000 --reload
API docs at: http://localhost:8000/docs
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from measurements.registry import measurement_router

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
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(measurement_router)


@app.get("/health")
def health():
    """Liveness probe — returns 200 if the server is up."""
    return {"status": "ok"}
