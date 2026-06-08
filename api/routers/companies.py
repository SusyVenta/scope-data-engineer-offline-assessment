"""
companies.py
------------
/companies endpoints.

All entity-level routes use the human-readable entity_name as the path
parameter rather than the internal surrogate company_id. This makes URLs
stable across SCD-2 version changes (a new version creates a new company_id
but the entity_name remains the same).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import psycopg2.extras
from fastapi import APIRouter, HTTPException, Path, Query

from api.db import get_db
from api.models import CompanyOut, CompanyVersionOut, CompareOut, ScopeCreditMetricOut, SnapshotOut

router = APIRouter(prefix="/companies", tags=["companies"])

_COMPANY_COLS = """
    dc.company_id, dc.entity_name,
    dc.sector_name  AS sector,
    dc.country,
    dc.reporting_currency AS currency,
    dc.accounting_principles,
    dc.business_year_end_month
"""

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

_SNAPSHOT_JOIN = """
    FROM fact_ratings fr
    LEFT JOIN dim_company dc ON dc.company_id = fr.company_id
"""


@router.get(
    "",
    response_model=list[CompanyOut],
    summary="List all companies",
    description=(
        "Returns the **current** (latest) dimension record for every company. "
        "Use the `entity_name` field from these results as the path parameter "
        "in the other `/companies/{entity_name}` endpoints.\n\n"
        "**Example call:** `GET /companies`\n\n"
        "**Sample entity names in the DB:** `Company A`, `Company B`"
    ),
)
def list_companies():
    sql = f"""
        SELECT {_COMPANY_COLS},
               dc.valid_from, dc.loaded_at_utc
        FROM dim_company dc
        WHERE dc.is_current = TRUE
        ORDER BY dc.entity_name
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()


@router.get(
    "/compare",
    response_model=CompareOut,
    summary="Compare companies at a point in time",
    description=(
        "Returns the most recent rating snapshot for each requested entity, "
        "optionally filtered to a specific point in time.\n\n"
        "**`entity_names`** — comma-separated list of entity names "
        "(e.g. `Company A,Company B`).\n\n"
        "**`as_of_date`** — ISO 8601 datetime; only snapshots loaded on or before "
        "this date are considered. Omit to get the absolute latest snapshot. "
        "Format: `YYYY-MM-DDTHH:MM:SSZ` — example: `2026-06-08T20:00:00Z`.\n\n"
        "**Example call:** `GET /companies/compare?entity_names=Company A,Company B`"
    ),
)
def compare_companies(
    entity_names: str = Query(
        ...,
        description="Comma-separated entity names to compare.",
        examples=["Company A,Company B"],
    ),
    as_of_date: Optional[datetime] = Query(
        None,
        description=(
            "Point-in-time filter in ISO 8601 format. "
            "Only snapshots loaded on or before this date are returned. "
            "Example: `2026-06-08T20:00:00Z`"
        ),
        examples=["2026-06-08T20:00:00Z"],
    ),
):
    names = [n.strip() for n in entity_names.split(",") if n.strip()]
    if not names:
        raise HTTPException(status_code=422, detail="entity_names must not be empty")

    placeholders = ",".join(["%s"] * len(names))
    if as_of_date:
        sql = f"""
            SELECT DISTINCT ON (dc.entity_name) {_SNAPSHOT_COLS}
            {_SNAPSHOT_JOIN}
            WHERE dc.entity_name IN ({placeholders})
              AND fr.loaded_at_utc <= %s
            ORDER BY dc.entity_name, fr.loaded_at_utc DESC
        """
        params = names + [as_of_date]
    else:
        sql = f"""
            SELECT DISTINCT ON (dc.entity_name) {_SNAPSHOT_COLS}
            {_SNAPSHOT_JOIN}
            WHERE dc.entity_name IN ({placeholders})
            ORDER BY dc.entity_name, fr.loaded_at_utc DESC
        """
        params = names

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    return CompareOut(as_of_date=as_of_date, companies=rows)


@router.get(
    "/{entity_name}",
    response_model=CompanyVersionOut,
    summary="Get current company record",
    description=(
        "Returns the current (latest SCD-2 version) dimension record for the given entity.\n\n"
        "**`entity_name`** — exact entity name as stored in `dim_company` "
        "(retrieve from `GET /companies`). Example: `Company A`.\n\n"
        "**Example call:** `GET /companies/Company A`"
    ),
)
def get_company(
    entity_name: str = Path(
        ...,
        description="Exact entity name (e.g. 'Company A'). Retrieve valid names from GET /companies.",
        examples=["Company A"],
    ),
):
    sql = f"""
        SELECT {_COMPANY_COLS},
               dc.valid_from, dc.valid_to, dc.is_current, dc.loaded_at_utc
        FROM dim_company dc
        WHERE dc.entity_name = %s AND dc.is_current = TRUE
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (entity_name,))
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Company '{entity_name}' not found")
    return row


@router.get(
    "/{entity_name}/versions",
    response_model=list[CompanyVersionOut],
    summary="Get all SCD-2 versions for a company",
    description=(
        "Returns every historical dimension record for the entity, ordered oldest → newest. "
        "A new version is created whenever company metadata changes (sector, country, "
        "currency, industry risk assignments, or applied methodologies).\n\n"
        "**`entity_name`** — exact entity name. Example: `Company A`.\n\n"
        "**Example call:** `GET /companies/Company A/versions`"
    ),
)
def get_company_versions(
    entity_name: str = Path(
        ...,
        description="Exact entity name (e.g. 'Company A'). Retrieve valid names from GET /companies.",
        examples=["Company A"],
    ),
):
    sql = f"""
        SELECT {_COMPANY_COLS},
               dc.valid_from, dc.valid_to, dc.is_current, dc.loaded_at_utc
        FROM dim_company dc
        WHERE dc.entity_name = %s
        ORDER BY dc.valid_from
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (entity_name,))
            rows = cur.fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Company '{entity_name}' not found")
    return rows


@router.get(
    "/{entity_name}/history",
    response_model=list[ScopeCreditMetricOut],
    summary="Get Scope Credit Metrics time-series for a company",
    description=(
        "Returns all rows from `fact_scope_credit_hist` for the entity — one row per "
        "(metric, year, upload). Ordered by metric name then year, giving a full "
        "time-series view of how financial metrics evolve across submissions.\n\n"
        "Available metrics: `Scope-adjusted debt/EBITDA`, `Scope-adjusted EBITDA interest cover`, "
        "`Scope-adjusted FFO/debt`, `Scope-adjusted FOCF/debt`, `Scope-adjusted loan/value`, "
        "`Liquidity (time-series)`.\n\n"
        "Year values include actuals (e.g. `2022`) and estimates (e.g. `2025E`).\n\n"
        "**`entity_name`** — exact entity name. Example: `Company A`.\n\n"
        "**Example call:** `GET /companies/Company A/history`"
    ),
)
def get_company_history(
    entity_name: str = Path(
        ...,
        description="Exact entity name (e.g. 'Company A'). Retrieve valid names from GET /companies.",
        examples=["Company A"],
    ),
):
    sql = """
        SELECT
            fsc.scope_credit_id,
            fsc.company_id,
            fsc.upload_id,
            dc.entity_name,
            fsc.metric_name,
            fsc.year,
            fsc.metric_value,
            fsc.loaded_at_utc
        FROM fact_scope_credit_hist fsc
        JOIN dim_company dc ON dc.company_id = fsc.company_id
        WHERE dc.entity_name = %s
        ORDER BY fsc.metric_name, fsc.year, fsc.upload_id
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (entity_name,))
            rows = cur.fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No time-series data found for company '{entity_name}'")
    return rows
