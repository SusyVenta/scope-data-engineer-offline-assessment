"""
test_integration.py
-------------------
End-to-end integration tests for the corporate_ratings_pipeline DAG and REST API.

Requires the full Docker Compose stack to be running:
  docker compose build
  docker compose up -d postgres
  docker compose run --rm airflow-init
  docker compose up -d airflow-webserver airflow-scheduler api

Run via Docker (recommended):
  docker compose --profile integration-test run --rm integration-tests

Run directly against a running stack:
  AIRFLOW_BASE_URL=http://localhost:8090 \
  POSTGRES_HOST=localhost \
  API_BASE_URL=http://localhost:8000 \
      python -m pytest tests/integration -v -s

The module-scoped ``dag_run_id`` fixture triggers the DAG once, waits up to
15 minutes for it to finish, then all test classes share that one run.
"""

from __future__ import annotations

import os
import time
from typing import Any

import psycopg2
import psycopg2.extras
import pytest
import requests

# ---------------------------------------------------------------------------
# Connection configuration (defaults work inside the Docker Compose network)
# ---------------------------------------------------------------------------

AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL", "http://airflow-webserver:8080")
AIRFLOW_AUTH = ("admin", "admin")
DAG_ID = "corporate_ratings_pipeline_integration"

PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB = os.getenv("POSTGRES_DB", "corporate")
PG_USER = os.getenv("POSTGRES_USER", "corporate")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "corporate")
# Schema used by the integration pipeline — never touches the production public schema
PG_SCHEMA = os.getenv("POSTGRES_SCHEMA", "corporate_test")
# Airflow connection ID the DAG uses when triggered by integration tests
AIRFLOW_TEST_CONN_ID = os.getenv("AIRFLOW_TEST_CONN_ID", "postgres_corporate_test")

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000")

POLL_INTERVAL = 15   # seconds between Airflow status checks
TIMEOUT = 900        # max seconds to wait for DAG completion (15 min)

_ACTIVE_STATES = {"queued", "running", "up_for_retry"}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _airflow_get(path: str) -> dict:
    resp = requests.get(f"{AIRFLOW_BASE_URL}/api/v1{path}", auth=AIRFLOW_AUTH, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _airflow_patch(path: str, payload: dict) -> dict:
    resp = requests.patch(
        f"{AIRFLOW_BASE_URL}/api/v1{path}", auth=AIRFLOW_AUTH, json=payload, timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def _airflow_post(path: str, payload: dict | None = None) -> dict:
    resp = requests.post(
        f"{AIRFLOW_BASE_URL}/api/v1{path}", auth=AIRFLOW_AUTH, json=payload or {}, timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def _pg_conn():
    kwargs: dict = dict(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD)
    kwargs["options"] = f"-csearch_path={PG_SCHEMA},public"
    return psycopg2.connect(**kwargs)


def _pg_scalar(sql: str, params=None) -> Any:
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def _pg_rows(sql: str, params=None) -> list[dict]:
    conn = _pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _api_get(path: str, params: dict | None = None) -> Any:
    resp = requests.get(f"{API_BASE_URL}{path}", params=params, timeout=15)
    if not resp.ok:
        print(f"\n[API ERROR] {resp.status_code} GET {path}\n{resp.text[:2000]}")
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trigger_dag_and_wait() -> str:
    """Unpause DAG, cancel active runs, trigger fresh run, wait for success."""
    _airflow_patch(f"/dags/{DAG_ID}", {"is_paused": False})

    existing = _airflow_get(f"/dags/{DAG_ID}/dagRuns?limit=25")
    for run in existing.get("dag_runs", []):
        if run["state"] in _ACTIVE_STATES:
            print(f"\n[integration] Cancelling active run: {run['dag_run_id']}")
            try:
                _airflow_patch(
                    f"/dags/{DAG_ID}/dagRuns/{run['dag_run_id']}",
                    {"state": "failed"},
                )
            except Exception:
                pass
    time.sleep(3)

    run_data = _airflow_post(f"/dags/{DAG_ID}/dagRuns", {"conf": {"conn_id": AIRFLOW_TEST_CONN_ID}})
    run_id = run_data["dag_run_id"]
    print(f"\n[integration] Triggered DAG run: {run_id}")
    print(f"[integration] Waiting up to {TIMEOUT}s …")

    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        status = _airflow_get(f"/dags/{DAG_ID}/dagRuns/{run_id}")
        state = status["state"]
        print(f"[integration] state={state}")
        if state == "success":
            return run_id
        if state in ("failed", "cancelled"):
            tasks = _airflow_get(f"/dags/{DAG_ID}/dagRuns/{run_id}/taskInstances")
            non_success = [
                f"{t['task_id']}={t['state']}"
                for t in tasks["task_instances"]
                if t["state"] != "success"
            ]
            pytest.fail(f"DAG ended with state '{state}'. Tasks: {non_success}")
        time.sleep(POLL_INTERVAL)

    pytest.fail(f"DAG did not complete within {TIMEOUT} seconds.")


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def clean_test_schema():
    """Truncate all tables in the corporate_test schema and delete prior DAG runs.

    Ensures each integration test session starts from a known-empty state so
    the first triggered run always loads all 4 files. The production public
    schema is never touched.
    """
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            # Truncate every table in the corporate_test schema with CASCADE.
            # Using a PL/pgSQL loop means this works whether the tables were
            # created by an old or new DDL version — no hardcoded table list.
            cur.execute(f"""
                DO $$
                DECLARE r record;
                BEGIN
                    FOR r IN
                        SELECT tablename
                        FROM pg_tables
                        WHERE schemaname = '{PG_SCHEMA}'
                    LOOP
                        BEGIN
                            EXECUTE format(
                                'TRUNCATE TABLE %I.%I RESTART IDENTITY CASCADE',
                                '{PG_SCHEMA}', r.tablename
                            );
                        EXCEPTION WHEN OTHERS THEN
                            NULL;
                        END;
                    END LOOP;
                END $$;
            """)
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()

    try:
        existing = _airflow_get(f"/dags/{DAG_ID}/dagRuns?limit=100")
        for run in existing.get("dag_runs", []):
            try:
                requests.delete(
                    f"{AIRFLOW_BASE_URL}/api/v1/dags/{DAG_ID}/dagRuns/{run['dag_run_id']}",
                    auth=AIRFLOW_AUTH,
                    timeout=15,
                )
            except Exception:
                pass
    except Exception:
        pass


@pytest.fixture(scope="module")
def dag_run_id(clean_test_schema):
    """Trigger the corporate_ratings_pipeline DAG once; all tests reuse it."""
    return _trigger_dag_and_wait()


@pytest.fixture(scope="module")
def second_dag_run_id(dag_run_id):
    """Trigger a second run immediately after the first to verify idempotency."""
    return _trigger_dag_and_wait()


# ---------------------------------------------------------------------------
# DAG completion
# ---------------------------------------------------------------------------

class TestDAGCompletion:
    def test_dag_run_succeeded(self, dag_run_id):
        status = _airflow_get(f"/dags/{DAG_ID}/dagRuns/{dag_run_id}")
        assert status["state"] == "success"

    def test_all_tasks_succeeded(self, dag_run_id):
        tasks = _airflow_get(f"/dags/{DAG_ID}/dagRuns/{dag_run_id}/taskInstances")
        for ti in tasks["task_instances"]:
            assert ti["state"] == "success", (
                f"Task '{ti['task_id']}' ended in state '{ti['state']}'"
            )

    def test_expected_tasks_present(self, dag_run_id):
        tasks = _airflow_get(f"/dags/{DAG_ID}/dagRuns/{dag_run_id}/taskInstances")
        task_ids = {t["task_id"] for t in tasks["task_instances"]}
        expected = {"create_tables", "extract_sheets", "validate_data", "transform_data", "load_to_warehouse"}
        assert expected.issubset(task_ids)


# ---------------------------------------------------------------------------
# pipeline_run_state table
# ---------------------------------------------------------------------------

class TestPipelineRunState:
    def test_run_recorded_as_success(self, dag_run_id):
        row = _pg_scalar(
            "SELECT status FROM pipeline_run_state WHERE dag_run_id = %s", (dag_run_id,)
        )
        assert row == "success", f"Expected 'success', got '{row}'"

    def test_started_and_completed_at_are_populated(self, dag_run_id):
        row = _pg_rows(
            "SELECT started_at_utc, completed_at_utc FROM pipeline_run_state WHERE dag_run_id = %s",
            (dag_run_id,),
        )
        assert row, "No pipeline_run_state row for this dag_run_id"
        assert row[0]["started_at_utc"] is not None
        assert row[0]["completed_at_utc"] is not None

    def test_files_loaded_is_positive(self, dag_run_id):
        files_loaded = _pg_scalar(
            "SELECT files_loaded FROM pipeline_run_state WHERE dag_run_id = %s", (dag_run_id,)
        )
        assert files_loaded is not None and files_loaded > 0


# ---------------------------------------------------------------------------
# upload_log table
# ---------------------------------------------------------------------------

class TestUploadLog:
    def test_table_has_rows(self, dag_run_id):
        count = _pg_scalar("SELECT COUNT(*) FROM upload_log")
        assert count > 0, "upload_log is empty"

    def test_no_null_source_filename(self, dag_run_id):
        bad = _pg_scalar(
            "SELECT COUNT(*) FROM upload_log WHERE source_filename IS NULL OR source_filename = ''"
        )
        assert bad == 0

    def test_no_null_data_hash(self, dag_run_id):
        bad = _pg_scalar("SELECT COUNT(*) FROM upload_log WHERE data_hash IS NULL OR data_hash = ''")
        assert bad == 0

    def test_data_hash_length_is_64(self, dag_run_id):
        bad = _pg_scalar("SELECT COUNT(*) FROM upload_log WHERE LENGTH(data_hash) <> 64")
        assert bad == 0, "All data hashes should be 64-character SHA-256 hex strings"

    def test_loaded_at_utc_populated(self, dag_run_id):
        bad = _pg_scalar("SELECT COUNT(*) FROM upload_log WHERE loaded_at_utc IS NULL")
        assert bad == 0

    def test_hashes_are_unique(self, dag_run_id):
        total = _pg_scalar("SELECT COUNT(*) FROM upload_log")
        distinct = _pg_scalar("SELECT COUNT(DISTINCT data_hash) FROM upload_log")
        assert total == distinct, "Duplicate data hashes found in upload_log"


# ---------------------------------------------------------------------------
# Dimension tables
# ---------------------------------------------------------------------------

class TestDimensionTables:
    def test_dim_sector_has_rows(self, dag_run_id):
        count = _pg_scalar("SELECT COUNT(*) FROM dim_sector")
        assert count > 0

    def test_dim_industry_risk_has_rows(self, dag_run_id):
        count = _pg_scalar("SELECT COUNT(*) FROM dim_industry_risk")
        assert count > 0

    def test_dim_rating_methodology_has_rows(self, dag_run_id):
        count = _pg_scalar("SELECT COUNT(*) FROM dim_rating_methodology")
        assert count > 0

    def test_dim_company_has_current_rows(self, dag_run_id):
        count = _pg_scalar("SELECT COUNT(*) FROM dim_company WHERE is_current = TRUE")
        assert count > 0

    def test_dim_company_entity_name_not_null(self, dag_run_id):
        bad = _pg_scalar(
            "SELECT COUNT(*) FROM dim_company WHERE entity_name IS NULL OR entity_name = ''"
        )
        assert bad == 0

    def test_dim_company_loaded_at_utc_populated(self, dag_run_id):
        bad = _pg_scalar("SELECT COUNT(*) FROM dim_company WHERE loaded_at_utc IS NULL")
        assert bad == 0

    def test_dim_company_valid_from_not_null(self, dag_run_id):
        bad = _pg_scalar("SELECT COUNT(*) FROM dim_company WHERE valid_from IS NULL")
        assert bad == 0

    def test_dim_company_current_rows_have_null_valid_to(self, dag_run_id):
        bad = _pg_scalar(
            "SELECT COUNT(*) FROM dim_company WHERE is_current = TRUE AND valid_to IS NOT NULL"
        )
        assert bad == 0

    def test_dim_company_fk_to_sector(self, dag_run_id):
        orphan = _pg_scalar(
            "SELECT COUNT(*) FROM dim_company dc "
            "LEFT JOIN dim_sector ds ON ds.sector_id = dc.sector_id "
            "WHERE dc.sector_id IS NOT NULL AND ds.sector_id IS NULL"
        )
        assert orphan == 0

    def test_company_industry_risk_has_rows(self, dag_run_id):
        count = _pg_scalar("SELECT COUNT(*) FROM company_industry_risk")
        assert count > 0

    def test_company_industry_risk_fk_to_company(self, dag_run_id):
        orphan = _pg_scalar(
            "SELECT COUNT(*) FROM company_industry_risk cir "
            "LEFT JOIN dim_company dc ON dc.company_id = cir.company_id "
            "WHERE dc.company_id IS NULL"
        )
        assert orphan == 0

    def test_company_industry_risk_fk_to_dim_industry_risk(self, dag_run_id):
        orphan = _pg_scalar(
            "SELECT COUNT(*) FROM company_industry_risk cir "
            "LEFT JOIN dim_industry_risk dir ON dir.industry_risk_id = cir.industry_risk_id "
            "WHERE dir.industry_risk_id IS NULL"
        )
        assert orphan == 0

    def test_company_methodology_has_rows(self, dag_run_id):
        count = _pg_scalar("SELECT COUNT(*) FROM company_methodology")
        assert count > 0

    def test_company_methodology_fk_to_company(self, dag_run_id):
        orphan = _pg_scalar(
            "SELECT COUNT(*) FROM company_methodology cm "
            "LEFT JOIN dim_company dc ON dc.company_id = cm.company_id "
            "WHERE dc.company_id IS NULL"
        )
        assert orphan == 0

    def test_company_methodology_fk_to_dim_rating_methodology(self, dag_run_id):
        orphan = _pg_scalar(
            "SELECT COUNT(*) FROM company_methodology cm "
            "LEFT JOIN dim_rating_methodology drm ON drm.methodology_id = cm.methodology_id "
            "WHERE drm.methodology_id IS NULL"
        )
        assert orphan == 0


# ---------------------------------------------------------------------------
# fact_ratings table
# ---------------------------------------------------------------------------

class TestFactRatings:
    def test_table_has_rows(self, dag_run_id):
        count = _pg_scalar("SELECT COUNT(*) FROM fact_ratings")
        assert count > 0

    def test_no_null_data_hash(self, dag_run_id):
        bad = _pg_scalar("SELECT COUNT(*) FROM fact_ratings WHERE data_hash IS NULL")
        assert bad == 0

    def test_data_hash_unique_in_fact(self, dag_run_id):
        total = _pg_scalar("SELECT COUNT(*) FROM fact_ratings")
        distinct = _pg_scalar("SELECT COUNT(DISTINCT data_hash) FROM fact_ratings")
        assert total == distinct, "Duplicate data_hash values found in fact_ratings"

    def test_loaded_at_utc_populated(self, dag_run_id):
        bad = _pg_scalar("SELECT COUNT(*) FROM fact_ratings WHERE loaded_at_utc IS NULL")
        assert bad == 0

    def test_fk_to_upload_log(self, dag_run_id):
        orphan = _pg_scalar(
            "SELECT COUNT(*) FROM fact_ratings fr "
            "LEFT JOIN upload_log u ON u.upload_id = fr.upload_id "
            "WHERE u.upload_id IS NULL"
        )
        assert orphan == 0

    def test_fk_to_dim_company(self, dag_run_id):
        orphan = _pg_scalar(
            "SELECT COUNT(*) FROM fact_ratings fr "
            "LEFT JOIN dim_company dc ON dc.company_id = fr.company_id "
            "WHERE dc.company_id IS NULL"
        )
        assert orphan == 0

    def test_rating_count_matches_upload_rows_extracted(self, dag_run_id):
        """rows_extracted in upload_log should equal fact_ratings inserted for that upload."""
        mismatched = _pg_scalar(
            "SELECT COUNT(*) FROM ("
            "  SELECT u.upload_id, u.rows_extracted, COUNT(fr.rating_id) AS actual "
            "  FROM upload_log u "
            "  LEFT JOIN fact_ratings fr ON fr.upload_id = u.upload_id "
            "  GROUP BY u.upload_id, u.rows_extracted "
            "  HAVING u.rows_extracted IS NOT NULL AND u.rows_extracted <> COUNT(fr.rating_id)"
            ") t"
        )
        assert mismatched == 0


# ---------------------------------------------------------------------------
# fact_scope_credit table
# ---------------------------------------------------------------------------

class TestFactScopeCredit:
    def test_table_has_rows(self, dag_run_id):
        count = _pg_scalar("SELECT COUNT(*) FROM fact_scope_credit")
        assert count > 0

    def test_no_null_metric_name(self, dag_run_id):
        bad = _pg_scalar(
            "SELECT COUNT(*) FROM fact_scope_credit WHERE metric_name IS NULL OR metric_name = ''"
        )
        assert bad == 0

    def test_no_null_year(self, dag_run_id):
        bad = _pg_scalar(
            "SELECT COUNT(*) FROM fact_scope_credit WHERE year IS NULL OR year = ''"
        )
        assert bad == 0

    def test_no_duplicates(self, dag_run_id):
        dups = _pg_scalar(
            "SELECT COUNT(*) FROM ("
            "  SELECT upload_id, metric_name, year, COUNT(*) "
            "  FROM fact_scope_credit "
            "  GROUP BY upload_id, metric_name, year "
            "  HAVING COUNT(*) > 1"
            ") t"
        )
        assert dups == 0

    def test_fk_to_upload_log(self, dag_run_id):
        orphan = _pg_scalar(
            "SELECT COUNT(*) FROM fact_scope_credit fsc "
            "LEFT JOIN upload_log u ON u.upload_id = fsc.upload_id "
            "WHERE u.upload_id IS NULL"
        )
        assert orphan == 0

    def test_fk_to_dim_company(self, dag_run_id):
        orphan = _pg_scalar(
            "SELECT COUNT(*) FROM fact_scope_credit fsc "
            "LEFT JOIN dim_company dc ON dc.company_id = fsc.company_id "
            "WHERE dc.company_id IS NULL"
        )
        assert orphan == 0


# ---------------------------------------------------------------------------
# Idempotency: second run must skip all duplicates
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_second_run_loads_nothing(self, second_dag_run_id):
        """Re-triggering with unchanged files: nothing new staged or loaded."""
        row = _pg_rows(
            "SELECT status, files_staged, files_loaded, files_skipped "
            "FROM pipeline_run_state WHERE dag_run_id = %s",
            (second_dag_run_id,),
        )
        assert row, "No pipeline_run_state row for second run"
        assert row[0]["status"] == "success", (
            f"Second run did not succeed: {row[0]['status']}"
        )
        assert row[0]["files_loaded"] == 0, (
            f"Expected files_loaded=0 on second run, got {row[0]['files_loaded']}"
        )

    def test_fact_ratings_count_unchanged_after_second_run(self, second_dag_run_id, dag_run_id):
        """The total rating count must be the same after the idempotent second run."""
        count_first_run = _pg_scalar("SELECT COUNT(*) FROM fact_ratings")
        assert count_first_run > 0, "No ratings after first run"
        count_after_second = _pg_scalar("SELECT COUNT(*) FROM fact_ratings")
        assert count_first_run == count_after_second, (
            "Second run added rows to fact_ratings despite unchanged files"
        )


# ---------------------------------------------------------------------------
# API — health
# ---------------------------------------------------------------------------

class TestAPIHealth:
    def test_health_endpoint(self, dag_run_id):
        resp = _api_get("/health")
        assert resp.get("status") == "ok"


# ---------------------------------------------------------------------------
# API — /companies
# ---------------------------------------------------------------------------

class TestAPICompanies:
    def test_list_companies_returns_list(self, dag_run_id):
        data = _api_get("/companies")
        assert isinstance(data, list)
        assert len(data) > 0

    def test_company_has_required_fields(self, dag_run_id):
        companies = _api_get("/companies")
        required = {"company_id", "entity_name", "valid_from", "loaded_at_utc"}
        for c in companies:
            assert required.issubset(c.keys()), f"Missing fields in {c}"

    def test_get_single_company(self, dag_run_id):
        companies = _api_get("/companies")
        first_id = companies[0]["company_id"]
        company = _api_get(f"/companies/{first_id}")
        assert company["company_id"] == first_id
        assert company["is_current"] is True

    def test_company_not_found_returns_404(self, dag_run_id):
        resp = requests.get(f"{API_BASE_URL}/companies/999999", timeout=15)
        assert resp.status_code == 404

    def test_company_versions(self, dag_run_id):
        companies = _api_get("/companies")
        first_id = companies[0]["company_id"]
        versions = _api_get(f"/companies/{first_id}/versions")
        assert isinstance(versions, list)
        assert len(versions) >= 1
        for v in versions:
            assert "valid_from" in v
            assert "is_current" in v

    def test_company_history(self, dag_run_id):
        companies = _api_get("/companies")
        first_id = companies[0]["company_id"]
        history = _api_get(f"/companies/{first_id}/history")
        assert isinstance(history, list)
        assert len(history) >= 1
        for snap in history:
            assert "snapshot_id" in snap
            assert "data_hash" in snap

    def test_compare_companies(self, dag_run_id):
        companies = _api_get("/companies")
        ids = ",".join(str(c["company_id"]) for c in companies[:2])
        result = _api_get("/companies/compare", params={"company_ids": ids})
        assert "companies" in result
        assert isinstance(result["companies"], list)
        assert len(result["companies"]) <= 2

    def test_compare_invalid_ids_returns_422(self, dag_run_id):
        resp = requests.get(
            f"{API_BASE_URL}/companies/compare",
            params={"company_ids": "abc,def"},
            timeout=15,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API — /snapshots
# ---------------------------------------------------------------------------

class TestAPISnapshots:
    def test_list_snapshots_returns_list(self, dag_run_id):
        data = _api_get("/snapshots")
        assert isinstance(data, list)
        assert len(data) > 0

    def test_snapshot_has_required_fields(self, dag_run_id):
        snapshots = _api_get("/snapshots")
        required = {"snapshot_id", "upload_id", "entity_name", "data_hash", "loaded_at_utc"}
        for s in snapshots:
            assert required.issubset(s.keys())

    def test_get_snapshot_by_id(self, dag_run_id):
        snapshots = _api_get("/snapshots")
        first_id = snapshots[0]["snapshot_id"]
        snap = _api_get(f"/snapshots/{first_id}")
        assert snap["snapshot_id"] == first_id

    def test_snapshot_not_found_returns_404(self, dag_run_id):
        resp = requests.get(f"{API_BASE_URL}/snapshots/999999", timeout=15)
        assert resp.status_code == 404

    def test_latest_snapshots(self, dag_run_id):
        latest = _api_get("/snapshots/latest")
        assert isinstance(latest, list)
        assert len(latest) > 0

    def test_latest_one_per_company(self, dag_run_id):
        latest = _api_get("/snapshots/latest")
        names = [s["entity_name"] for s in latest]
        assert len(names) == len(set(names)), "Duplicate entity_names in /snapshots/latest"

    def test_filter_by_company_id(self, dag_run_id):
        companies = _api_get("/companies")
        cid = companies[0]["company_id"]
        snaps = _api_get("/snapshots", params={"company_id": cid})
        assert all(s["company_id"] == cid for s in snaps)


# ---------------------------------------------------------------------------
# API — /uploads
# ---------------------------------------------------------------------------

class TestAPIUploads:
    def test_list_uploads_returns_list(self, dag_run_id):
        data = _api_get("/uploads")
        assert isinstance(data, list)
        assert len(data) > 0

    def test_upload_has_required_fields(self, dag_run_id):
        uploads = _api_get("/uploads")
        required = {"upload_id", "source_filename", "data_hash", "loaded_at_utc"}
        for u in uploads:
            assert required.issubset(u.keys())

    def test_upload_details(self, dag_run_id):
        uploads = _api_get("/uploads")
        first_id = uploads[0]["upload_id"]
        detail = _api_get(f"/uploads/{first_id}/details")
        assert detail["upload_id"] == first_id
        assert "snapshots" in detail
        assert isinstance(detail["snapshots"], list)

    def test_upload_not_found_returns_404(self, dag_run_id):
        resp = requests.get(f"{API_BASE_URL}/uploads/999999/details", timeout=15)
        assert resp.status_code == 404

    def test_upload_stats(self, dag_run_id):
        stats = _api_get("/uploads/stats")
        assert stats["total_uploads"] > 0
        assert stats["unique_files"] > 0
        assert stats["unique_companies"] > 0
        assert stats["earliest_upload"] is not None
        assert stats["latest_upload"] is not None
