"""
uploads.py
----------
/uploads endpoints.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg2.extras
from fastapi import APIRouter, HTTPException
from fastapi import Path as FPath
from fastapi.responses import FileResponse

from api.db import get_db
from api.models import UploadDetailOut, UploadOut, UploadStatsOut

router = APIRouter(prefix="/uploads", tags=["uploads"])

_INPUT_FILES_DIR = Path(os.getenv("INPUT_FILES_DIR", "/app/data/input_files"))

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


@router.get(
    "/stats",
    response_model=UploadStatsOut,
    summary="Upload statistics",
    description=(
        "Returns aggregate metrics across all upload log entries: total uploads, "
        "unique source files, unique companies loaded, and the earliest/latest load timestamps.\n\n"
        "**Example call:** `GET /uploads/stats`"
    ),
)
def get_upload_stats():
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


@router.get(
    "",
    response_model=list[UploadOut],
    summary="List all uploads",
    description=(
        "Returns every entry in `upload_log`, newest first. Each row tracks one "
        "processed source file including its SHA-256 hash, modification time, and "
        "Airflow run ID.\n\n"
        "**Sample upload IDs in the DB:** `1` (`corporates_A_1.xlsm`), "
        "`2` (`corporates_A_2.xlsm`), `3` (`corporates_B_1.xlsm`), `4` (`corporates_B_2.xlsm`)\n\n"
        "**Example call:** `GET /uploads`"
    ),
)
def list_uploads():
    sql = "SELECT * FROM upload_log ORDER BY loaded_at_utc DESC"
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()


@router.get(
    "/{upload_id}/details",
    response_model=UploadDetailOut,
    summary="Get upload details with rating snapshots",
    description=(
        "Returns the upload log entry plus all `fact_ratings` rows produced from that file.\n\n"
        "**Sample upload IDs:** `1`, `2`, `3`, `4`\n\n"
        "**Example call:** `GET /uploads/1/details`"
    ),
)
def get_upload_details(
    upload_id: int = FPath(
        ...,
        description="Upload log ID. Sample values: 1, 2, 3, 4.",
        examples=[1],
    ),
):
    upload_sql = "SELECT * FROM upload_log WHERE upload_id = %s"
    snapshots_sql = f"""
        SELECT {_SNAPSHOT_COLS}
        FROM fact_ratings fr
        LEFT JOIN dim_company dc ON dc.company_id = fr.company_id
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


@router.get(
    "/{upload_id}/file",
    summary="Download original source file",
    description=(
        "Streams the original `.xlsm` source file that was processed for this upload.\n\n"
        "**Sample upload IDs:** `1` (`corporates_A_1.xlsm`), `2` (`corporates_A_2.xlsm`), "
        "`3` (`corporates_B_1.xlsm`), `4` (`corporates_B_2.xlsm`)\n\n"
        "**Example call:** `GET /uploads/1/file`"
    ),
    response_description="The original .xlsm Excel file as a binary download.",
)
def download_upload_file(
    upload_id: int = FPath(
        ...,
        description="Upload log ID. Sample values: 1, 2, 3, 4.",
        examples=[1],
    ),
):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT source_filename FROM upload_log WHERE upload_id = %s", (upload_id,))
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Upload {upload_id} not found")

    filename = row["source_filename"]
    file_path = _INPUT_FILES_DIR / filename
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Source file '{filename}' is not available on this server",
        )
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.ms-excel.sheet.macroenabled.12",
    )
