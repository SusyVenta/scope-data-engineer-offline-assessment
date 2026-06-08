"""
main.py
-------
FastAPI application entry point for the corporate ratings API.
"""

from __future__ import annotations

import os
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.routers import companies, snapshots, uploads

app = FastAPI(
    title="Corporate Ratings API",
    description="Query corporate credit rating data loaded by the Airflow pipeline.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(companies.router)
app.include_router(snapshots.router)
app.include_router(uploads.router)


@app.get("/health", tags=["health"])
def health_check():
    """Liveness probe."""
    return JSONResponse({"status": "ok"})


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    """Return the real exception detail in non-production environments."""
    detail = f"{type(exc).__name__}: {exc}"
    if os.getenv("POSTGRES_SCHEMA") != "public":
        return JSONResponse(
            status_code=500,
            content={"detail": detail, "traceback": traceback.format_exc()},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
