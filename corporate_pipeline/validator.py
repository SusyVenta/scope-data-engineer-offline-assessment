"""
validator.py
------------
Data quality validation for extracted MASTER sheet records.

Public API:
  validate_record(record)          -> list[ValidationResult]
  generate_quality_report(results) -> dict
  is_valid(results)                -> bool   (no CRITICAL failures)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from corporate_pipeline.extractor import RawMasterRecord


# ---------------------------------------------------------------------------
# Rating scale
# ---------------------------------------------------------------------------

RATING_SCALE: set[str] = {
    "AAA", "AA+", "AA", "AA-",
    "A+",  "A",   "A-",
    "BBB+", "BBB", "BBB-",
    "BB+",  "BB",  "BB-",
    "B+",   "B",   "B-",
    "CCC+", "CCC", "CCC-",
    "CC",   "C",   "D",
}

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_NOTCH_RE    = re.compile(r"^[+-]\d+ notch(es)?$")

MONTH_NAMES: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    field: str
    rule: str
    passed: bool
    severity: str       # "CRITICAL" | "WARNING"
    message: str = ""


# ---------------------------------------------------------------------------
# Individual rule functions
# ---------------------------------------------------------------------------

def _check_not_null(field: str, value: Any, severity: str = "CRITICAL") -> ValidationResult:
    passed = value is not None and str(value).strip() != ""
    return ValidationResult(
        field=field,
        rule="not_null",
        passed=passed,
        severity=severity,
        message="" if passed else f"{field} is required but missing or empty",
    )


def _check_currency(currency: str | None) -> ValidationResult:
    if currency is None:
        return ValidationResult(
            field="currency", rule="iso3_format", passed=False,
            severity="CRITICAL", message="currency is missing",
        )
    passed = bool(_CURRENCY_RE.match(currency))
    return ValidationResult(
        field="currency",
        rule="iso3_format",
        passed=passed,
        severity="CRITICAL",
        message="" if passed else f"currency '{currency}' must be 3 uppercase letters (ISO 4217)",
    )


def _check_year_end_month(value: str | None) -> ValidationResult:
    """Accept month names (December) or integers 1-12."""
    if value is None:
        return ValidationResult(
            field="business_year_end", rule="valid_month", passed=False,
            severity="WARNING", message="business_year_end is missing",
        )
    normalised = value.strip().lower()
    by_name = normalised in MONTH_NAMES
    by_int = normalised.isdigit() and 1 <= int(normalised) <= 12
    passed = by_name or by_int
    return ValidationResult(
        field="business_year_end",
        rule="valid_month",
        passed=passed,
        severity="WARNING",
        message="" if passed else f"business_year_end '{value}' is not a valid month name or 1-12 integer",
    )


def _check_rating_score(field: str, value: str | None, severity: str = "WARNING") -> ValidationResult:
    if value is None:
        return ValidationResult(
            field=field, rule="rating_scale", passed=True,
            severity=severity, message="",  # optional field — None is fine
        )
    passed = value in RATING_SCALE
    return ValidationResult(
        field=field,
        rule="rating_scale",
        passed=passed,
        severity=severity,
        message="" if passed else f"{field} value '{value}' not in recognised rating scale",
    )


def _check_weight(field: str, value: float | None, required: bool = False) -> ValidationResult:
    if value is None:
        passed = not required
        return ValidationResult(
            field=field, rule="weight_range", passed=passed,
            severity="CRITICAL" if required else "WARNING",
            message="" if passed else f"{field} is required but missing",
        )
    passed = 0.0 <= value <= 1.0
    return ValidationResult(
        field=field,
        rule="weight_range",
        passed=passed,
        severity="CRITICAL",
        message="" if passed else f"{field} = {value} must be between 0 and 1",
    )


def _check_weights_sum(w1: float | None, w2: float | None) -> ValidationResult:
    """Weights must sum to approximately 1.0 (tolerance ±0.01)."""
    total = (w1 or 0.0) + (w2 or 0.0)
    passed = abs(total - 1.0) <= 0.01
    return ValidationResult(
        field="industry_weight",
        rule="weights_sum_to_one",
        passed=passed,
        severity="CRITICAL",
        message="" if passed else f"Industry weights sum to {total:.4f}, expected ~1.0",
    )


def _check_liquidity_adjustment(value: str | None) -> ValidationResult:
    if value is None:
        return ValidationResult(
            field="liquidity_adjustment", rule="notch_format", passed=False,
            severity="WARNING", message="liquidity_adjustment is missing",
        )
    passed = bool(_NOTCH_RE.match(value.strip()))
    return ValidationResult(
        field="liquidity_adjustment",
        rule="notch_format",
        passed=passed,
        severity="WARNING",
        message="" if passed else f"liquidity_adjustment '{value}' does not match expected notch format (e.g. '+1 notch', '-2 notches')",
    )


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------

def validate_record(record: RawMasterRecord) -> list[ValidationResult]:
    """Run all validation rules against a RawMasterRecord.

    Returns a list of ValidationResult items. Call is_valid() on the result
    to check whether any CRITICAL failures exist.
    """
    results: list[ValidationResult] = []

    # Required fields (CRITICAL)
    results.append(_check_not_null("rated_entity", record.rated_entity))
    results.append(_check_not_null("sector", record.sector))
    results.append(_check_not_null("country", record.country))
    results.append(_check_not_null("accounting_principles", record.accounting_principles))
    results.append(_check_not_null("methodology_1", record.methodology_1))
    results.append(_check_not_null("industry_risk_1", record.industry_risk_1))
    results.append(_check_not_null("industry_risk_score_1", record.industry_risk_score_1))

    # Currency format
    results.append(_check_currency(record.currency))

    # Business year end month
    results.append(_check_year_end_month(record.business_year_end))

    # Rating scale checks
    for field_name, value in [
        ("industry_risk_score_1", record.industry_risk_score_1),
        ("industry_risk_score_2", record.industry_risk_score_2),
        ("business_risk_profile", record.business_risk_profile),
        ("blended_industry_risk_profile", record.blended_industry_risk_profile),
        ("competitive_positioning", record.competitive_positioning),
        ("market_share", record.market_share),
        ("diversification", record.diversification),
        ("operating_profitability", record.operating_profitability),
        ("sector_specific_factor_1", record.sector_specific_factor_1),
        ("sector_specific_factor_2", record.sector_specific_factor_2),
        ("financial_risk_profile", record.financial_risk_profile),
        ("leverage", record.leverage),
        ("interest_cover", record.interest_cover),
        ("cash_flow_cover", record.cash_flow_cover),
    ]:
        results.append(_check_rating_score(field_name, value))

    # Weight range checks
    results.append(_check_weight("industry_weight_1", record.industry_weight_1, required=True))
    results.append(_check_weight("industry_weight_2", record.industry_weight_2, required=False))

    # Weights sum check
    results.append(_check_weights_sum(record.industry_weight_1, record.industry_weight_2))

    # Liquidity adjustment format
    results.append(_check_liquidity_adjustment(record.liquidity_adjustment))

    return results


def is_valid(results: list[ValidationResult]) -> bool:
    """Return True when there are no CRITICAL failures."""
    return all(r.passed for r in results if r.severity == "CRITICAL")


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

def generate_quality_report(
    results: list[ValidationResult],
    source_filename: str = "",
) -> dict:
    """Summarise validation results into a report dict.

    Keys:
      source_filename   – which file was validated
      total_checks      – number of rules evaluated
      passed            – number that passed
      failed_critical   – CRITICAL failures (block loading)
      failed_warning    – WARNING failures (logged but non-blocking)
      completeness_pct  – % of not_null checks that passed
      validity_pct      – % of all checks that passed
      failures          – list of dicts for failed checks
    """
    total = len(results)
    passed_count = sum(1 for r in results if r.passed)
    critical_failures = [r for r in results if not r.passed and r.severity == "CRITICAL"]
    warning_failures  = [r for r in results if not r.passed and r.severity == "WARNING"]

    null_checks = [r for r in results if r.rule == "not_null"]
    null_passed = sum(1 for r in null_checks if r.passed)
    completeness = round(null_passed / len(null_checks) * 100, 1) if null_checks else 100.0
    validity = round(passed_count / total * 100, 1) if total else 100.0

    return {
        "source_filename": source_filename,
        "total_checks": total,
        "passed": passed_count,
        "failed_critical": len(critical_failures),
        "failed_warning": len(warning_failures),
        "completeness_pct": completeness,
        "validity_pct": validity,
        "failures": [
            {"field": r.field, "rule": r.rule, "severity": r.severity, "message": r.message}
            for r in results if not r.passed
        ],
    }
