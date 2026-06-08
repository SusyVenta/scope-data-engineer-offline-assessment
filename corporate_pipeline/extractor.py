"""
extractor.py
------------
Extracts the MASTER sheet from each corporate .xlsm file.

The MASTER sheet has a non-standard key-value layout:
  - Column A (index 0): always empty
  - Column B (index 1): row label / key
  - Column C (index 2): primary value
  - Column D (index 3): secondary value (present for multi-value rows such as
    Industry risk, Industry risk score, Industry weight, and Rating methodologies)
  - Columns E onward: time-series year headers and numeric values (rows 34-40)

Public API:
  extract_master_sheet(filepath)       -> pd.DataFrame  (raw key-value frame)
  parse_master_record(df, filename)    -> RawMasterRecord
  save_extracted_sheet(df, output_dir, stem)
  extract_all_files(input_dir, output_dir) -> list[RawMasterRecord]
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Row keys as they appear in column B of the MASTER sheet
# ---------------------------------------------------------------------------
_KEY_RATED_ENTITY = "Rated entity"
_KEY_SECTOR = "CorporateSector"
_KEY_METHODOLOGIES = "Rating methodologies applied"
_KEY_INDUSTRY_RISK = "Industry risk"
_KEY_INDUSTRY_SCORE = "Industry risk score"
_KEY_INDUSTRY_WEIGHT = "Industry weight"
_KEY_SEGMENTATION = "Segmentation criteria"
_KEY_CURRENCY = "Reporting Currency/Units"
_KEY_COUNTRY = "Country of origin"
_KEY_ACCOUNTING = "Accounting principles"
_KEY_YEAR_END = "End of business year"
_KEY_BIZ_RISK = "Business risk profile"
_KEY_BLENDED_INDUSTRY = "(Blended) Industry risk profile"
_KEY_COMP_POSITIONING = "Competitive Positioning"
_KEY_MARKET_SHARE = "Market share"
_KEY_DIVERSIFICATION = "Diversification"
_KEY_OP_PROFITABILITY = "Operating profitability"
_KEY_SECTOR_FACTOR_1 = "Sector/company-specific factors (1)"
_KEY_SECTOR_FACTOR_2 = "Sector/company-specific factors (2)"
_KEY_FIN_RISK = "Financial risk profile"
_KEY_LEVERAGE = "Leverage"
_KEY_INTEREST_COVER = "Interest cover"
_KEY_CASH_FLOW = "Cash flow cover"
_KEY_LIQUIDITY = "Liquidity"
_KEY_METRICS_HEADER = "[Scope Credit Metrics]"

# Financial metric row labels (rows 35-40)
_METRIC_KEYS = [
    "Scope-adjusted EBITDA interest cover",
    "Scope-adjusted debt/EBITDA",
    "Scope-adjusted FFO/debt",
    "Scope-adjusted loan/value",
    "Scope-adjusted FOCF/debt",
    "Liquidity",  # second occurrence — in the metrics block
]


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class RawMasterRecord:
    """All fields parsed from one MASTER sheet."""
    source_filename: str
    rated_entity: str | None
    sector: str | None
    methodology_1: str | None
    methodology_2: str | None
    industry_risk_1: str | None
    industry_risk_2: str | None
    industry_risk_score_1: str | None
    industry_risk_score_2: str | None
    industry_weight_1: float | None
    industry_weight_2: float | None
    segmentation_criteria: str | None
    currency: str | None
    country: str | None
    accounting_principles: str | None
    business_year_end: str | None
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
    # Time-series metrics: {metric_name: {year: value}}
    scope_credit_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Sheet extraction
# ---------------------------------------------------------------------------

def extract_master_sheet(filepath: str | Path) -> pd.DataFrame:
    """Load the MASTER sheet from an .xlsm file into a raw DataFrame.

    Returns a DataFrame where:
      - Every non-empty row is preserved (empty rows are dropped)
      - Leading/trailing whitespace is stripped from all string cells
      - The sheet's original row index is preserved as the DataFrame index

    Raises FileNotFoundError if the file does not exist.
    Raises ValueError if the file has no MASTER sheet.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Input file not found: {filepath}")

    df = pd.read_excel(
        filepath,
        sheet_name="MASTER",
        header=None,
        engine="openpyxl",
    )

    # Strip leading/trailing whitespace from all string cells
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)

    # Drop rows that are entirely empty (all cells None/NaN)
    df = df.dropna(how="all")

    return df


def _get_value(key_map: dict[str, tuple[Any, Any]], key: str, col: int = 0) -> Any:
    """Return value from key_map[key][col], or None if key/col absent."""
    entry = key_map.get(key)
    if entry is None:
        return None
    return entry[col] if col < len(entry) else None


def _clean_str(value: Any) -> str | None:
    """Return stripped string or None for empty/None values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s if s else None


def _clean_float(value: Any) -> float | None:
    """Return float or None for non-numeric/empty values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_master_record(df: pd.DataFrame, source_filename: str) -> RawMasterRecord:
    """Parse a raw MASTER sheet DataFrame into a RawMasterRecord.

    Uses column B (index 1) as the key and columns C (index 2) / D (index 3)
    as primary and secondary values. Empty rows have already been dropped by
    extract_master_sheet().

    The [Scope Credit Metrics] block (rows 34-40) is parsed separately into
    a nested dict: {metric_name: {str(year): value}}.
    """
    # Build key → (primary_value, secondary_value) map
    # Scan all rows; use stripped key from column 1
    key_map: dict[str, tuple[Any, Any]] = {}
    metrics_years: list[str] = []
    in_metrics = False

    for _, row in df.iterrows():
        key = _clean_str(row.iloc[1] if len(row) > 1 else None)
        if key is None:
            continue

        val1 = row.iloc[2] if len(row) > 2 else None
        val2 = row.iloc[3] if len(row) > 3 else None

        # Normalise NaN → None
        if isinstance(val1, float) and pd.isna(val1):
            val1 = None
        if isinstance(val2, float) and pd.isna(val2):
            val2 = None

        if key == _KEY_METRICS_HEADER:
            in_metrics = True
            # Columns 2..11 are year headers
            metrics_years = []
            for i in range(2, len(row)):
                yr = row.iloc[i]
                if yr is None or (isinstance(yr, float) and pd.isna(yr)):
                    break
                # Normalize numeric years: 2020.0 → "2020"; keep strings like "2025E"
                if isinstance(yr, (int, float)) and not pd.isna(yr):
                    yr = int(yr) if float(yr) == int(yr) else yr
                metrics_years.append(str(yr).strip())
            key_map[key] = (val1, val2)
            continue

        key_map[key] = (val1, val2)

    # Parse time-series metrics block
    scope_credit_metrics: dict[str, dict[str, Any]] = {}
    if metrics_years:
        metric_count = 0
        for _, row in df.iterrows():
            key = _clean_str(row.iloc[1] if len(row) > 1 else None)
            if key is None:
                continue
            # Skip the header row itself
            if key == _KEY_METRICS_HEADER:
                continue
            # Only collect rows that come after the metrics header in the sheet
            # We identify metric rows by checking if key appears in _METRIC_KEYS
            # or if we're past row 34 and in the time-series block.
            # Use row position: rows 35-40 (0-indexed: 34-39 after drop)
            # Simpler: collect up to 6 rows after the header row
            if key in (
                "Scope-adjusted EBITDA interest cover",
                "Scope-adjusted debt/EBITDA",
                "Scope-adjusted FFO/debt",
                "Scope-adjusted loan/value",
                "Scope-adjusted FOCF/debt",
            ):
                values: dict[str, Any] = {}
                for i, yr in enumerate(metrics_years):
                    col_idx = 2 + i
                    raw = row.iloc[col_idx] if col_idx < len(row) else None
                    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                        raw = None
                    elif isinstance(raw, str) and raw.strip() in ("Locked", "No data", ""):
                        raw = raw.strip() if raw.strip() else None
                    values[yr] = raw
                scope_credit_metrics[key] = values
                metric_count += 1

    # Handle the Liquidity row in the metrics block (last row, row 40)
    # It appears twice in the sheet — once at row 30 (notch adjustment) and
    # once at row 40 (time-series). We capture the time-series version separately.
    liq_rows = []
    for _, row in df.iterrows():
        key = _clean_str(row.iloc[1] if len(row) > 1 else None)
        if key == _KEY_LIQUIDITY:
            liq_rows.append(row)

    if len(liq_rows) >= 2 and metrics_years:
        row = liq_rows[1]  # second occurrence = time-series row
        values = {}
        for i, yr in enumerate(metrics_years):
            col_idx = 2 + i
            raw = row.iloc[col_idx] if col_idx < len(row) else None
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                raw = None
            elif isinstance(raw, str) and raw.strip() in ("Locked", "No data", ""):
                raw = raw.strip() if raw.strip() else None
            values[yr] = raw
        scope_credit_metrics["Liquidity (time-series)"] = values

    return RawMasterRecord(
        source_filename=source_filename,
        rated_entity=_clean_str(_get_value(key_map, _KEY_RATED_ENTITY, 0)),
        sector=_clean_str(_get_value(key_map, _KEY_SECTOR, 0)),
        methodology_1=_clean_str(_get_value(key_map, _KEY_METHODOLOGIES, 0)),
        methodology_2=_clean_str(_get_value(key_map, _KEY_METHODOLOGIES, 1)),
        industry_risk_1=_clean_str(_get_value(key_map, _KEY_INDUSTRY_RISK, 0)),
        industry_risk_2=_clean_str(_get_value(key_map, _KEY_INDUSTRY_RISK, 1)),
        industry_risk_score_1=_clean_str(_get_value(key_map, _KEY_INDUSTRY_SCORE, 0)),
        industry_risk_score_2=_clean_str(_get_value(key_map, _KEY_INDUSTRY_SCORE, 1)),
        industry_weight_1=_clean_float(_get_value(key_map, _KEY_INDUSTRY_WEIGHT, 0)),
        industry_weight_2=_clean_float(_get_value(key_map, _KEY_INDUSTRY_WEIGHT, 1)),
        segmentation_criteria=_clean_str(_get_value(key_map, _KEY_SEGMENTATION, 0)),
        currency=_clean_str(_get_value(key_map, _KEY_CURRENCY, 0)),
        country=_clean_str(_get_value(key_map, _KEY_COUNTRY, 0)),
        accounting_principles=_clean_str(_get_value(key_map, _KEY_ACCOUNTING, 0)),
        business_year_end=_clean_str(_get_value(key_map, _KEY_YEAR_END, 0)),
        business_risk_profile=_clean_str(_get_value(key_map, _KEY_BIZ_RISK, 0)),
        blended_industry_risk_profile=_clean_str(_get_value(key_map, _KEY_BLENDED_INDUSTRY, 0)),
        competitive_positioning=_clean_str(_get_value(key_map, _KEY_COMP_POSITIONING, 0)),
        market_share=_clean_str(_get_value(key_map, _KEY_MARKET_SHARE, 0)),
        diversification=_clean_str(_get_value(key_map, _KEY_DIVERSIFICATION, 0)),
        operating_profitability=_clean_str(_get_value(key_map, _KEY_OP_PROFITABILITY, 0)),
        sector_specific_factor_1=_clean_str(_get_value(key_map, _KEY_SECTOR_FACTOR_1, 0)),
        sector_specific_factor_2=_clean_str(_get_value(key_map, _KEY_SECTOR_FACTOR_2, 0)),
        financial_risk_profile=_clean_str(_get_value(key_map, _KEY_FIN_RISK, 0)),
        leverage=_clean_str(_get_value(key_map, _KEY_LEVERAGE, 0)),
        interest_cover=_clean_str(_get_value(key_map, _KEY_INTEREST_COVER, 0)),
        cash_flow_cover=_clean_str(_get_value(key_map, _KEY_CASH_FLOW, 0)),
        liquidity_adjustment=_clean_str(liq_rows[0].iloc[2] if liq_rows else None),
        scope_credit_metrics=scope_credit_metrics,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_extracted_sheet(df: pd.DataFrame, output_dir: str | Path, stem: str) -> Path:
    """Save the raw key-value DataFrame to a CSV in output_dir.

    Filename: <stem>_master.csv
    Returns the path to the written file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{stem}_master.csv"
    df.to_csv(out_path, index=True, header=False)
    return out_path


# ---------------------------------------------------------------------------
# Batch extraction
# ---------------------------------------------------------------------------

def extract_all_files(
    input_dir: str | Path,
    output_dir: str | Path,
) -> list[RawMasterRecord]:
    """Extract MASTER sheet from every .xlsm file in input_dir.

    For each file:
      1. Load the MASTER sheet via extract_master_sheet()
      2. Save the raw DataFrame to output_dir via save_extracted_sheet()
      3. Parse into a RawMasterRecord via parse_master_record()

    Returns a list of RawMasterRecord (one per file), sorted by filename.
    Raises if any individual file fails — callers should handle per-file errors.
    """
    input_dir = Path(input_dir)
    records: list[RawMasterRecord] = []

    for filepath in sorted(input_dir.glob("*.xlsm")):
        df = extract_master_sheet(filepath)
        save_extracted_sheet(df, output_dir, filepath.stem)
        record = parse_master_record(df, filepath.name)
        records.append(record)

    return records
