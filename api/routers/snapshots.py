"""
snapshots.py
------------
/snapshots endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import psycopg2.extras
from fastapi import APIRouter, HTTPException, Query

from api.db import get_db
from api.models import SnapshotOut

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


@router.get("/latest", response_model=list[SnapshotOut])
def get_latest_snapshots():
    """Get the most recent snapshot for each company."""
    sql = """
        SELECT DISTINCT ON (entity_name) *
        FROM fact_rating_snapshot
        ORDER BY entity_name, loaded_at_utc DESC
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()


@router.get("", response_model=list[SnapshotOut])
def list_snapshots(
    company_id: Optional[int] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    sector: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
):
    """List snapshots with optional filters."""
    conditions = []
    params: list = []

    if company_id is not None:
        conditions.append("company_id = %s")
        params.append(company_id)
    if from_date is not None:
        conditions.append("loaded_at_utc >= %s")
        params.append(from_date)
    if to_date is not None:
        conditions.append("loaded_at_utc <= %s")
        params.append(to_date)
    if sector is not None:
        conditions.append("sector ILIKE %s")
        params.append(f"%{sector}%")
    if country is not None:
        conditions.append("country ILIKE %s")
        params.append(f"%{country}%")
    if currency is not None:
        conditions.append("currency = %s")
        params.append(currency.upper())

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT * FROM fact_rating_snapshot {where} ORDER BY loaded_at_utc DESC"

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


@router.get("/{snapshot_id}", response_model=SnapshotOut)
def get_snapshot(snapshot_id: int):
    """Get a specific snapshot by ID."""
    sql = "SELECT * FROM fact_rating_snapshot WHERE snapshot_id = %s"
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (snapshot_id,))
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    return row
