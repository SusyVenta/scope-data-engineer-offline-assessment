"""
uploads.py
----------
/uploads endpoints.
"""

from __future__ import annotations

import psycopg2.extras
from fastapi import APIRouter, HTTPException

from api.db import get_db
from api.models import UploadDetailOut, UploadOut, UploadStatsOut

router = APIRouter(prefix="/uploads", tags=["uploads"])

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


@router.get("/stats", response_model=UploadStatsOut)
def get_upload_stats():
    """Aggregate stats across all uploads."""
    sql = """
        SELECT
            COUNT(*)                               AS total_uploads,
            COUNT(DISTINCT source_filename)        AS unique_files,
            COUNT(DISTINCT fr.company_id)          AS unique_companies,
            MIN(u.loaded_at_utc)                   AS earliest_upload,
            MAX(u.loaded_at_utc)                   AS latest_upload
        FROM upload_log u
        LEFT JOIN fact_ratings fr ON fr.upload_id = u.upload_id
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            row = cur.fetchone()
    return row


@router.get("", response_model=list[UploadOut])
def list_uploads():
    """List all upload log entries, newest first."""
    sql = "SELECT * FROM upload_log ORDER BY loaded_at_utc DESC"
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()


@router.get("/{upload_id}/details", response_model=UploadDetailOut)
def get_upload_details(upload_id: int):
    """Get a single upload entry plus all rating rows produced from it."""
    upload_sql = "SELECT * FROM upload_log WHERE upload_id = %s"
    snapshots_sql = f"""
        SELECT {_SNAPSHOT_COLS}
        FROM fact_ratings fr
        LEFT JOIN dim_company dc ON dc.company_id = fr.company_id
        LEFT JOIN dim_sector  ds ON ds.sector_id  = fr.sector_id
        WHERE fr.upload_id = %s
        ORDER BY fr.rating_id
    """

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(upload_sql, (upload_id,))
            upload = cur.fetchone()
            if upload is None:
                raise HTTPException(status_code=404, detail=f"Upload {upload_id} not found")
            cur.execute(snapshots_sql, (upload_id,))
            snapshots = cur.fetchall()

    return {**upload, "snapshots": snapshots}
