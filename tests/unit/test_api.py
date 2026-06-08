"""
test_api.py
-----------
Unit tests for all FastAPI endpoints in api/.

get_db() is patched in each router's own namespace so no PostgreSQL connection
is needed. TestClient drives the ASGI app in-process.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app, raise_server_exceptions=False)

_NOW = datetime(2026, 6, 8, 19, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Shared sample rows (keys match the SQL aliases in each router)
# ---------------------------------------------------------------------------

_COMPANY_ROW = {
    "company_id": 1,
    "entity_name": "Company A",
    "sector": "Personal & Household Goods",
    "country": "Federal Republic of Germany",
    "currency": "EUR",
    "accounting_principles": "IFRS",
    "business_year_end_month": 12,
    "valid_from": _NOW,
    "valid_to": None,
    "is_current": True,
    "loaded_at_utc": _NOW,
}

_SNAPSHOT_ROW = {
    "snapshot_id": 1,
    "upload_id": 1,
    "company_id": 1,
    "entity_name": "Company A",
    "sector": "Personal & Household Goods",
    "country": "Federal Republic of Germany",
    "currency": "EUR",
    "business_risk_profile": "B+",
    "financial_risk_profile": "C",
    "blended_industry_risk_profile": "A",
    "competitive_positioning": "B+",
    "market_share": "BB-",
    "diversification": "B+",
    "operating_profitability": "BB-",
    "sector_company_specific_factor_1": "B-",
    "sector_company_specific_factor_2": None,
    "leverage": "CCC",
    "interest_cover": "B-",
    "cash_flow_cover": "CCC",
    "liquidity": "-2 notches",
    "data_hash": "abc123",
    "loaded_at_utc": _NOW,
}

_SCOPE_ROW = {
    "scope_credit_id": 1,
    "company_id": 1,
    "upload_id": 1,
    "entity_name": "Company A",
    "metric_name": "Scope-adjusted debt/EBITDA",
    "year": "2022",
    "metric_value": "3.5",
    "loaded_at_utc": _NOW,
}

_UPLOAD_ROW = {
    "upload_id": 1,
    "source_filename": "corporates_A_1.xlsm",
    "file_modified_at": _NOW,
    "data_hash": "abc123",
    "dag_run_id": "run_001",
    "rows_extracted": 1,
    "loaded_at_utc": _NOW,
}

_STATS_ROW = {
    "total_uploads": 4,
    "unique_files": 4,
    "unique_companies": 4,
    "earliest_upload": _NOW,
    "latest_upload": _NOW,
}


# ---------------------------------------------------------------------------
# Mock DB factory
# ---------------------------------------------------------------------------

def _mock_db(rows=None, one=None):
    """Return a get_db replacement that yields a mock connection.

    conn.cursor() is a context manager that always yields a single cursor mock.
    cur.fetchall() → rows (default [])
    cur.fetchone() → one (default None)
    """
    @contextmanager
    def mock_get_db():
        cur = MagicMock()
        cur.fetchall.return_value = rows if rows is not None else []
        cur.fetchone.return_value = one

        conn = MagicMock()

        @contextmanager
        def _cursor_cm(*args, **kwargs):
            yield cur

        conn.cursor = _cursor_cm
        yield conn

    return mock_get_db


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /companies
# ---------------------------------------------------------------------------

class TestCompanies:
    def test_list_companies(self):
        with patch("api.routers.companies.get_db", _mock_db(rows=[_COMPANY_ROW])):
            resp = client.get("/companies")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["entity_name"] == "Company A"

    def test_list_companies_empty(self):
        with patch("api.routers.companies.get_db", _mock_db(rows=[])):
            resp = client.get("/companies")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_company(self):
        with patch("api.routers.companies.get_db", _mock_db(one=_COMPANY_ROW)):
            resp = client.get("/companies/Company A")
        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_name"] == "Company A"
        assert body["is_current"] is True

    def test_get_company_not_found(self):
        with patch("api.routers.companies.get_db", _mock_db(one=None)):
            resp = client.get("/companies/nonexistent-xyz")
        assert resp.status_code == 404

    def test_get_company_versions(self):
        with patch("api.routers.companies.get_db", _mock_db(rows=[_COMPANY_ROW])):
            resp = client.get("/companies/Company A/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["company_id"] == 1

    def test_get_company_versions_not_found(self):
        with patch("api.routers.companies.get_db", _mock_db(rows=[])):
            resp = client.get("/companies/nonexistent-xyz/versions")
        assert resp.status_code == 404

    def test_get_company_history(self):
        with patch("api.routers.companies.get_db", _mock_db(rows=[_SCOPE_ROW])):
            resp = client.get("/companies/Company A/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["metric_name"] == "Scope-adjusted debt/EBITDA"
        assert data[0]["year"] == "2022"
        assert data[0]["metric_value"] == "3.5"

    def test_get_company_history_not_found(self):
        with patch("api.routers.companies.get_db", _mock_db(rows=[])):
            resp = client.get("/companies/nonexistent-xyz/history")
        assert resp.status_code == 404

    def test_compare_companies(self):
        with patch("api.routers.companies.get_db", _mock_db(rows=[_SNAPSHOT_ROW])):
            resp = client.get(
                "/companies/compare",
                params={"entity_names": "Company A,Company B"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "companies" in body
        assert "as_of_date" in body
        assert len(body["companies"]) == 1

    def test_compare_with_as_of_date(self):
        with patch("api.routers.companies.get_db", _mock_db(rows=[_SNAPSHOT_ROW])):
            resp = client.get(
                "/companies/compare",
                params={
                    "entity_names": "Company A",
                    "as_of_date": "2026-06-08T20:00:00Z",
                },
            )
        assert resp.status_code == 200

    def test_compare_missing_entity_names_returns_422(self):
        resp = client.get("/companies/compare")
        assert resp.status_code == 422

    def test_compare_blank_entity_names_returns_422(self):
        with patch("api.routers.companies.get_db", _mock_db(rows=[])):
            resp = client.get("/companies/compare", params={"entity_names": " , "})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /snapshots
# ---------------------------------------------------------------------------

class TestSnapshots:
    def test_list_snapshots(self):
        with patch("api.routers.snapshots.get_db", _mock_db(rows=[_SNAPSHOT_ROW])):
            resp = client.get("/snapshots")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["snapshot_id"] == 1

    def test_list_snapshots_empty(self):
        with patch("api.routers.snapshots.get_db", _mock_db(rows=[])):
            resp = client.get("/snapshots")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_snapshots_currency_filter(self):
        with patch("api.routers.snapshots.get_db", _mock_db(rows=[_SNAPSHOT_ROW])):
            resp = client.get("/snapshots", params={"currency": "EUR"})
        assert resp.status_code == 200

    def test_list_snapshots_sector_filter(self):
        with patch("api.routers.snapshots.get_db", _mock_db(rows=[_SNAPSHOT_ROW])):
            resp = client.get("/snapshots", params={"sector": "Household"})
        assert resp.status_code == 200

    def test_list_snapshots_country_filter(self):
        with patch("api.routers.snapshots.get_db", _mock_db(rows=[])):
            resp = client.get("/snapshots", params={"country": "Germany"})
        assert resp.status_code == 200

    def test_list_snapshots_company_id_filter(self):
        with patch("api.routers.snapshots.get_db", _mock_db(rows=[_SNAPSHOT_ROW])):
            resp = client.get("/snapshots", params={"company_id": 1})
        assert resp.status_code == 200

    def test_list_snapshots_date_range(self):
        with patch("api.routers.snapshots.get_db", _mock_db(rows=[_SNAPSHOT_ROW])):
            resp = client.get(
                "/snapshots",
                params={
                    "from_date": "2026-01-01T00:00:00Z",
                    "to_date": "2026-12-31T23:59:59Z",
                },
            )
        assert resp.status_code == 200

    def test_get_latest_snapshots(self):
        with patch("api.routers.snapshots.get_db", _mock_db(rows=[_SNAPSHOT_ROW])):
            resp = client.get("/snapshots/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["entity_name"] == "Company A"

    def test_get_snapshot_by_id(self):
        with patch("api.routers.snapshots.get_db", _mock_db(one=_SNAPSHOT_ROW)):
            resp = client.get("/snapshots/1")
        assert resp.status_code == 200
        assert resp.json()["snapshot_id"] == 1

    def test_get_snapshot_not_found(self):
        with patch("api.routers.snapshots.get_db", _mock_db(one=None)):
            resp = client.get("/snapshots/999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /uploads
# ---------------------------------------------------------------------------

class TestUploads:
    def test_list_uploads(self):
        with patch("api.routers.uploads.get_db", _mock_db(rows=[_UPLOAD_ROW])):
            resp = client.get("/uploads")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["source_filename"] == "corporates_A_1.xlsm"

    def test_list_uploads_empty(self):
        with patch("api.routers.uploads.get_db", _mock_db(rows=[])):
            resp = client.get("/uploads")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_upload_stats(self):
        with patch("api.routers.uploads.get_db", _mock_db(one=_STATS_ROW)):
            resp = client.get("/uploads/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_uploads"] == 4
        assert body["unique_files"] == 4

    def test_upload_details(self):
        # upload_details calls fetchone first (for the upload row) then fetchall (for snapshots).
        # Both calls go through the same cursor mock, so set both return values.
        with patch("api.routers.uploads.get_db", _mock_db(rows=[_SNAPSHOT_ROW], one=_UPLOAD_ROW)):
            resp = client.get("/uploads/1/details")
        assert resp.status_code == 200
        body = resp.json()
        assert body["upload_id"] == 1
        assert "snapshots" in body
        assert len(body["snapshots"]) == 1

    def test_upload_details_not_found(self):
        with patch("api.routers.uploads.get_db", _mock_db(one=None)):
            resp = client.get("/uploads/999/details")
        assert resp.status_code == 404

    def test_upload_file_not_found_in_db(self):
        with patch("api.routers.uploads.get_db", _mock_db(one=None)):
            resp = client.get("/uploads/999/file")
        assert resp.status_code == 404

    def test_upload_file_not_on_disk(self, tmp_path: Path):
        with (
            patch(
                "api.routers.uploads.get_db",
                _mock_db(one={"source_filename": "missing.xlsm"}),
            ),
            patch("api.routers.uploads._INPUT_FILES_DIR", tmp_path),
        ):
            resp = client.get("/uploads/1/file")
        assert resp.status_code == 404

    def test_upload_file_download(self, tmp_path: Path):
        fake = tmp_path / "corporates_A_1.xlsm"
        fake.write_bytes(b"fake xlsx content")
        with (
            patch(
                "api.routers.uploads.get_db",
                _mock_db(one={"source_filename": "corporates_A_1.xlsm"}),
            ),
            patch("api.routers.uploads._INPUT_FILES_DIR", tmp_path),
        ):
            resp = client.get("/uploads/1/file")
        assert resp.status_code == 200
        assert resp.content == b"fake xlsx content"
