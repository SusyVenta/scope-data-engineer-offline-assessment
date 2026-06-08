"""
test_loader.py
--------------
Unit tests for corporate_pipeline/loader.py.

Tests that require DB logic use a lightweight fake connection backed by
sqlite3 (in-memory). The schema is translated to SQLite syntax for the
purpose of these unit tests. All public loader functions are covered.

Tests that require real PostgreSQL (full JSONB, ON CONFLICT with RETURNING,
SCD2 end-to-end) live in tests/integration/.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from corporate_pipeline.loader import (
    begin_pipeline_run,
    complete_pipeline_run,
    get_last_successful_run_time,
    hash_already_loaded,
    stage_modified_files,
)
from corporate_pipeline.transformer import RatingRecord


# ---------------------------------------------------------------------------
# SQLite fake connection
# ---------------------------------------------------------------------------
# We use a minimal subset of the schema translated to SQLite so we can test
# loader logic without a running PostgreSQL instance.

_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_run_state (
    run_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    dag_run_id       TEXT    NOT NULL UNIQUE,
    started_at_utc   TEXT    NOT NULL,
    completed_at_utc TEXT,
    status           TEXT    NOT NULL DEFAULT 'running',
    files_staged     INTEGER NOT NULL DEFAULT 0,
    files_loaded     INTEGER NOT NULL DEFAULT 0,
    files_skipped    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS upload_log (
    upload_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source_filename  TEXT    NOT NULL,
    file_modified_at TEXT    NOT NULL,
    data_hash        TEXT    NOT NULL,
    dag_run_id       TEXT,
    rows_extracted   INTEGER DEFAULT 0,
    loaded_at_utc    TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


class _SQLiteCursor:
    """Wraps sqlite3.Cursor to look like a psycopg2 cursor (context manager)."""

    def __init__(self, sqlite_conn: sqlite3.Connection) -> None:
        self._conn = sqlite_conn
        self._cur = sqlite_conn.cursor()
        self._description = None
        self._rows = []

    @property
    def description(self):
        return self._cur.description

    def execute(self, sql: str, params=()) -> None:
        # psycopg2 uses %s; sqlite3 uses ?
        sql_sqlite = sql.replace("%s", "?")
        self._cur.execute(sql_sqlite, params)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class _FakeConn:
    """Minimal psycopg2-like connection backed by sqlite3 in-memory."""

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.executescript(_SQLITE_DDL)
        self._conn.commit()

    def cursor(self) -> _SQLiteCursor:
        return _SQLiteCursor(self._conn)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


@pytest.fixture
def db() -> _FakeConn:
    conn = _FakeConn()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# stage_modified_files
# ---------------------------------------------------------------------------

class TestStageModifiedFiles:
    def test_returns_all_files_when_no_last_run(self, tmp_path: Path) -> None:
        for name in ["a.xlsm", "b.xlsm", "c.xlsm"]:
            (tmp_path / name).touch()
        result = stage_modified_files(tmp_path, last_run_at=None)
        assert len(result) == 3

    def test_returns_only_newer_files(self, tmp_path: Path) -> None:
        old = tmp_path / "old.xlsm"
        new = tmp_path / "new.xlsm"
        old.touch()
        new.touch()

        # Set old file's mtime to the past
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        last_run = datetime.now(timezone.utc) - timedelta(hours=1)
        os.utime(old, (old_time.timestamp(), old_time.timestamp()))

        result = stage_modified_files(tmp_path, last_run_at=last_run)
        names = [f.name for f in result]
        assert "new.xlsm" in names
        assert "old.xlsm" not in names

    def test_returns_empty_when_no_files_modified(self, tmp_path: Path) -> None:
        f = tmp_path / "old.xlsm"
        f.touch()
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        import os
        os.utime(f, (past.timestamp(), past.timestamp()))
        last_run = datetime.now(timezone.utc) - timedelta(hours=1)
        result = stage_modified_files(tmp_path, last_run_at=last_run)
        assert len(result) == 0

    def test_ignores_non_xlsm_files(self, tmp_path: Path) -> None:
        (tmp_path / "data.csv").touch()
        (tmp_path / "report.xlsx").touch()
        (tmp_path / "file.xlsm").touch()
        result = stage_modified_files(tmp_path, last_run_at=None)
        assert all(f.suffix == ".xlsm" for f in result)
        assert len(result) == 1

    def test_returns_sorted_paths(self, tmp_path: Path) -> None:
        for name in ["c.xlsm", "a.xlsm", "b.xlsm"]:
            (tmp_path / name).touch()
        result = stage_modified_files(tmp_path, last_run_at=None)
        names = [f.name for f in result]
        assert names == sorted(names)

    def test_empty_directory_returns_empty_list(self, tmp_path: Path) -> None:
        assert stage_modified_files(tmp_path, last_run_at=None) == []


# ---------------------------------------------------------------------------
# hash_already_loaded
# ---------------------------------------------------------------------------

class TestHashAlreadyLoaded:
    def test_returns_false_when_no_records(self, db: _FakeConn) -> None:
        assert hash_already_loaded(db, "abc123") is False

    def test_returns_true_after_insert(self, db: _FakeConn) -> None:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO upload_log (source_filename, file_modified_at, data_hash) "
                "VALUES (?, ?, ?)",
                ("file.xlsm", "2026-01-01", "deadbeef"),
            )
        db.commit()
        assert hash_already_loaded(db, "deadbeef") is True

    def test_different_hash_returns_false(self, db: _FakeConn) -> None:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO upload_log (source_filename, file_modified_at, data_hash) "
                "VALUES (?, ?, ?)",
                ("file.xlsm", "2026-01-01", "deadbeef"),
            )
        db.commit()
        assert hash_already_loaded(db, "cafebabe") is False


# ---------------------------------------------------------------------------
# Pipeline run state
# ---------------------------------------------------------------------------

class TestPipelineRunState:
    def test_begin_run_inserts_row(self, db: _FakeConn) -> None:
        run_id = begin_pipeline_run(db, "run_001")
        db.commit()
        with db.cursor() as cur:
            cur.execute("SELECT status FROM pipeline_run_state WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "running"

    def test_begin_run_returns_int(self, db: _FakeConn) -> None:
        run_id = begin_pipeline_run(db, "run_002")
        db.commit()
        assert isinstance(run_id, int)

    def test_complete_run_updates_status(self, db: _FakeConn) -> None:
        run_id = begin_pipeline_run(db, "run_003")
        db.commit()
        complete_pipeline_run(db, run_id, "success", 4, 4, 0)
        db.commit()
        with db.cursor() as cur:
            cur.execute("SELECT status, files_loaded FROM pipeline_run_state WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        assert row[0] == "success"
        assert row[1] == 4

    def test_get_last_successful_run_time_returns_none_when_empty(
        self, db: _FakeConn
    ) -> None:
        assert get_last_successful_run_time(db) is None

    def test_get_last_successful_run_time_returns_latest(
        self, db: _FakeConn
    ) -> None:
        run1 = begin_pipeline_run(db, "run_004")
        db.commit()
        complete_pipeline_run(db, run1, "success")
        db.commit()

        # Insert a completed_at manually since SQLite won't use DEFAULT now()
        with db.cursor() as cur:
            cur.execute(
                "UPDATE pipeline_run_state SET completed_at_utc = ? WHERE run_id = ?",
                ("2026-01-15T10:00:00+00:00", run1),
            )
        db.commit()

        result = get_last_successful_run_time(db)
        assert result is not None

    def test_failed_run_not_returned_as_last_successful(
        self, db: _FakeConn
    ) -> None:
        run1 = begin_pipeline_run(db, "run_005")
        db.commit()
        complete_pipeline_run(db, run1, "failed")
        db.commit()
        assert get_last_successful_run_time(db) is None


# ---------------------------------------------------------------------------
# load_record — duplicate detection (mocked connection)
# ---------------------------------------------------------------------------

class TestLoadRecordDuplicateDetection:
    def _make_record(self, data_hash: str = "abc123") -> RatingRecord:
        return RatingRecord(
            source_filename="test.xlsm",
            file_modified_at=datetime.now(timezone.utc),
            rated_entity="Test Corp",
            sector="Industrials",
            country="Germany",
            currency="EUR",
            accounting_principles="IFRS",
            business_year_end_month=12,
            methodology_1="General Corporate",
            methodology_2=None,
            industry_risk_1="Industrial Goods",
            industry_risk_2=None,
            industry_risk_score_1="BBB",
            industry_risk_score_2=None,
            industry_weight_1=1.0,
            industry_weight_2=None,
            segmentation_criteria="EBITDA",
            business_risk_profile="BB+",
            blended_industry_risk_profile="BBB",
            competitive_positioning="BB+",
            market_share="BB",
            diversification="BB+",
            operating_profitability="B+",
            sector_specific_factor_1="B",
            sector_specific_factor_2=None,
            financial_risk_profile="B",
            leverage="B-",
            interest_cover="B",
            cash_flow_cover="CCC",
            liquidity_adjustment="-2 notches",
            scope_credit_metrics={},
            data_hash=data_hash,
            effective_date=datetime.now(timezone.utc),
        )

    def test_skips_when_hash_already_loaded(self) -> None:
        from corporate_pipeline.loader import load_record
        conn = MagicMock()
        # Simulate hash_already_loaded returning True
        with patch("corporate_pipeline.loader.hash_already_loaded", return_value=True):
            result = load_record(conn, self._make_record("dup_hash"))
        assert result == "skipped_duplicate"

    def test_loads_when_hash_not_loaded(self) -> None:
        from corporate_pipeline.loader import load_record
        conn = MagicMock()
        # Mock all the sub-calls so we don't need a real DB
        with (
            patch("corporate_pipeline.loader.hash_already_loaded", return_value=False),
            patch("corporate_pipeline.loader._insert_upload_log", return_value=42),
            patch("corporate_pipeline.loader._scd2_upsert_company", return_value=7),
            patch("corporate_pipeline.loader._insert_company_industry_risks"),
            patch("corporate_pipeline.loader._insert_company_methodologies"),
            patch("corporate_pipeline.loader._insert_fact_ratings"),
            patch("corporate_pipeline.loader._insert_fact_scope_credit"),
        ):
            result = load_record(conn, self._make_record("new_hash"))
        assert result == "loaded"


import os


# ---------------------------------------------------------------------------
# Private loader functions — MagicMock-based unit tests
# ---------------------------------------------------------------------------

def _make_record(data_hash: str = "abc123", scope_metrics=None) -> "RatingRecord":
    return RatingRecord(
        source_filename="test.xlsm",
        file_modified_at=datetime.now(timezone.utc),
        rated_entity="Test Corp",
        sector="Industrials",
        country="Germany",
        currency="EUR",
        accounting_principles="IFRS",
        business_year_end_month=12,
        methodology_1="General Corporate",
        methodology_2=None,
        industry_risk_1="Industrial Goods",
        industry_risk_2=None,
        industry_risk_score_1="BBB",
        industry_risk_score_2=None,
        industry_weight_1=1.0,
        industry_weight_2=None,
        segmentation_criteria="EBITDA",
        business_risk_profile="BB+",
        blended_industry_risk_profile="BBB",
        competitive_positioning="BB+",
        market_share="BB",
        diversification="BB+",
        operating_profitability="B+",
        sector_specific_factor_1="B",
        sector_specific_factor_2=None,
        financial_risk_profile="B",
        leverage="B-",
        interest_cover="B",
        cash_flow_cover="CCC",
        liquidity_adjustment="-2 notches",
        scope_credit_metrics=scope_metrics or {},
        data_hash=data_hash,
        effective_date=datetime.now(timezone.utc),
    )


def _make_conn_with_cursor(fetchone_values=None, fetchall_values=None):
    """Return (conn, cur) where conn.cursor() yields cur as a context manager."""
    from contextlib import contextmanager

    cur = MagicMock()
    if fetchone_values is not None:
        cur.fetchone.side_effect = fetchone_values
    if fetchall_values is not None:
        cur.fetchall.side_effect = fetchall_values

    conn = MagicMock()

    @contextmanager
    def _cursor_cm(*args, **kwargs):
        yield cur

    conn.cursor = _cursor_cm
    return conn, cur


class TestInsertUploadLog:
    def test_returns_upload_id(self):
        from corporate_pipeline.loader import _insert_upload_log

        conn, cur = _make_conn_with_cursor(fetchone_values=[(42,)])
        result = _insert_upload_log(conn, _make_record(), "dag_run_1")
        assert result == 42

    def test_executes_insert(self):
        from corporate_pipeline.loader import _insert_upload_log

        conn, cur = _make_conn_with_cursor(fetchone_values=[(7,)])
        _insert_upload_log(conn, _make_record(), "dag_run_xyz")
        cur.execute.assert_called_once()
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO upload_log" in sql
        assert "dag_run_xyz" in params


class TestInsertCompanyIndustryRisks:
    def test_inserts_one_risk(self):
        from corporate_pipeline.loader import _insert_company_industry_risks

        conn, cur = _make_conn_with_cursor()
        _insert_company_industry_risks(conn, company_id=1, record=_make_record())
        # record has industry_risk_1="Industrial Goods", industry_risk_2=None → 1 execute
        assert cur.execute.call_count == 1

    def test_skips_null_risks(self):
        from dataclasses import replace as dc_replace
        from corporate_pipeline.loader import _insert_company_industry_risks

        record = dc_replace(_make_record(), industry_risk_1=None, industry_risk_2=None)
        conn, cur = _make_conn_with_cursor()
        _insert_company_industry_risks(conn, company_id=1, record=record)
        assert cur.execute.call_count == 0


class TestInsertCompanyMethodologies:
    def test_inserts_one_methodology(self):
        from corporate_pipeline.loader import _insert_company_methodologies

        conn, cur = _make_conn_with_cursor()
        _insert_company_methodologies(conn, company_id=1, record=_make_record())
        # methodology_1="General Corporate", methodology_2=None → 1 execute
        assert cur.execute.call_count == 1

    def test_skips_null_methodologies(self):
        from dataclasses import replace as dc_replace
        from corporate_pipeline.loader import _insert_company_methodologies

        record = dc_replace(_make_record(), methodology_1=None, methodology_2=None)
        conn, cur = _make_conn_with_cursor()
        _insert_company_methodologies(conn, company_id=1, record=record)
        assert cur.execute.call_count == 0


class TestInsertFactRatings:
    def test_executes_insert(self):
        from corporate_pipeline.loader import _insert_fact_ratings

        conn, cur = _make_conn_with_cursor()
        now = datetime.now(timezone.utc)
        _insert_fact_ratings(conn, _make_record(), upload_id=1, company_id=1, now=now)
        cur.execute.assert_called_once()
        sql, _ = cur.execute.call_args[0]
        assert "INSERT INTO fact_ratings" in sql


class TestInsertFactScopeCredit:
    def test_inserts_one_row_per_metric_year(self):
        from corporate_pipeline.loader import _insert_fact_scope_credit

        metrics = {"Revenue": {"2022": "100", "2023": "110"}}
        conn, cur = _make_conn_with_cursor()
        now = datetime.now(timezone.utc)
        _insert_fact_scope_credit(
            conn, _make_record(scope_metrics=metrics), upload_id=1, company_id=1, now=now
        )
        assert cur.execute.call_count == 2  # 1 metric × 2 years

    def test_noop_for_empty_metrics(self):
        from corporate_pipeline.loader import _insert_fact_scope_credit

        conn, cur = _make_conn_with_cursor()
        now = datetime.now(timezone.utc)
        _insert_fact_scope_credit(
            conn, _make_record(scope_metrics={}), upload_id=1, company_id=1, now=now
        )
        assert cur.execute.call_count == 0


class TestScd2UpsertCompany:
    def _existing_tuple(self, record):
        return (
            99,
            record.sector,
            record.country,
            record.currency,
            record.accounting_principles,
            record.business_year_end_month,
            record.segmentation_criteria,
        )

    def test_new_company_inserts_and_returns_id(self):
        from corporate_pipeline.loader import _scd2_upsert_company

        # First fetchone → None (no existing company), second → (42,) (new insert)
        conn, cur = _make_conn_with_cursor(fetchone_values=[None, (42,)])
        result = _scd2_upsert_company(conn, _make_record(), upload_id=1, now=datetime.now(timezone.utc))
        assert result == 42

    def test_unchanged_company_returns_existing_id(self):
        from corporate_pipeline.loader import _scd2_upsert_company

        record = _make_record()
        conn, cur = _make_conn_with_cursor(
            fetchone_values=[self._existing_tuple(record)],
            fetchall_values=[
                [("Industrial Goods", 1.0)],  # _fetch_existing_risks
                [("General Corporate",)],       # _fetch_existing_methodologies
            ],
        )
        result = _scd2_upsert_company(conn, record, upload_id=1, now=datetime.now(timezone.utc))
        assert result == 99

    def test_changed_company_creates_new_version(self):
        from corporate_pipeline.loader import _scd2_upsert_company

        record = _make_record()
        changed_tuple = (
            99, "Different Sector", record.country, record.currency,
            record.accounting_principles, record.business_year_end_month,
            record.segmentation_criteria,
        )
        conn, cur = _make_conn_with_cursor(
            fetchone_values=[changed_tuple, (100,)],
            fetchall_values=[
                [("Industrial Goods", 1.0)],
                [("General Corporate",)],
            ],
        )
        result = _scd2_upsert_company(conn, record, upload_id=2, now=datetime.now(timezone.utc))
        assert result == 100
