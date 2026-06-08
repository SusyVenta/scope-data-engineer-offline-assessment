"""
companies.py
------------
/companies endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import psycopg2.extras
from fastapi import APIRouter, HTTPException, Query

from api.db import get_db
from api.models import CompanyOut, CompanyVersionOut, CompareOut, SnapshotOut

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyOut])
def list_companies():
    """List all companies (current version only)."""
    sql = """
        SELECT
            dc.company_id, dc.entity_name,
            ds.sector_name  AS sector,
            dco.country_name AS country,
            dcu.currency_code AS currency,
            dc.accounting_principles,
            dc.business_year_end_month,
            dc.valid_from,
            dc.loaded_at_utc
        FROM dim_company dc
        LEFT JOIN dim_sector   ds  ON ds.sector_id   = dc.sector_id
        LEFT JOIN dim_country  dco ON dco.country_id = dc.country_id
        LEFT JOIN dim_currency dcu ON dcu.currency_id = dc.currency_id
        WHERE dc.is_current = TRUE
        ORDER BY dc.entity_name
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()


@router.get("/compare", response_model=CompareOut)
def compare_companies(
    company_ids: str = Query(..., description="Comma-separated company_ids"),
    as_of_date: Optional[datetime] = Query(None, description="Point-in-time date (ISO 8601)"),
):
    """Compare multiple companies at a point in time.

    Returns the most recent snapshot for each company as of as_of_date
    (or the latest snapshot if as_of_date is not supplied).
    """
    try:
        ids = [int(x.strip()) for x in company_ids.split(",")]
    except ValueError:
        raise HTTPException(status_code=422, detail="company_ids must be comma-separated integers")

    placeholders = ",".join(["%s"] * len(ids))
    if as_of_date:
        sql = f"""
            SELECT DISTINCT ON (f.company_id) f.*
            FROM fact_rating_snapshot f
            WHERE f.company_id IN ({placeholders})
              AND f.loaded_at_utc <= %s
            ORDER BY f.company_id, f.loaded_at_utc DESC
        """
        params = ids + [as_of_date]
    else:
        sql = f"""
            SELECT DISTINCT ON (f.company_id) f.*
            FROM fact_rating_snapshot f
            WHERE f.company_id IN ({placeholders})
            ORDER BY f.company_id, f.loaded_at_utc DESC
        """
        params = ids

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    return CompareOut(as_of_date=as_of_date, companies=rows)


@router.get("/{company_id}", response_model=CompanyVersionOut)
def get_company(company_id: int):
    """Get current version of a company."""
    sql = """
        SELECT
            dc.company_id, dc.entity_name,
            ds.sector_name  AS sector,
            dco.country_name AS country,
            dcu.currency_code AS currency,
            dc.accounting_principles,
            dc.business_year_end_month,
            dc.valid_from, dc.valid_to, dc.is_current,
            dc.loaded_at_utc
        FROM dim_company dc
        LEFT JOIN dim_sector   ds  ON ds.sector_id   = dc.sector_id
        LEFT JOIN dim_country  dco ON dco.country_id = dc.country_id
        LEFT JOIN dim_currency dcu ON dcu.currency_id = dc.currency_id
        WHERE dc.company_id = %s AND dc.is_current = TRUE
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (company_id,))
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")
    return row


@router.get("/{company_id}/versions", response_model=list[CompanyVersionOut])
def get_company_versions(company_id: int):
    """Get all SCD2 versions for a company, ordered from oldest to newest."""
    sql = """
        SELECT
            dc.company_id, dc.entity_name,
            ds.sector_name  AS sector,
            dco.country_name AS country,
            dcu.currency_code AS currency,
            dc.accounting_principles,
            dc.business_year_end_month,
            dc.valid_from, dc.valid_to, dc.is_current,
            dc.loaded_at_utc
        FROM dim_company dc
        LEFT JOIN dim_sector   ds  ON ds.sector_id   = dc.sector_id
        LEFT JOIN dim_country  dco ON dco.country_id = dc.country_id
        LEFT JOIN dim_currency dcu ON dcu.currency_id = dc.currency_id
        WHERE dc.entity_name = (
            SELECT entity_name FROM dim_company WHERE company_id = %s LIMIT 1
        )
        ORDER BY dc.valid_from
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (company_id,))
            rows = cur.fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")
    return rows


@router.get("/{company_id}/history", response_model=list[SnapshotOut])
def get_company_history(company_id: int):
    """Get all rating snapshots for a company, ordered by load date."""
    sql = """
        SELECT * FROM fact_rating_snapshot
        WHERE company_id = %s
        ORDER BY loaded_at_utc
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (company_id,))
            rows = cur.fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No snapshots found for company {company_id}")
    return rows
