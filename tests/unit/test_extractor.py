"""
test_extractor.py
-----------------
Unit tests for corporate_pipeline/extractor.py.

Tests use the real .xlsm files in data/input_files/ as fixtures, since the
MASTER sheet structure is fixed and small. No mocking is needed.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from corporate_pipeline.extractor import (
    RawMasterRecord,
    extract_all_files,
    extract_master_sheet,
    parse_master_record,
    save_extracted_sheet,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(filename: str, input_files_dir: Path) -> tuple[pd.DataFrame, RawMasterRecord]:
    path = input_files_dir / filename
    df = extract_master_sheet(path)
    record = parse_master_record(df, filename)
    return df, record


# ---------------------------------------------------------------------------
# extract_master_sheet — structural tests
# ---------------------------------------------------------------------------

class TestExtractMasterSheet:
    def test_loads_without_error(self, all_xlsm_files: list[Path]) -> None:
        for f in all_xlsm_files:
            df = extract_master_sheet(f)
            assert isinstance(df, pd.DataFrame)

    def test_non_empty_dataframe(self, all_xlsm_files: list[Path]) -> None:
        for f in all_xlsm_files:
            df = extract_master_sheet(f)
            assert len(df) > 0, f"{f.name}: MASTER sheet produced empty DataFrame"

    def test_no_fully_empty_rows(self, all_xlsm_files: list[Path]) -> None:
        for f in all_xlsm_files:
            df = extract_master_sheet(f)
            for idx, row in df.iterrows():
                assert not row.isna().all(), f"{f.name}: row {idx} is entirely empty"

    def test_at_least_20_non_empty_rows(self, all_xlsm_files: list[Path]) -> None:
        for f in all_xlsm_files:
            df = extract_master_sheet(f)
            assert len(df) >= 20, f"{f.name}: fewer than 20 non-empty rows"

    def test_string_values_stripped(self, all_xlsm_files: list[Path]) -> None:
        for f in all_xlsm_files:
            df = extract_master_sheet(f)
            for col in df.columns:
                for val in df[col]:
                    if isinstance(val, str):
                        assert val == val.strip(), (
                            f"{f.name}: column {col} has unstripped value: {val!r}"
                        )

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            extract_master_sheet(tmp_path / "nonexistent.xlsm")

    def test_key_column_is_col_b(self, all_xlsm_files: list[Path]) -> None:
        """Column B (index 1) must contain the row labels, not column A."""
        for f in all_xlsm_files:
            df = extract_master_sheet(f)
            col_a_non_null = df.iloc[:, 0].dropna()
            assert len(col_a_non_null) == 0, (
                f"{f.name}: column A (index 0) unexpectedly has values: {col_a_non_null.tolist()}"
            )


# ---------------------------------------------------------------------------
# parse_master_record — field extraction tests
# ---------------------------------------------------------------------------

class TestParseMasterRecordCompanyA1:
    @pytest.fixture(autouse=True)
    def setup(self, input_files_dir: Path) -> None:
        self.df, self.r = _load("corporates_A_1.xlsm", input_files_dir)

    def test_rated_entity(self) -> None:
        assert self.r.rated_entity == "Company A"

    def test_sector(self) -> None:
        assert self.r.sector == "Personal & Household Goods"

    def test_methodology_1(self) -> None:
        assert self.r.methodology_1 == "General Corporate Rating Methodology"

    def test_methodology_2(self) -> None:
        assert self.r.methodology_2 == "Consumer Products Rating Methodology"

    def test_industry_risk_1(self) -> None:
        assert self.r.industry_risk_1 == "Consumer Products: Non-Discretionary"

    def test_industry_risk_2_none(self) -> None:
        assert self.r.industry_risk_2 is None

    def test_industry_risk_score_1(self) -> None:
        assert self.r.industry_risk_score_1 == "A"

    def test_industry_risk_score_2_none(self) -> None:
        assert self.r.industry_risk_score_2 is None

    def test_industry_weight_1(self) -> None:
        assert self.r.industry_weight_1 == 1.0

    def test_industry_weight_2_none(self) -> None:
        assert self.r.industry_weight_2 is None

    def test_currency(self) -> None:
        assert self.r.currency == "EUR"

    def test_country(self) -> None:
        assert self.r.country == "Federal Republic of Germany"

    def test_accounting_principles(self) -> None:
        assert self.r.accounting_principles == "IFRS"

    def test_business_year_end(self) -> None:
        assert self.r.business_year_end == "December"

    def test_source_filename(self) -> None:
        assert self.r.source_filename == "corporates_A_1.xlsm"

    def test_financial_risk_profile(self) -> None:
        assert self.r.financial_risk_profile == "C"

    def test_leverage(self) -> None:
        assert self.r.leverage == "CCC"

    def test_liquidity_adjustment(self) -> None:
        assert self.r.liquidity_adjustment == "-2 notches"

    def test_scope_credit_metrics_has_entries(self) -> None:
        assert len(self.r.scope_credit_metrics) > 0

    def test_scope_credit_metrics_years(self) -> None:
        years = list(self.r.scope_credit_metrics.get(
            "Scope-adjusted EBITDA interest cover", {}
        ).keys())
        assert "2018" in years
        assert "2024" in years


class TestParseMasterRecordCompanyA2:
    """Version 2 of Company A — industry risk score changed from A → BBB,
    methodology_2 removed."""

    @pytest.fixture(autouse=True)
    def setup(self, input_files_dir: Path) -> None:
        self.df, self.r = _load("corporates_A_2.xlsm", input_files_dir)

    def test_industry_risk_score_changed(self) -> None:
        assert self.r.industry_risk_score_1 == "BBB"

    def test_methodology_2_dropped(self) -> None:
        assert self.r.methodology_2 is None

    def test_rated_entity_unchanged(self) -> None:
        assert self.r.rated_entity == "Company A"

    def test_currency_unchanged(self) -> None:
        assert self.r.currency == "EUR"


class TestParseMasterRecordCompanyB1:
    """Company B has two industry segments (dual weights that sum to 1.0)."""

    @pytest.fixture(autouse=True)
    def setup(self, input_files_dir: Path) -> None:
        self.df, self.r = _load("corporates_B_1.xlsm", input_files_dir)

    def test_rated_entity(self) -> None:
        assert self.r.rated_entity == "Company B"

    def test_sector(self) -> None:
        assert self.r.sector == "Automobiles & Parts"

    def test_industry_risk_2(self) -> None:
        assert self.r.industry_risk_2 == "Automotive and Commercial Vehicle Manufacturers"

    def test_industry_risk_score_2(self) -> None:
        assert self.r.industry_risk_score_2 == "BB"

    def test_industry_weight_1(self) -> None:
        assert self.r.industry_weight_1 == pytest.approx(0.15)

    def test_industry_weight_2(self) -> None:
        assert self.r.industry_weight_2 == pytest.approx(0.85)

    def test_weights_sum_to_one(self) -> None:
        total = (self.r.industry_weight_1 or 0.0) + (self.r.industry_weight_2 or 0.0)
        assert total == pytest.approx(1.0, abs=0.01)

    def test_currency_chf(self) -> None:
        assert self.r.currency == "CHF"

    def test_business_year_end_march(self) -> None:
        assert self.r.business_year_end == "March"

    def test_liquidity_positive_notch(self) -> None:
        assert self.r.liquidity_adjustment == "+1 notch"


class TestParseMasterRecordCompanyB2:
    """Version 2 of Company B — weights changed (0.15/0.85 → 0.25/0.75)."""

    @pytest.fixture(autouse=True)
    def setup(self, input_files_dir: Path) -> None:
        self.df, self.r = _load("corporates_B_2.xlsm", input_files_dir)

    def test_weight_1_changed(self) -> None:
        assert self.r.industry_weight_1 == pytest.approx(0.25)

    def test_weight_2_changed(self) -> None:
        assert self.r.industry_weight_2 == pytest.approx(0.75)

    def test_weights_still_sum_to_one(self) -> None:
        total = (self.r.industry_weight_1 or 0.0) + (self.r.industry_weight_2 or 0.0)
        assert total == pytest.approx(1.0, abs=0.01)


class TestParseMasterRecordMissingField:
    """sector_specific_factor_2 is None in all files — test graceful handling."""

    def test_optional_field_returns_none(self, input_files_dir: Path) -> None:
        _, r = _load("corporates_A_1.xlsm", input_files_dir)
        assert r.sector_specific_factor_2 is None

    def test_all_files_optional_field_none(self, all_xlsm_files: list[Path]) -> None:
        for f in all_xlsm_files:
            df = extract_master_sheet(f)
            r = parse_master_record(df, f.name)
            # sector_specific_factor_2 is None in the known dataset; must not raise
            _ = r.sector_specific_factor_2


# ---------------------------------------------------------------------------
# save_extracted_sheet
# ---------------------------------------------------------------------------

class TestSaveExtractedSheet:
    def test_creates_csv_file(self, input_files_dir: Path, tmp_path: Path) -> None:
        df = extract_master_sheet(input_files_dir / "corporates_A_1.xlsm")
        out = save_extracted_sheet(df, tmp_path, "corporates_A_1")
        assert out.exists()
        assert out.suffix == ".csv"
        assert out.name == "corporates_A_1_master.csv"

    def test_csv_has_rows(self, input_files_dir: Path, tmp_path: Path) -> None:
        df = extract_master_sheet(input_files_dir / "corporates_A_1.xlsm")
        out = save_extracted_sheet(df, tmp_path, "corporates_A_1")
        rows = out.read_text().splitlines()
        assert len(rows) > 0

    def test_csv_roundtrip_preserves_row_count(
        self, input_files_dir: Path, tmp_path: Path
    ) -> None:
        df = extract_master_sheet(input_files_dir / "corporates_A_1.xlsm")
        out = save_extracted_sheet(df, tmp_path, "corporates_A_1")
        reloaded = pd.read_csv(out, header=None, index_col=0)
        assert len(reloaded) == len(df)

    def test_creates_output_dir_if_missing(
        self, input_files_dir: Path, tmp_path: Path
    ) -> None:
        new_dir = tmp_path / "nested" / "output"
        df = extract_master_sheet(input_files_dir / "corporates_A_1.xlsm")
        save_extracted_sheet(df, new_dir, "test")
        assert new_dir.exists()

    def test_all_files_produce_csv(
        self, all_xlsm_files: list[Path], tmp_path: Path
    ) -> None:
        for f in all_xlsm_files:
            df = extract_master_sheet(f)
            out = save_extracted_sheet(df, tmp_path, f.stem)
            assert out.exists(), f"CSV not created for {f.name}"


# ---------------------------------------------------------------------------
# extract_all_files — batch processing
# ---------------------------------------------------------------------------

class TestExtractAllFiles:
    def test_returns_four_records(
        self, input_files_dir: Path, extracted_sheets_dir: Path
    ) -> None:
        records = extract_all_files(input_files_dir, extracted_sheets_dir)
        assert len(records) == 4

    def test_all_records_are_raw_master_record(
        self, input_files_dir: Path, extracted_sheets_dir: Path
    ) -> None:
        records = extract_all_files(input_files_dir, extracted_sheets_dir)
        for r in records:
            assert isinstance(r, RawMasterRecord)

    def test_source_filenames_set(
        self, input_files_dir: Path, extracted_sheets_dir: Path
    ) -> None:
        records = extract_all_files(input_files_dir, extracted_sheets_dir)
        names = {r.source_filename for r in records}
        assert names == {
            "corporates_A_1.xlsm",
            "corporates_A_2.xlsm",
            "corporates_B_1.xlsm",
            "corporates_B_2.xlsm",
        }

    def test_csv_files_written(
        self, input_files_dir: Path, extracted_sheets_dir: Path
    ) -> None:
        extract_all_files(input_files_dir, extracted_sheets_dir)
        csvs = list(extracted_sheets_dir.glob("*_master.csv"))
        assert len(csvs) == 4

    def test_two_companies_represented(
        self, input_files_dir: Path, extracted_sheets_dir: Path
    ) -> None:
        records = extract_all_files(input_files_dir, extracted_sheets_dir)
        entities = {r.rated_entity for r in records}
        assert entities == {"Company A", "Company B"}

    def test_versions_differ_on_changed_field(
        self, input_files_dir: Path, extracted_sheets_dir: Path
    ) -> None:
        records = extract_all_files(input_files_dir, extracted_sheets_dir)
        by_name = {r.source_filename: r for r in records}
        # A_1 has score A, A_2 has score BBB
        assert by_name["corporates_A_1.xlsm"].industry_risk_score_1 == "A"
        assert by_name["corporates_A_2.xlsm"].industry_risk_score_1 == "BBB"
        # B_1 weight 0.15, B_2 weight 0.25
        assert by_name["corporates_B_1.xlsm"].industry_weight_1 == pytest.approx(0.15)
        assert by_name["corporates_B_2.xlsm"].industry_weight_1 == pytest.approx(0.25)
