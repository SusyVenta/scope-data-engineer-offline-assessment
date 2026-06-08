"""
loader.py
---------
Incremental load of RatingRecord objects into the corporate PostgreSQL warehouse.

Incremental logic:
  1. On DAG start, record the run in pipeline_run_state (status='running').
  2. Query the last successful run's completed_at_utc.
  3. For each file, compare os.path.getmtime() to that timestamp.
     Files modified AFTER the last run are staged (list returned to caller).
  4. For each staged file: check upload_log for its data_hash.
     If already present → skip with WARNING (same content already loaded).
     Otherwise:
       a. upsert dim_sector
       b. insert upload_log
       c. SCD2 upsert dim_company (includes segmentation criteria comparison)
       d. upsert dim_industry_risk entries and insert company_industry_risk bridge
       e. upsert dim_rating_methodology entries and insert company_methodology bridge
       f. insert fact_ratings
       g. insert fact_scope_credit (one row per metric × year)
  5. On completion, update pipeline_run_state with final status and counts.

All DB operations for one record are wrapped in a single transaction;
a failure on one file does not roll back others.

Public API:
  get_last_successful_run_time(conn)      -> datetime | None
  stage_modified_files(input_dir, last)   -> list[Path]
  hash_already_loaded(conn, data_hash)    -> bool
  load_record(conn, record, dag_run_id)   -> str  ("loaded" | "skipped_duplicate")
  begin_pipeline_run(conn, dag_run_id)    -> int  (run_id)
  complete_pipeline_run(conn, run_id, status, staged, loaded, skipped)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corporate_pipeline.transformer import RatingRecord

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline run state
# ---------------------------------------------------------------------------

def begin_pipeline_run(conn: Any, dag_run_id: str) -> int:
    """Insert a new pipeline_run_state row with status='running'.
    Returns the run_id."""
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_run_state
                (dag_run_id, started_at_utc, status)
            VALUES (%s, %s, 'running')
            ON CONFLICT (dag_run_id) DO UPDATE
                SET started_at_utc = EXCLUDED.started_at_utc,
                    status = 'running',
                    completed_at_utc = NULL
            RETURNING run_id
            """,
            (dag_run_id, now),
        )
        return cur.fetchone()[0]


def complete_pipeline_run(
    conn: Any,
    run_id: int,
    status: str,
    files_staged: int = 0,
    files_loaded: int = 0,
    files_skipped: int = 0,
) -> None:
    """Update pipeline_run_state on completion."""
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pipeline_run_state
            SET completed_at_utc = %s,
                status           = %s,
                files_staged     = %s,
                files_loaded     = %s,
                files_skipped    = %s
            WHERE run_id = %s
            """,
            (now, status, files_staged, files_loaded, files_skipped, run_id),
        )


def get_last_successful_run_time(conn: Any) -> datetime | None:
    """Return the completed_at_utc of the most recent successful run, or None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT completed_at_utc
            FROM pipeline_run_state
            WHERE status = 'success'
            ORDER BY completed_at_utc DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# File staging
# ---------------------------------------------------------------------------

def stage_modified_files(
    input_dir: str | Path,
    last_run_at: datetime | None,
) -> list[Path]:
    """Return .xlsm files in input_dir whose mtime > last_run_at.

    If last_run_at is None (first run), all files are returned.
    """
    input_dir = Path(input_dir)
    staged: list[Path] = []
    for filepath in sorted(input_dir.glob("*.xlsm")):
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=timezone.utc)
        if last_run_at is None or mtime > last_run_at:
            staged.append(filepath)
    return staged


# ---------------------------------------------------------------------------
# Deduplication check
# ---------------------------------------------------------------------------

def hash_already_loaded(conn: Any, data_hash: str) -> bool:
    """Return True if data_hash already exists in upload_log."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM upload_log WHERE data_hash = %s LIMIT 1",
            (data_hash,),
        )
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Dimension upserts
# ---------------------------------------------------------------------------

def _upsert_sector(conn: Any, sector_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dim_sector (sector_name)
            VALUES (%s)
            ON CONFLICT (sector_name) DO UPDATE SET sector_name = EXCLUDED.sector_name
            RETURNING sector_id
            """,
            (sector_name,),
        )
        return cur.fetchone()[0]


def _upsert_industry_risk(conn: Any, risk_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dim_industry_risk (industry_risk_name)
            VALUES (%s)
            ON CONFLICT (industry_risk_name)
                DO UPDATE SET industry_risk_name = EXCLUDED.industry_risk_name
            RETURNING industry_risk_id
            """,
            (risk_name,),
        )
        return cur.fetchone()[0]


def _upsert_methodology(conn: Any, methodology_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dim_rating_methodology (methodology_name)
            VALUES (%s)
            ON CONFLICT (methodology_name)
                DO UPDATE SET methodology_name = EXCLUDED.methodology_name
            RETURNING methodology_id
            """,
            (methodology_name,),
        )
        return cur.fetchone()[0]


def _insert_upload_log(
    conn: Any,
    record: RatingRecord,
    dag_run_id: str,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO upload_log
                (source_filename, file_modified_at, data_hash, dag_run_id, rows_extracted)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING upload_id
            """,
            (
                record.source_filename,
                record.file_modified_at,
                record.data_hash,
                dag_run_id,
                1,
            ),
        )
        return cur.fetchone()[0]


def _scd2_upsert_company(
    conn: Any,
    record: RatingRecord,
    sector_id: int | None,
    upload_id: int,
    now: datetime,
) -> int:
    """Insert a new dim_company row or return the existing company_id unchanged.

    A new version is created when any of the following change: sector,
    country, reporting currency, accounting principles, business year-end
    month, industry risk segmentation criteria, industry risk weights,
    or applied methodologies.

    Returns the (new or existing) company_id.
    """
    new_risks = _sorted_risks(record)
    new_methodologies = sorted(filter(None, [record.methodology_1, record.methodology_2]))

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT company_id, sector_id, country, reporting_currency,
                   accounting_principles, business_year_end_month,
                   industry_risk_segmentation_criteria
            FROM dim_company
            WHERE entity_name = %s AND is_current = TRUE
            """,
            (record.rated_entity,),
        )
        existing = cur.fetchone()

        if existing:
            (
                existing_id, ex_sector, ex_country, ex_currency,
                ex_accounting, ex_year_end, ex_segmentation,
            ) = existing

            ex_risks = _fetch_existing_risks(cur, existing_id)
            ex_methodologies = _fetch_existing_methodologies(cur, existing_id)

            changed = (
                ex_sector       != sector_id
                or ex_country   != record.country
                or ex_currency  != record.currency
                or ex_accounting != record.accounting_principles
                or ex_year_end  != record.business_year_end_month
                or ex_segmentation != record.segmentation_criteria
                or ex_risks     != new_risks
                or ex_methodologies != new_methodologies
            )

            if not changed:
                return existing_id

            cur.execute(
                """
                UPDATE dim_company
                SET valid_to = %s, is_current = FALSE
                WHERE company_id = %s
                """,
                (now, existing_id),
            )

        cur.execute(
            """
            INSERT INTO dim_company
                (entity_name, sector_id, country, reporting_currency,
                 accounting_principles, business_year_end_month,
                 industry_risk_segmentation_criteria,
                 valid_from, is_current, source_upload_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
            RETURNING company_id
            """,
            (
                record.rated_entity,
                sector_id,
                record.country,
                record.currency,
                record.accounting_principles,
                record.business_year_end_month,
                record.segmentation_criteria,
                now,
                upload_id,
            ),
        )
        return cur.fetchone()[0]


def _sorted_risks(record: RatingRecord) -> list[tuple[str, float]]:
    risks = [
        (record.industry_risk_1, record.industry_weight_1),
        (record.industry_risk_2, record.industry_weight_2),
    ]
    return sorted(
        (name, round(float(w or 0.0), 4))
        for name, w in risks
        if name
    )


def _fetch_existing_risks(cur: Any, company_id: int) -> list[tuple[str, float]]:
    cur.execute(
        """
        SELECT dir.industry_risk_name, cir.weight
        FROM company_industry_risk cir
        JOIN dim_industry_risk dir ON dir.industry_risk_id = cir.industry_risk_id
        WHERE cir.company_id = %s
        """,
        (company_id,),
    )
    return sorted((r[0], round(float(r[1]), 4)) for r in cur.fetchall())


def _fetch_existing_methodologies(cur: Any, company_id: int) -> list[str]:
    cur.execute(
        """
        SELECT drm.methodology_name
        FROM company_methodology cm
        JOIN dim_rating_methodology drm ON drm.methodology_id = cm.methodology_id
        WHERE cm.company_id = %s
        """,
        (company_id,),
    )
    return sorted(r[0] for r in cur.fetchall())


def _insert_company_industry_risks(
    conn: Any, company_id: int, record: RatingRecord
) -> None:
    pairs = [
        (record.industry_risk_1, record.industry_weight_1),
        (record.industry_risk_2, record.industry_weight_2),
    ]
    for risk_name, weight in pairs:
        if not risk_name:
            continue
        risk_id = _upsert_industry_risk(conn, risk_name)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO company_industry_risk (company_id, industry_risk_id, weight)
                VALUES (%s, %s, %s)
                ON CONFLICT (company_id, industry_risk_id) DO NOTHING
                """,
                (company_id, risk_id, round(float(weight or 0.0), 4)),
            )


def _insert_company_methodologies(
    conn: Any, company_id: int, record: RatingRecord
) -> None:
    for methodology_name in [record.methodology_1, record.methodology_2]:
        if not methodology_name:
            continue
        m_id = _upsert_methodology(conn, methodology_name)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO company_methodology (company_id, methodology_id)
                VALUES (%s, %s)
                ON CONFLICT (company_id, methodology_id) DO NOTHING
                """,
                (company_id, m_id),
            )


def _insert_fact_ratings(
    conn: Any,
    record: RatingRecord,
    upload_id: int,
    company_id: int,
    sector_id: int | None,
    now: datetime,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fact_ratings (
                upload_id, company_id, sector_id,
                business_risk_profile, financial_risk_profile,
                blended_industry_risk_profile, competitive_positioning,
                market_share, diversification, operating_profitability,
                sector_company_specific_factor_1, sector_company_specific_factor_2,
                leverage, interest_cover, cash_flow_cover, liquidity,
                data_hash, loaded_at_utc
            ) VALUES (
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s
            )
            """,
            (
                upload_id, company_id, sector_id,
                record.business_risk_profile, record.financial_risk_profile,
                record.blended_industry_risk_profile, record.competitive_positioning,
                record.market_share, record.diversification, record.operating_profitability,
                record.sector_specific_factor_1, record.sector_specific_factor_2,
                record.leverage, record.interest_cover, record.cash_flow_cover,
                record.liquidity_adjustment,
                record.data_hash, now,
            ),
        )


def _insert_fact_scope_credit(
    conn: Any,
    record: RatingRecord,
    upload_id: int,
    company_id: int,
    now: datetime,
) -> None:
    for metric_name, year_values in (record.scope_credit_metrics or {}).items():
        for year, metric_value in year_values.items():
            value_str = str(metric_value) if metric_value is not None else None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO fact_scope_credit
                        (company_id, upload_id, metric_name, year, metric_value, loaded_at_utc)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (upload_id, metric_name, year) DO NOTHING
                    """,
                    (company_id, upload_id, metric_name, str(year), value_str, now),
                )


# ---------------------------------------------------------------------------
# Main load function
# ---------------------------------------------------------------------------

def load_record(
    conn: Any,
    record: RatingRecord,
    dag_run_id: str = "",
) -> str:
    """Load one RatingRecord into the warehouse.

    Returns:
      "loaded"             – record was inserted successfully
      "skipped_duplicate"  – data_hash already in upload_log; nothing inserted
    """
    if hash_already_loaded(conn, record.data_hash):
        _LOG.warning(
            "[loader] SKIPPING %s — data_hash %s already loaded in a previous run.",
            record.source_filename,
            record.data_hash[:12],
        )
        return "skipped_duplicate"

    now = datetime.now(timezone.utc)

    sector_id = _upsert_sector(conn, record.sector) if record.sector else None
    upload_id = _insert_upload_log(conn, record, dag_run_id)
    company_id = _scd2_upsert_company(conn, record, sector_id, upload_id, now)

    _insert_company_industry_risks(conn, company_id, record)
    _insert_company_methodologies(conn, company_id, record)
    _insert_fact_ratings(conn, record, upload_id, company_id, sector_id, now)
    _insert_fact_scope_credit(conn, record, upload_id, company_id, now)

    _LOG.info(
        "[loader] Loaded %s → upload_id=%s company_id=%s hash=%s",
        record.source_filename, upload_id, company_id, record.data_hash[:12],
    )
    return "loaded"
