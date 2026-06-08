"""
corporate_ratings_dag.py
------------------------
Airflow DAG for the corporate credit rating data pipeline.

Pipeline graph:
    create_tables >> extract_sheets >> validate_data >> transform_data >> load_to_warehouse

Tasks:
  0. create_tables      – Apply all DDL files (CREATE TABLE IF NOT EXISTS).
  1. extract_sheets     – Extract MASTER sheet from each staged .xlsm file;
                          save to extracted_sheets/; push records via XCom.
  2. validate_data      – Run data quality checks; fail if any CRITICAL errors;
                          log quality report for every file.
  3. transform_data     – Normalize records, compute data_hash; push via XCom.
  4. load_to_warehouse  – Incremental load with duplicate detection;
                          skipped files logged as WARNING; update run state.

Connections expected in Airflow (set via env vars in docker-compose):
  • postgres_corporate → corporate database on the postgres service
"""

from __future__ import annotations

import json
import logging
import os
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

DEFAULT_POSTGRES_CONN_ID: str = "postgres_corporate"
SQL_DIR: Path = Path("/opt/airflow/sql")
INPUT_FILES_DIR: str = os.getenv("INPUT_FILES_DIR", "/opt/airflow/data/input_files")
EXTRACTED_SHEETS_DIR: str = os.getenv("EXTRACTED_SHEETS_DIR", "/opt/airflow/data/extracted_sheets")

_LOG = logging.getLogger(__name__)
_ALERT_EMAIL: str = os.getenv("ALERT_EMAIL", "")

DEFAULT_ARGS = {
    "owner": "data_engineering",
    "depends_on_past": False,
    "email_on_failure": bool(_ALERT_EMAIL),
    "email_on_retry": False,
    "email": [_ALERT_EMAIL] if _ALERT_EMAIL else [],
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


# ---------------------------------------------------------------------------
# Task 0 — Create tables
# ---------------------------------------------------------------------------

def _create_output_tables(**context) -> None:
    postgres_conn_id = context["dag_run"].conf.get("conn_id", DEFAULT_POSTGRES_CONN_ID)
    ddl_dir = SQL_DIR / "ddl"
    hook = PostgresHook(postgres_conn_id=postgres_conn_id)
    conn = hook.get_conn()
    try:
        for ddl_file in sorted(ddl_dir.glob("*.sql")):
            sql = ddl_file.read_text()
            _LOG.info("Applying DDL: %s", ddl_file.name)
            with conn.cursor() as cur:
                cur.execute(sql)
        conn.commit()
        _LOG.info("All DDL files applied.")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Task 1 — Extract sheets
# ---------------------------------------------------------------------------

def _extract_sheets(
    input_files_dir: str,
    extracted_sheets_dir: str,
    dag_run_id: str,
    **context,
) -> None:
    postgres_conn_id = context["dag_run"].conf.get("conn_id", DEFAULT_POSTGRES_CONN_ID)
    import sys
    sys.path.insert(0, "/opt/airflow")

    from corporate_pipeline.extractor import extract_master_sheet, parse_master_record, save_extracted_sheet
    from corporate_pipeline.loader import begin_pipeline_run, get_last_successful_run_time, stage_modified_files

    hook = PostgresHook(postgres_conn_id=postgres_conn_id)
    conn = hook.get_conn()

    try:
        run_id = begin_pipeline_run(conn, dag_run_id)
        conn.commit()
        _LOG.info("[extract] Pipeline run started: run_id=%s", run_id)

        last_run = get_last_successful_run_time(conn)
        _LOG.info("[extract] Last successful run: %s", last_run)

        staged = stage_modified_files(input_files_dir, last_run)
        _LOG.info("[extract] Staged %d file(s): %s", len(staged), [f.name for f in staged])

        records = []
        mtimes = {}
        for filepath in staged:
            df = extract_master_sheet(filepath)
            save_extracted_sheet(df, extracted_sheets_dir, filepath.stem)
            record = parse_master_record(df, filepath.name)
            records.append(record)
            mtimes[filepath.name] = datetime.fromtimestamp(
                filepath.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            _LOG.info("[extract] Extracted %s → %s", filepath.name, record.rated_entity)

        # Push to XCom (serialise as JSON-friendly dicts)
        ti = context["ti"]
        ti.xcom_push(key="run_id", value=run_id)
        ti.xcom_push(key="file_mtimes", value=mtimes)
        ti.xcom_push(key="staged_count", value=len(staged))
        # Pickle records because RawMasterRecord contains dicts that may not JSON-serialize cleanly
        ti.xcom_push(key="records_pickle", value=pickle.dumps(records).hex())

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Task 2 — Validate data
# ---------------------------------------------------------------------------

def _validate_data(**context) -> None:
    import sys, pickle
    sys.path.insert(0, "/opt/airflow")

    from corporate_pipeline.validator import generate_quality_report, is_valid, validate_record

    ti = context["ti"]
    records_hex = ti.xcom_pull(task_ids="extract_sheets", key="records_pickle")
    records = pickle.loads(bytes.fromhex(records_hex))

    quality_reports = []
    has_critical_failure = False

    for record in records:
        results = validate_record(record)
        report = generate_quality_report(results, record.source_filename)
        quality_reports.append(report)

        if not is_valid(results):
            has_critical_failure = True
            _LOG.error(
                "[validate] CRITICAL failures in %s:\n%s",
                record.source_filename,
                json.dumps(report["failures"], indent=2),
            )
        else:
            _LOG.info(
                "[validate] %s passed validation (completeness=%.1f%%, validity=%.1f%%)",
                record.source_filename,
                report["completeness_pct"],
                report["validity_pct"],
            )
            if report["failures"]:
                _LOG.warning(
                    "[validate] %s warnings in %s:\n%s",
                    len(report["failures"]),
                    record.source_filename,
                    json.dumps(report["failures"], indent=2),
                )

    _LOG.info("[validate] Quality report summary:\n%s", json.dumps(quality_reports, indent=2))

    if has_critical_failure:
        raise ValueError(
            "One or more files failed data quality validation. "
            "See task logs for details. Pipeline halted."
        )


# ---------------------------------------------------------------------------
# Task 3 — Transform data
# ---------------------------------------------------------------------------

def _transform_data(**context) -> None:
    import sys, pickle
    from datetime import datetime, timezone
    sys.path.insert(0, "/opt/airflow")

    from corporate_pipeline.transformer import transform_all

    ti = context["ti"]
    records_hex = ti.xcom_pull(task_ids="extract_sheets", key="records_pickle")
    records = pickle.loads(bytes.fromhex(records_hex))
    mtimes_iso = ti.xcom_pull(task_ids="extract_sheets", key="file_mtimes") or {}

    mtimes = {
        fname: datetime.fromisoformat(ts)
        for fname, ts in mtimes_iso.items()
    }

    transformed = transform_all(records, mtimes)
    _LOG.info("[transform] Transformed %d record(s).", len(transformed))
    for r in transformed:
        _LOG.info("[transform] %s → hash=%s", r.source_filename, r.data_hash[:12])

    ti.xcom_push(key="records_pickle", value=pickle.dumps(transformed).hex())


# ---------------------------------------------------------------------------
# Task 4 — Load to warehouse
# ---------------------------------------------------------------------------

def _load_to_warehouse(**context) -> None:
    postgres_conn_id = context["dag_run"].conf.get("conn_id", DEFAULT_POSTGRES_CONN_ID)
    import sys, pickle
    sys.path.insert(0, "/opt/airflow")

    from corporate_pipeline.loader import (
        complete_pipeline_run,
        load_record,
    )

    ti = context["ti"]
    records_hex = ti.xcom_pull(task_ids="transform_data", key="records_pickle")
    records = pickle.loads(bytes.fromhex(records_hex))
    run_id = ti.xcom_pull(task_ids="extract_sheets", key="run_id")
    staged_count = ti.xcom_pull(task_ids="extract_sheets", key="staged_count") or 0
    dag_run_id = context["dag_run"].run_id

    hook = PostgresHook(postgres_conn_id=postgres_conn_id)
    conn = hook.get_conn()

    loaded = 0
    skipped = 0

    try:
        for record in records:
            result = load_record(conn, record, dag_run_id)
            conn.commit()
            if result == "loaded":
                loaded += 1
            else:
                skipped += 1
                _LOG.warning(
                    "[load] DUPLICATE SKIPPED: %s (hash=%s already loaded in a previous run). "
                    "No data was inserted. Exiting this file successfully.",
                    record.source_filename,
                    record.data_hash[:12],
                )

        complete_pipeline_run(conn, run_id, "success", staged_count, loaded, skipped)
        conn.commit()
        _LOG.info(
            "[load] Pipeline complete. staged=%d loaded=%d skipped=%d",
            staged_count, loaded, skipped,
        )

    except Exception:
        complete_pipeline_run(conn, run_id, "failed", staged_count, loaded, skipped)
        conn.commit()
        conn.close()
        raise

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DAG factory — reused by the integration-test DAG variant
# ---------------------------------------------------------------------------

def build_dag(dag_id: str, extra_tags: list[str] | None = None) -> DAG:
    tags = ["corporate", "etl", "ratings"] + (extra_tags or [])
    with DAG(
        dag_id=dag_id,
        description="ETL pipeline: extract → validate → transform → load corporate rating Excel files",
        default_args=DEFAULT_ARGS,
        start_date=datetime(2024, 1, 1),
        schedule_interval=None,
        catchup=False,
        tags=tags,
        max_active_runs=1,
    ) as dag:

        create_tables = PythonOperator(
            task_id="create_tables",
            python_callable=_create_output_tables,
        )

        extract_sheets = PythonOperator(
            task_id="extract_sheets",
            python_callable=_extract_sheets,
            op_kwargs={
                "input_files_dir": INPUT_FILES_DIR,
                "extracted_sheets_dir": EXTRACTED_SHEETS_DIR,
                "dag_run_id": "{{ run_id }}",
            },
        )

        validate_data = PythonOperator(
            task_id="validate_data",
            python_callable=_validate_data,
        )

        transform_data = PythonOperator(
            task_id="transform_data",
            python_callable=_transform_data,
        )

        load_to_warehouse = PythonOperator(
            task_id="load_to_warehouse",
            python_callable=_load_to_warehouse,
        )

        create_tables >> extract_sheets >> validate_data >> transform_data >> load_to_warehouse

    return dag


# ---------------------------------------------------------------------------
# Production DAG
# ---------------------------------------------------------------------------

dag = build_dag("corporate_ratings_pipeline")
