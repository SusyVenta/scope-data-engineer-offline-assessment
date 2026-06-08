"""
models.py
---------
Pydantic response models for the corporate ratings API.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SectorOut(BaseModel):
    sector_id: int
    sector_name: str


class CompanyVersionOut(BaseModel):
    company_id: int
    entity_name: str
    sector: str | None
    country: str | None
    currency: str | None
    accounting_principles: str | None
    business_year_end_month: int | None
    valid_from: datetime
    valid_to: datetime | None
    is_current: bool
    loaded_at_utc: datetime


class CompanyOut(BaseModel):
    company_id: int
    entity_name: str
    sector: str | None
    country: str | None
    currency: str | None
    accounting_principles: str | None
    business_year_end_month: int | None
    valid_from: datetime
    loaded_at_utc: datetime


class SnapshotOut(BaseModel):
    snapshot_id: int
    upload_id: int
    company_id: int | None
    entity_name: str | None
    sector: str | None
    country: str | None
    currency: str | None
    business_risk_profile: str | None
    financial_risk_profile: str | None
    blended_industry_risk_profile: str | None
    competitive_positioning: str | None
    market_share: str | None
    diversification: str | None
    operating_profitability: str | None
    sector_company_specific_factor_1: str | None
    sector_company_specific_factor_2: str | None
    leverage: str | None
    interest_cover: str | None
    cash_flow_cover: str | None
    liquidity: str | None
    data_hash: str
    loaded_at_utc: datetime


class UploadOut(BaseModel):
    upload_id: int
    source_filename: str
    file_modified_at: datetime
    data_hash: str
    dag_run_id: str | None
    rows_extracted: int | None
    loaded_at_utc: datetime


class UploadDetailOut(UploadOut):
    snapshots: list[SnapshotOut] = []


class UploadStatsOut(BaseModel):
    total_uploads: int
    unique_files: int
    unique_companies: int
    earliest_upload: datetime | None
    latest_upload: datetime | None


class CompareOut(BaseModel):
    as_of_date: datetime | None
    companies: list[SnapshotOut]
