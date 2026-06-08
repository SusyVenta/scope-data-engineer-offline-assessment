"""
transformer.py
--------------
Transforms a RawMasterRecord into a RatingRecord ready for database loading.

Key responsibilities:
  - Strip all string fields (defensive, extractor already strips)
  - Normalize currency to uppercase
  - Convert business_year_end month name to integer (1-12)
  - Compute a deterministic SHA-256 data_hash of all data fields
  - Populate effective_date from file modification time or extraction time

Public API:
  transform_record(raw, file_modified_at) -> RatingRecord
  transform_all(records, file_mtimes)     -> list[RatingRecord]
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from corporate_pipeline.extractor import RawMasterRecord
from corporate_pipeline.validator import MONTH_NAMES


# ---------------------------------------------------------------------------
# Output container
# ---------------------------------------------------------------------------

@dataclass
class RatingRecord:
    """Fully normalized, hash-keyed record ready for database insertion."""
    source_filename: str
    file_modified_at: datetime

    # Core metadata
    rated_entity: str | None
    sector: str | None
    country: str | None
    currency: str | None
    accounting_principles: str | None
    business_year_end_month: int | None

    # Methodologies
    methodology_1: str | None
    methodology_2: str | None

    # Industry risk
    industry_risk_1: str | None
    industry_risk_2: str | None
    industry_risk_score_1: str | None
    industry_risk_score_2: str | None
    industry_weight_1: float | None
    industry_weight_2: float | None
    segmentation_criteria: str | None

    # Risk sub-scores
    business_risk_profile: str | None
    blended_industry_risk_profile: str | None
    competitive_positioning: str | None
    market_share: str | None
    diversification: str | None
    operating_profitability: str | None
    sector_specific_factor_1: str | None
    sector_specific_factor_2: str | None
    financial_risk_profile: str | None
    leverage: str | None
    interest_cover: str | None
    cash_flow_cover: str | None
    liquidity_adjustment: str | None

    # Time-series
    scope_credit_metrics: dict[str, dict[str, Any]]

    # Computed
    data_hash: str
    effective_date: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    return s if s else None


def _parse_month(value: str | None) -> int | None:
    """Convert month name or integer string to 1-12 int. Returns None if unparseable."""
    if value is None:
        return None
    v = value.strip()
    by_name = MONTH_NAMES.get(v.lower())
    if by_name is not None:
        return by_name
    if v.isdigit():
        m = int(v)
        return m if 1 <= m <= 12 else None
    return None


def _compute_hash(data: dict) -> str:
    """SHA-256 of a canonically serialized dict (sorted keys, no whitespace)."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _data_fields(raw: RawMasterRecord) -> dict:
    """Collect all business-logic fields into a dict for hashing.

    Excludes source_filename and file_modified_at — those are metadata about
    the file, not the content. Two files with identical content but different
    names or timestamps must produce the same hash.
    """
    return {
        "rated_entity": _strip(raw.rated_entity),
        "sector": _strip(raw.sector),
        "methodology_1": _strip(raw.methodology_1),
        "methodology_2": _strip(raw.methodology_2),
        "industry_risk_1": _strip(raw.industry_risk_1),
        "industry_risk_2": _strip(raw.industry_risk_2),
        "industry_risk_score_1": _strip(raw.industry_risk_score_1),
        "industry_risk_score_2": _strip(raw.industry_risk_score_2),
        "industry_weight_1": raw.industry_weight_1,
        "industry_weight_2": raw.industry_weight_2,
        "segmentation_criteria": _strip(raw.segmentation_criteria),
        "currency": _strip(raw.currency).upper() if raw.currency else None,
        "country": _strip(raw.country),
        "accounting_principles": _strip(raw.accounting_principles),
        "business_year_end": _strip(raw.business_year_end),
        "business_risk_profile": _strip(raw.business_risk_profile),
        "blended_industry_risk_profile": _strip(raw.blended_industry_risk_profile),
        "competitive_positioning": _strip(raw.competitive_positioning),
        "market_share": _strip(raw.market_share),
        "diversification": _strip(raw.diversification),
        "operating_profitability": _strip(raw.operating_profitability),
        "sector_specific_factor_1": _strip(raw.sector_specific_factor_1),
        "sector_specific_factor_2": _strip(raw.sector_specific_factor_2),
        "financial_risk_profile": _strip(raw.financial_risk_profile),
        "leverage": _strip(raw.leverage),
        "interest_cover": _strip(raw.interest_cover),
        "cash_flow_cover": _strip(raw.cash_flow_cover),
        "liquidity_adjustment": _strip(raw.liquidity_adjustment),
        "scope_credit_metrics": raw.scope_credit_metrics,
    }


# ---------------------------------------------------------------------------
# Main transform function
# ---------------------------------------------------------------------------

def transform_record(
    raw: RawMasterRecord,
    file_modified_at: datetime,
) -> RatingRecord:
    """Normalize a RawMasterRecord into a RatingRecord.

    file_modified_at is used as effective_date and stored in upload_log.
    """
    data = _data_fields(raw)
    data_hash = _compute_hash(data)

    return RatingRecord(
        source_filename=raw.source_filename,
        file_modified_at=file_modified_at,
        rated_entity=data["rated_entity"],
        sector=data["sector"],
        country=data["country"],
        currency=data["currency"],
        accounting_principles=data["accounting_principles"],
        business_year_end_month=_parse_month(raw.business_year_end),
        methodology_1=data["methodology_1"],
        methodology_2=data["methodology_2"],
        industry_risk_1=data["industry_risk_1"],
        industry_risk_2=data["industry_risk_2"],
        industry_risk_score_1=data["industry_risk_score_1"],
        industry_risk_score_2=data["industry_risk_score_2"],
        industry_weight_1=raw.industry_weight_1,
        industry_weight_2=raw.industry_weight_2,
        segmentation_criteria=data["segmentation_criteria"],
        business_risk_profile=data["business_risk_profile"],
        blended_industry_risk_profile=data["blended_industry_risk_profile"],
        competitive_positioning=data["competitive_positioning"],
        market_share=data["market_share"],
        diversification=data["diversification"],
        operating_profitability=data["operating_profitability"],
        sector_specific_factor_1=data["sector_specific_factor_1"],
        sector_specific_factor_2=data["sector_specific_factor_2"],
        financial_risk_profile=data["financial_risk_profile"],
        leverage=data["leverage"],
        interest_cover=data["interest_cover"],
        cash_flow_cover=data["cash_flow_cover"],
        liquidity_adjustment=data["liquidity_adjustment"],
        scope_credit_metrics=raw.scope_credit_metrics,
        data_hash=data_hash,
        effective_date=file_modified_at,
    )


def transform_all(
    records: list[RawMasterRecord],
    file_mtimes: dict[str, datetime],
) -> list[RatingRecord]:
    """Transform a list of RawMasterRecords.

    file_mtimes: mapping of source_filename → file modification datetime.
    Falls back to now(UTC) for any filename not in the map.
    """
    fallback = datetime.now(timezone.utc)
    return [
        transform_record(r, file_mtimes.get(r.source_filename, fallback))
        for r in records
    ]
