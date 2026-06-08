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

_SNAPSHOT_COLS = """
    fr.rating_id AS snapshot_id, fr.upload_id, fr.company_id,
    dc.entity_name,
    ds.sector_name AS sector,
    dc.country,
    dc.reporting_currency AS currency,
    fr.business_risk_profile, fr.financial_risk_profile,
    fr.blended_industry_risk_profile, fr.competitive_positioning,
    fr.market_share, fr.diversification, fr.operating_profitability,
    fr.sector_company_specific_factor_1, fr.sector_company_specific_factor_2,
    fr.leverage, fr.interest_cover, fr.cash_flow_cover, fr.liquidity,
    fr.data_hash, fr.loaded_at_utc
"""

_SNAPSHOT_JOIN = """
    FROM fact_ratings fr
    LEFT JOIN dim_company dc ON dc.company_id = fr.company_id
    LEFT JOIN dim_sector  ds ON ds.sector_id  = fr.sector_id
"""


@router.get("/latest", response_model=list[SnapshotOut])
def get_latest_snapshots():
    """Get the most recent snapshot for each company."""
    sql = f"""
        SELECT DISTINCT ON (dc.entity_name) {_SNAPSHOT_COLS}
        {_SNAPSHOT_JOIN}
        ORDER BY dc.entity_name, fr.loaded_at_utc DESC
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
        conditions.append("fr.company_id = %s")
        params.append(company_id)
    if from_date is not None:
        conditions.append("fr.loaded_at_utc >= %s")
        params.append(from_date)
    if to_date is not None:
        conditions.append("fr.loaded_at_utc <= %s")
        params.append(to_date)
    if sector is not None:
        conditions.append("ds.sector_name ILIKE %s")
        params.append(f"%{sector}%")
    if country is not None:
        conditions.append("dc.country ILIKE %s")
        params.append(f"%{country}%")
    if currency is not None:
        conditions.append("dc.reporting_currency = %s")
        params.append(currency.upper())

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT {_SNAPSHOT_COLS} {_SNAPSHOT_JOIN} {where} ORDER BY fr.loaded_at_utc DESC"

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


@router.get("/{snapshot_id}", response_model=SnapshotOut)
def get_snapshot(snapshot_id: int):
    """Get a specific snapshot by ID."""
    sql = f"""
        SELECT {_SNAPSHOT_COLS}
        {_SNAPSHOT_JOIN}
        WHERE fr.rating_id = %s
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (snapshot_id,))
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    return row
