"""
snapshots.py
------------
/snapshots endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import psycopg2.extras
from fastapi import APIRouter, HTTPException, Path, Query

from api.db import get_db
from api.models import SnapshotOut

router = APIRouter(prefix="/snapshots", tags=["snapshots"])

_SNAPSHOT_COLS = """
    fr.rating_id AS snapshot_id, fr.upload_id, fr.company_id,
    dc.entity_name,
    dc.sector_name AS sector,
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
"""


@router.get(
    "/latest",
    response_model=list[SnapshotOut],
    summary="Get the latest snapshot for each company",
    description=(
        "Returns one row per entity — the most recently loaded `fact_ratings` record. "
        "Useful as a quick BI-friendly view of the current state of all companies.\n\n"
        "**Example call:** `GET /snapshots/latest`"
    ),
)
def get_latest_snapshots():
    sql = f"""
        SELECT DISTINCT ON (dc.entity_name) {_SNAPSHOT_COLS}
        {_SNAPSHOT_JOIN}
        ORDER BY dc.entity_name, fr.loaded_at_utc DESC
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()


@router.get(
    "",
    response_model=list[SnapshotOut],
    summary="List snapshots with optional filters",
    description=(
        "Returns all rating snapshots, optionally filtered by company, date range, "
        "sector, country, or currency. All filters are combined with AND.\n\n"
        "**Sample values from the DB:**\n"
        "- `company_id`: `1`, `2`, `3`, `4`\n"
        "- `sector`: `Personal & Household Goods`, `Automobiles & Parts`\n"
        "- `country`: `Federal Republic of Germany`, `Swiss Confederation`\n"
        "- `currency`: `EUR`, `CHF`\n"
        "- Date format: `YYYY-MM-DDTHH:MM:SSZ` — e.g. `2026-06-08T18:00:00Z`\n\n"
        "**Example call:** `GET /snapshots?currency=EUR`"
    ),
)
def list_snapshots(
    company_id: Optional[int] = Query(
        None,
        description="Filter by internal company_id (surrogate key from dim_company).",
        example=1,
    ),
    from_date: Optional[datetime] = Query(
        None,
        description="Include only snapshots loaded on or after this date (ISO 8601). Example: `2026-06-08T18:00:00Z`",
        example="2026-06-08T18:00:00Z",
    ),
    to_date: Optional[datetime] = Query(
        None,
        description="Include only snapshots loaded on or before this date (ISO 8601). Example: `2026-06-08T20:00:00Z`",
        example="2026-06-08T20:00:00Z",
    ),
    sector: Optional[str] = Query(
        None,
        description="Case-insensitive partial match on sector name. Example: `Automobiles`",
        example="Automobiles",
    ),
    country: Optional[str] = Query(
        None,
        description="Case-insensitive partial match on country name. Example: `Germany`",
        example="Germany",
    ),
    currency: Optional[str] = Query(
        None,
        description="Exact match on reporting currency (case-insensitive). Example: `EUR` or `CHF`",
        example="EUR",
    ),
):
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
        conditions.append("dc.sector_name ILIKE %s")
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


@router.get(
    "/{snapshot_id}",
    response_model=SnapshotOut,
    summary="Get a specific snapshot by ID",
    description=(
        "Returns the full rating record for a single snapshot. "
        "The `snapshot_id` corresponds to `fact_ratings.rating_id`.\n\n"
        "**Sample snapshot IDs in the DB:** `1`, `2`, `3`, `4`\n\n"
        "**Example call:** `GET /snapshots/1`"
    ),
)
def get_snapshot(
    snapshot_id: int = Path(
        ...,
        description="Rating snapshot ID (fact_ratings.rating_id). Sample values: 1, 2, 3, 4.",
        example=1,
    ),
):
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
