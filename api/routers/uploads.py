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


@router.get("/stats", response_model=UploadStatsOut)
def get_upload_stats():
    """Aggregate stats across all uploads."""
    sql = """
        SELECT
            COUNT(*)                               AS total_uploads,
            COUNT(DISTINCT source_filename)        AS unique_files,
            COUNT(DISTINCT f.company_id)           AS unique_companies,
            MIN(u.loaded_at_utc)                   AS earliest_upload,
            MAX(u.loaded_at_utc)                   AS latest_upload
        FROM upload_log u
        LEFT JOIN fact_rating_snapshot f ON f.upload_id = u.upload_id
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
    """Get a single upload entry plus all snapshots produced from it."""
    upload_sql = "SELECT * FROM upload_log WHERE upload_id = %s"
    snapshots_sql = "SELECT * FROM fact_rating_snapshot WHERE upload_id = %s ORDER BY snapshot_id"

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(upload_sql, (upload_id,))
            upload = cur.fetchone()
            if upload is None:
                raise HTTPException(status_code=404, detail=f"Upload {upload_id} not found")
            cur.execute(snapshots_sql, (upload_id,))
            snapshots = cur.fetchall()

    return {**upload, "snapshots": snapshots}
