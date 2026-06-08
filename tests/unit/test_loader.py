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
            patch("corporate_pipeline.loader._upsert_sector", return_value=1),
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
