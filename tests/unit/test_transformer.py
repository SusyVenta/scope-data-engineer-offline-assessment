"""
test_transformer.py
-------------------
Unit tests for corporate_pipeline/transformer.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from corporate_pipeline.extractor import RawMasterRecord
from corporate_pipeline.transformer import (
    RatingRecord,
    _compute_hash,
    _parse_month,
    transform_all,
    transform_record,
)


# ---------------------------------------------------------------------------
# Helper: build a minimal valid RawMasterRecord
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _raw(**overrides) -> RawMasterRecord:
    base = RawMasterRecord(
        source_filename="test.xlsm",
        rated_entity="Test Corp",
        sector="Industrials",
        methodology_1="General Corporate Rating Methodology",
        methodology_2=None,
        industry_risk_1="Industrial Goods",
        industry_risk_2=None,
        industry_risk_score_1="BBB",
        industry_risk_score_2=None,
        industry_weight_1=1.0,
        industry_weight_2=None,
        segmentation_criteria="EBITDA contribution",
        currency="EUR",
        country="Germany",
        accounting_principles="IFRS",
        business_year_end="December",
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
    )
    for k, v in overrides.items():
        object.__setattr__(base, k, v)
    return base


# ---------------------------------------------------------------------------
# _parse_month
# ---------------------------------------------------------------------------

class TestParseMonth:
    def test_december_returns_12(self) -> None:
        assert _parse_month("December") == 12

    def test_march_returns_3(self) -> None:
        assert _parse_month("March") == 3

    def test_january_returns_1(self) -> None:
        assert _parse_month("January") == 1

    def test_lowercase_month_name(self) -> None:
        assert _parse_month("december") == 12

    def test_integer_string_12(self) -> None:
        assert _parse_month("12") == 12

    def test_integer_string_1(self) -> None:
        assert _parse_month("1") == 1

    def test_zero_returns_none(self) -> None:
        assert _parse_month("0") is None

    def test_13_returns_none(self) -> None:
        assert _parse_month("13") is None

    def test_none_returns_none(self) -> None:
        assert _parse_month(None) is None

    def test_nonsense_returns_none(self) -> None:
        assert _parse_month("Quatember") is None


# ---------------------------------------------------------------------------
# _compute_hash
# ---------------------------------------------------------------------------

class TestComputeHash:
    def test_returns_64_char_hex(self) -> None:
        h = _compute_hash({"a": 1})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self) -> None:
        data = {"a": 1, "b": "hello"}
        assert _compute_hash(data) == _compute_hash(data)

    def test_key_order_independent(self) -> None:
        assert _compute_hash({"a": 1, "b": 2}) == _compute_hash({"b": 2, "a": 1})

    def test_different_data_different_hash(self) -> None:
        assert _compute_hash({"a": 1}) != _compute_hash({"a": 2})

    def test_none_values_included(self) -> None:
        assert _compute_hash({"a": None}) != _compute_hash({"a": 1})


# ---------------------------------------------------------------------------
# transform_record — field transformations
# ---------------------------------------------------------------------------

class TestTransformRecord:
    def test_returns_rating_record(self) -> None:
        result = transform_record(_raw(), _NOW)
        assert isinstance(result, RatingRecord)

    def test_source_filename_preserved(self) -> None:
        result = transform_record(_raw(source_filename="corp_A.xlsm"), _NOW)
        assert result.source_filename == "corp_A.xlsm"

    def test_currency_uppercase(self) -> None:
        result = transform_record(_raw(currency="eur"), _NOW)
        assert result.currency == "EUR"

    def test_currency_already_uppercase_preserved(self) -> None:
        result = transform_record(_raw(currency="CHF"), _NOW)
        assert result.currency == "CHF"

    def test_whitespace_stripped_from_entity(self) -> None:
        result = transform_record(_raw(rated_entity="  Test Corp  "), _NOW)
        assert result.rated_entity == "Test Corp"

    def test_whitespace_stripped_from_country(self) -> None:
        result = transform_record(_raw(country="  Germany  "), _NOW)
        assert result.country == "Germany"

    def test_december_converted_to_12(self) -> None:
        result = transform_record(_raw(business_year_end="December"), _NOW)
        assert result.business_year_end_month == 12

    def test_march_converted_to_3(self) -> None:
        result = transform_record(_raw(business_year_end="March"), _NOW)
        assert result.business_year_end_month == 3

    def test_none_year_end_stays_none(self) -> None:
        result = transform_record(_raw(business_year_end=None), _NOW)
        assert result.business_year_end_month is None

    def test_file_modified_at_stored(self) -> None:
        result = transform_record(_raw(), _NOW)
        assert result.file_modified_at == _NOW

    def test_effective_date_equals_file_modified_at(self) -> None:
        result = transform_record(_raw(), _NOW)
        assert result.effective_date == _NOW

    def test_data_hash_is_64_char_hex(self) -> None:
        result = transform_record(_raw(), _NOW)
        assert len(result.data_hash) == 64
        assert all(c in "0123456789abcdef" for c in result.data_hash)

    def test_weights_preserved(self) -> None:
        result = transform_record(_raw(industry_weight_1=0.25, industry_weight_2=0.75), _NOW)
        assert result.industry_weight_1 == pytest.approx(0.25)
        assert result.industry_weight_2 == pytest.approx(0.75)

    def test_scope_credit_metrics_preserved(self) -> None:
        metrics = {"Scope-adjusted debt/EBITDA": {"2023": 3.5, "2024": 3.1}}
        result = transform_record(_raw(scope_credit_metrics=metrics), _NOW)
        assert result.scope_credit_metrics == metrics


# ---------------------------------------------------------------------------
# Hash determinism & content-dependence
# ---------------------------------------------------------------------------

class TestHashBehavior:
    def test_same_content_same_hash(self) -> None:
        r1 = transform_record(_raw(), _NOW)
        r2 = transform_record(_raw(), _NOW)
        assert r1.data_hash == r2.data_hash

    def test_different_filename_same_hash(self) -> None:
        """Hash must be content-only — filename change must not change hash."""
        r1 = transform_record(_raw(source_filename="file_v1.xlsm"), _NOW)
        r2 = transform_record(_raw(source_filename="file_v2.xlsm"), _NOW)
        assert r1.data_hash == r2.data_hash

    def test_different_mtime_same_hash(self) -> None:
        """File modification time must not affect content hash."""
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 6, 1, tzinfo=timezone.utc)
        r1 = transform_record(_raw(), t1)
        r2 = transform_record(_raw(), t2)
        assert r1.data_hash == r2.data_hash

    def test_changed_score_changes_hash(self) -> None:
        r1 = transform_record(_raw(industry_risk_score_1="A"), _NOW)
        r2 = transform_record(_raw(industry_risk_score_1="BBB"), _NOW)
        assert r1.data_hash != r2.data_hash

    def test_changed_weight_changes_hash(self) -> None:
        r1 = transform_record(_raw(industry_weight_1=0.15, industry_weight_2=0.85), _NOW)
        r2 = transform_record(_raw(industry_weight_1=0.25, industry_weight_2=0.75), _NOW)
        assert r1.data_hash != r2.data_hash

    def test_a1_and_a2_have_different_hashes(self, input_files_dir) -> None:
        """Real files: Company A v1 vs v2 must differ in hash."""
        from corporate_pipeline.extractor import extract_master_sheet, parse_master_record
        df1 = extract_master_sheet(input_files_dir / "corporates_A_1.xlsm")
        r1 = parse_master_record(df1, "corporates_A_1.xlsm")
        df2 = extract_master_sheet(input_files_dir / "corporates_A_2.xlsm")
        r2 = parse_master_record(df2, "corporates_A_2.xlsm")
        t1 = transform_record(r1, _NOW)
        t2 = transform_record(r2, _NOW)
        assert t1.data_hash != t2.data_hash

    def test_b1_and_b2_have_different_hashes(self, input_files_dir) -> None:
        from corporate_pipeline.extractor import extract_master_sheet, parse_master_record
        df1 = extract_master_sheet(input_files_dir / "corporates_B_1.xlsm")
        r1 = parse_master_record(df1, "corporates_B_1.xlsm")
        df2 = extract_master_sheet(input_files_dir / "corporates_B_2.xlsm")
        r2 = parse_master_record(df2, "corporates_B_2.xlsm")
        t1 = transform_record(r1, _NOW)
        t2 = transform_record(r2, _NOW)
        assert t1.data_hash != t2.data_hash


# ---------------------------------------------------------------------------
# transform_all
# ---------------------------------------------------------------------------

class TestTransformAll:
    def test_returns_correct_count(self) -> None:
        raws = [_raw(source_filename=f"f{i}.xlsm") for i in range(3)]
        results = transform_all(raws, {})
        assert len(results) == 3

    def test_mtime_applied_from_map(self) -> None:
        t = datetime(2025, 3, 15, tzinfo=timezone.utc)
        raw = _raw(source_filename="corp.xlsm")
        results = transform_all([raw], {"corp.xlsm": t})
        assert results[0].file_modified_at == t

    def test_fallback_mtime_when_not_in_map(self) -> None:
        raw = _raw(source_filename="unknown.xlsm")
        results = transform_all([raw], {})
        assert results[0].file_modified_at is not None

    def test_all_four_real_files(self, input_files_dir) -> None:
        from corporate_pipeline.extractor import extract_all_files
        from pathlib import Path
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            records = extract_all_files(input_files_dir, Path(tmpdir))
            mtimes = {
                r.source_filename: datetime.fromtimestamp(
                    (input_files_dir / r.source_filename).stat().st_mtime,
                    tz=timezone.utc,
                )
                for r in records
            }
            results = transform_all(records, mtimes)
            assert len(results) == 4
            hashes = {r.data_hash for r in results}
            assert len(hashes) == 4, "All 4 files must produce unique hashes"
