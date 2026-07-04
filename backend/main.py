"""
FastAPI application entry point.

Mounts the /api router, enables CORS for frontend dev servers,
and exposes a /health endpoint for liveness checks.

Start with:  python -m uvicorn main:app --port 8000 --reload
API docs at: http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from measurements.registry import measurement_router

app = FastAPI(
    title="MCR-3 Correlation Dashboard API",
    description="Real-time ETF holdings, stock correlations, and market data via Yahoo Finance",
    version="1.0.0",
)

# Allow all origins in development — the frontend may run on :3456 or :5173.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(measurement_router)


@app.get("/health")
def health():
    """Liveness probe — returns 200 if the server is up."""
    return {"status": "ok"}
