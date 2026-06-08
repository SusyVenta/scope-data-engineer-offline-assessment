"""
test_validator.py
-----------------
Unit tests for corporate_pipeline/validator.py.
Uses synthetic RawMasterRecord instances — no file I/O required.
"""

from __future__ import annotations

from corporate_pipeline.extractor import RawMasterRecord
from corporate_pipeline.validator import (
    EXPECTED_SCOPE_METRICS,
    KNOWN_ACCOUNTING_PRINCIPLES,
    ValidationResult,
    format_quality_report,
    generate_quality_report,
    is_valid,
    validate_record,
)


# ---------------------------------------------------------------------------
# Helper: build a fully-valid record
# ---------------------------------------------------------------------------

def _valid_record(**overrides) -> RawMasterRecord:
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
# is_valid / full record
# ---------------------------------------------------------------------------

class TestIsValid:
    def test_valid_record_passes(self) -> None:
        results = validate_record(_valid_record())
        assert is_valid(results)

    def test_missing_required_field_fails(self) -> None:
        results = validate_record(_valid_record(rated_entity=None))
        assert not is_valid(results)

    def test_invalid_currency_fails(self) -> None:
        results = validate_record(_valid_record(currency="euro"))
        assert not is_valid(results)

    def test_weight_over_one_fails(self) -> None:
        results = validate_record(_valid_record(industry_weight_1=1.5))
        assert not is_valid(results)

    def test_negative_weight_fails(self) -> None:
        results = validate_record(_valid_record(industry_weight_1=-0.1))
        assert not is_valid(results)

    def test_weights_not_summing_to_one_fails(self) -> None:
        results = validate_record(_valid_record(
            industry_weight_1=0.4, industry_weight_2=0.4
        ))
        assert not is_valid(results)


# ---------------------------------------------------------------------------
# Required-field checks
# ---------------------------------------------------------------------------

class TestNotNullChecks:
    def test_null_rated_entity(self) -> None:
        results = validate_record(_valid_record(rated_entity=None))
        failures = [r for r in results if not r.passed and r.field == "rated_entity"]
        assert len(failures) == 1
        assert failures[0].severity == "CRITICAL"

    def test_empty_string_rated_entity(self) -> None:
        results = validate_record(_valid_record(rated_entity=""))
        failures = [r for r in results if not r.passed and r.field == "rated_entity"]
        assert len(failures) == 1

    def test_null_sector(self) -> None:
        results = validate_record(_valid_record(sector=None))
        assert not is_valid(results)

    def test_null_country(self) -> None:
        results = validate_record(_valid_record(country=None))
        assert not is_valid(results)

    def test_null_accounting_principles(self) -> None:
        results = validate_record(_valid_record(accounting_principles=None))
        assert not is_valid(results)

    def test_null_methodology_1(self) -> None:
        results = validate_record(_valid_record(methodology_1=None))
        assert not is_valid(results)

    def test_null_industry_risk_1(self) -> None:
        results = validate_record(_valid_record(industry_risk_1=None))
        assert not is_valid(results)


# ---------------------------------------------------------------------------
# Currency checks
# ---------------------------------------------------------------------------

class TestCurrencyCheck:
    def test_valid_eur(self) -> None:
        results = validate_record(_valid_record(currency="EUR"))
        currency_results = [r for r in results if r.field == "currency"]
        assert all(r.passed for r in currency_results)

    def test_valid_chf(self) -> None:
        results = validate_record(_valid_record(currency="CHF"))
        currency_results = [r for r in results if r.field == "currency"]
        assert all(r.passed for r in currency_results)

    def test_lowercase_fails(self) -> None:
        results = validate_record(_valid_record(currency="eur"))
        currency_results = [r for r in results if r.field == "currency" and not r.passed]
        assert len(currency_results) == 1

    def test_too_short_fails(self) -> None:
        results = validate_record(_valid_record(currency="EU"))
        currency_results = [r for r in results if r.field == "currency" and not r.passed]
        assert len(currency_results) == 1

    def test_too_long_fails(self) -> None:
        results = validate_record(_valid_record(currency="EURO"))
        currency_results = [r for r in results if r.field == "currency" and not r.passed]
        assert len(currency_results) == 1

    def test_null_currency_fails(self) -> None:
        results = validate_record(_valid_record(currency=None))
        assert not is_valid(results)


# ---------------------------------------------------------------------------
# Business year-end month checks
# ---------------------------------------------------------------------------

class TestYearEndMonthCheck:
    def test_december_passes(self) -> None:
        results = validate_record(_valid_record(business_year_end="December"))
        yr_results = [r for r in results if r.field == "business_year_end"]
        assert all(r.passed for r in yr_results)

    def test_march_passes(self) -> None:
        results = validate_record(_valid_record(business_year_end="March"))
        yr_results = [r for r in results if r.field == "business_year_end"]
        assert all(r.passed for r in yr_results)

    def test_integer_string_passes(self) -> None:
        results = validate_record(_valid_record(business_year_end="12"))
        yr_results = [r for r in results if r.field == "business_year_end"]
        assert all(r.passed for r in yr_results)

    def test_zero_month_fails(self) -> None:
        results = validate_record(_valid_record(business_year_end="0"))
        yr_results = [r for r in results if r.field == "business_year_end" and not r.passed]
        assert len(yr_results) == 1

    def test_month_13_fails(self) -> None:
        results = validate_record(_valid_record(business_year_end="13"))
        yr_results = [r for r in results if r.field == "business_year_end" and not r.passed]
        assert len(yr_results) == 1

    def test_nonsense_fails(self) -> None:
        results = validate_record(_valid_record(business_year_end="Quatember"))
        yr_results = [r for r in results if r.field == "business_year_end" and not r.passed]
        assert len(yr_results) == 1


# ---------------------------------------------------------------------------
# Rating scale checks
# ---------------------------------------------------------------------------

class TestRatingScaleChecks:
    def test_valid_rating_bbb(self) -> None:
        results = validate_record(_valid_record(industry_risk_score_1="BBB"))
        score_results = [r for r in results if r.field == "industry_risk_score_1"]
        assert all(r.passed for r in score_results)

    def test_invalid_rating_fails(self) -> None:
        results = validate_record(_valid_record(industry_risk_score_1="XYZ"))
        score_results = [r for r in results if r.field == "industry_risk_score_1" and not r.passed]
        assert len(score_results) == 1

    def test_none_optional_rating_passes(self) -> None:
        results = validate_record(_valid_record(industry_risk_score_2=None))
        score_results = [r for r in results if r.field == "industry_risk_score_2"]
        assert all(r.passed for r in score_results)

    def test_all_valid_ratings_accepted(self) -> None:
        from corporate_pipeline.validator import RATING_SCALE
        for rating in RATING_SCALE:
            r = validate_record(_valid_record(industry_risk_score_1=rating))
            score_results = [x for x in r if x.field == "industry_risk_score_1" and not x.passed]
            assert len(score_results) == 0, f"Rating '{rating}' incorrectly rejected"


# ---------------------------------------------------------------------------
# Weight checks
# ---------------------------------------------------------------------------

class TestWeightChecks:
    def test_weight_1_required(self) -> None:
        results = validate_record(_valid_record(industry_weight_1=None))
        assert not is_valid(results)

    def test_weight_2_optional(self) -> None:
        results = validate_record(_valid_record(industry_weight_2=None))
        # Single-segment: weight_1=1.0, weight_2=None → should still sum to 1.0
        assert is_valid(results)

    def test_two_segments_sum_to_one(self) -> None:
        results = validate_record(_valid_record(
            industry_weight_1=0.15, industry_weight_2=0.85
        ))
        assert is_valid(results)

    def test_weights_0_15_0_85_pass(self) -> None:
        results = validate_record(_valid_record(
            industry_weight_1=0.15, industry_weight_2=0.85
        ))
        weight_failures = [r for r in results if "weight" in r.field and not r.passed]
        assert len(weight_failures) == 0

    def test_weights_0_25_0_75_pass(self) -> None:
        results = validate_record(_valid_record(
            industry_weight_1=0.25, industry_weight_2=0.75
        ))
        weight_failures = [r for r in results if "weight" in r.field and not r.passed]
        assert len(weight_failures) == 0

    def test_weight_exceeds_1_critical(self) -> None:
        results = validate_record(_valid_record(industry_weight_1=1.2))
        failures = [r for r in results if r.field == "industry_weight_1" and not r.passed]
        assert len(failures) == 1
        assert failures[0].severity == "CRITICAL"


# ---------------------------------------------------------------------------
# Liquidity adjustment format
# ---------------------------------------------------------------------------

class TestLiquidityAdjustment:
    def test_minus_2_notches(self) -> None:
        results = validate_record(_valid_record(liquidity_adjustment="-2 notches"))
        liq = [r for r in results if r.field == "liquidity_adjustment"]
        assert all(r.passed for r in liq)

    def test_plus_1_notch(self) -> None:
        results = validate_record(_valid_record(liquidity_adjustment="+1 notch"))
        liq = [r for r in results if r.field == "liquidity_adjustment"]
        assert all(r.passed for r in liq)

    def test_invalid_format_warning(self) -> None:
        results = validate_record(_valid_record(liquidity_adjustment="bad"))
        liq_fail = [r for r in results if r.field == "liquidity_adjustment" and not r.passed]
        assert len(liq_fail) == 1
        assert liq_fail[0].severity == "WARNING"

    def test_invalid_format_still_valid_record(self) -> None:
        """Liquidity format failure is WARNING — should not block loading."""
        results = validate_record(_valid_record(liquidity_adjustment="bad"))
        assert is_valid(results)


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

class TestGenerateQualityReport:
    def test_perfect_report(self) -> None:
        results = validate_record(_valid_record())
        report = generate_quality_report(results, "test.xlsm")
        assert report["failed_critical"] == 0
        assert report["validity_pct"] > 90.0
        assert report["completeness_pct"] == 100.0
        assert report["source_filename"] == "test.xlsm"

    def test_report_counts_failures(self) -> None:
        results = validate_record(_valid_record(
            rated_entity=None,
            currency="bad",
        ))
        report = generate_quality_report(results)
        assert report["failed_critical"] >= 2

    def test_report_failures_list(self) -> None:
        results = validate_record(_valid_record(rated_entity=None))
        report = generate_quality_report(results)
        fields_in_failures = [f["field"] for f in report["failures"]]
        assert "rated_entity" in fields_in_failures

    def test_report_total_matches_results(self) -> None:
        results = validate_record(_valid_record())
        report = generate_quality_report(results)
        assert report["total_checks"] == len(results)
        assert report["passed"] == sum(1 for r in results if r.passed)

    def test_validity_pct_decreases_with_failures(self) -> None:
        good = generate_quality_report(validate_record(_valid_record()))
        bad = generate_quality_report(validate_record(
            _valid_record(rated_entity=None, currency="x", industry_weight_1=None)
        ))
        assert bad["validity_pct"] < good["validity_pct"]


# ---------------------------------------------------------------------------
# New rule: accounting principles
# ---------------------------------------------------------------------------

class TestAccountingPrinciplesCheck:
    def test_ifrs_passes(self) -> None:
        results = validate_record(_valid_record(accounting_principles="IFRS"))
        failures = [r for r in results if r.field == "accounting_principles" and r.rule == "known_framework" and not r.passed]
        assert len(failures) == 0

    def test_us_gaap_passes(self) -> None:
        results = validate_record(_valid_record(accounting_principles="US GAAP"))
        failures = [r for r in results if r.field == "accounting_principles" and r.rule == "known_framework" and not r.passed]
        assert len(failures) == 0

    def test_all_known_principles_pass(self) -> None:
        for p in KNOWN_ACCOUNTING_PRINCIPLES:
            results = validate_record(_valid_record(accounting_principles=p))
            fails = [r for r in results if r.field == "accounting_principles" and r.rule == "known_framework" and not r.passed]
            assert len(fails) == 0, f"'{p}' should be accepted"

    def test_unknown_framework_warns(self) -> None:
        results = validate_record(_valid_record(accounting_principles="JGAAP"))
        failures = [r for r in results if r.field == "accounting_principles" and not r.passed]
        assert len(failures) == 1
        assert failures[0].severity == "WARNING"

    def test_unknown_framework_does_not_block_pipeline(self) -> None:
        results = validate_record(_valid_record(accounting_principles="JGAAP"))
        assert is_valid(results)


# ---------------------------------------------------------------------------
# New rule: dual risk consistency
# ---------------------------------------------------------------------------

class TestDualRiskConsistency:
    def test_both_absent_passes(self) -> None:
        results = validate_record(_valid_record(industry_risk_2=None, industry_weight_2=None))
        failures = [r for r in results if r.rule == "dual_risk_consistency" and not r.passed]
        assert len(failures) == 0

    def test_both_present_passes(self) -> None:
        results = validate_record(_valid_record(
            industry_risk_2="Consumer Goods", industry_weight_2=0.3,
            industry_weight_1=0.7,
        ))
        failures = [r for r in results if r.rule == "dual_risk_consistency" and not r.passed]
        assert len(failures) == 0

    def test_risk_without_weight_warns(self) -> None:
        results = validate_record(_valid_record(industry_risk_2="Consumer Goods", industry_weight_2=None))
        failures = [r for r in results if r.rule == "dual_risk_consistency" and not r.passed]
        assert len(failures) == 1
        assert failures[0].severity == "WARNING"

    def test_weight_without_risk_warns(self) -> None:
        results = validate_record(_valid_record(industry_risk_2=None, industry_weight_2=0.3))
        failures = [r for r in results if r.rule == "dual_risk_consistency" and not r.passed]
        assert len(failures) == 1
        assert failures[0].severity == "WARNING"

    def test_dual_risk_inconsistency_does_not_block_pipeline(self) -> None:
        results = validate_record(_valid_record(industry_risk_2="X", industry_weight_2=None))
        assert is_valid(results)


# ---------------------------------------------------------------------------
# New rule: scope metrics coverage
# ---------------------------------------------------------------------------

class TestScopeMetricsCoverage:
    def test_all_expected_metrics_passes(self) -> None:
        full_metrics = {m: {"2022": "1.0"} for m in EXPECTED_SCOPE_METRICS}
        results = validate_record(_valid_record(scope_credit_metrics=full_metrics))
        failures = [r for r in results if r.rule == "metrics_coverage" and not r.passed]
        assert len(failures) == 0

    def test_empty_metrics_warns(self) -> None:
        results = validate_record(_valid_record(scope_credit_metrics={}))
        failures = [r for r in results if r.rule == "metrics_coverage" and not r.passed]
        assert len(failures) == 1
        assert failures[0].severity == "WARNING"

    def test_partial_metrics_warns(self) -> None:
        partial = {EXPECTED_SCOPE_METRICS[0]: {"2022": "1.0"}}
        results = validate_record(_valid_record(scope_credit_metrics=partial))
        failures = [r for r in results if r.rule == "metrics_coverage" and not r.passed]
        assert len(failures) == 1

    def test_missing_metrics_does_not_block_pipeline(self) -> None:
        results = validate_record(_valid_record(scope_credit_metrics={}))
        assert is_valid(results)

    def test_failure_message_names_missing_metrics(self) -> None:
        partial = {EXPECTED_SCOPE_METRICS[0]: {"2022": "1.0"}}
        results = validate_record(_valid_record(scope_credit_metrics=partial))
        failure = next(r for r in results if r.rule == "metrics_coverage" and not r.passed)
        assert "missing" in failure.message.lower()


# ---------------------------------------------------------------------------
# format_quality_report
# ---------------------------------------------------------------------------

def _make_report(entity="Company A", fname="test.xlsm", n_checks=30, failures=None) -> dict:
    failures = failures or []
    n_crit = sum(1 for f in failures if f["severity"] == "CRITICAL")
    n_warn = sum(1 for f in failures if f["severity"] == "WARNING")
    n_pass = n_checks - len(failures)
    return {
        "source_filename": fname,
        "entity_name": entity,
        "total_checks": n_checks,
        "passed": n_pass,
        "failed_critical": n_crit,
        "failed_warning": n_warn,
        "completeness_pct": 100.0,
        "validity_pct": round(n_pass / n_checks * 100, 1),
        "failures": failures,
    }


class TestFormatQualityReport:
    def test_output_is_string(self) -> None:
        report = format_quality_report([_make_report()])
        assert isinstance(report, str)

    def test_header_present(self) -> None:
        report = format_quality_report([_make_report()], dag_run_id="run_001")
        assert "DATA QUALITY REPORT" in report
        assert "run_001" in report

    def test_passed_file_shows_checkmark(self) -> None:
        report = format_quality_report([_make_report()])
        assert "✓" in report
        assert "PASSED" in report

    def test_critical_failure_shows_field_and_message(self) -> None:
        failures = [{"field": "rated_entity", "rule": "not_null", "severity": "CRITICAL",
                     "message": "rated_entity is required but missing"}]
        report = format_quality_report([_make_report(failures=failures)])
        assert "✗" in report
        assert "rated_entity" in report
        assert "Critical" in report

    def test_warning_shows_in_output(self) -> None:
        failures = [{"field": "liquidity_adjustment", "rule": "notch_format",
                     "severity": "WARNING", "message": "bad format"}]
        report = format_quality_report([_make_report(failures=failures)])
        assert "⚠" in report
        assert "Warnings" in report

    def test_footer_shows_total_counts(self) -> None:
        report = format_quality_report([_make_report(), _make_report(fname="b.xlsm", entity="Company B")])
        assert "Checks:" in report
        assert "Passed:" in report

    def test_pipeline_halted_message_on_critical(self) -> None:
        failures = [{"field": "currency", "rule": "iso3_format", "severity": "CRITICAL", "message": "bad"}]
        report = format_quality_report([_make_report(failures=failures)])
        assert "PIPELINE HALTED" in report

    def test_may_proceed_message_when_clean(self) -> None:
        report = format_quality_report([_make_report()])
        assert "may proceed" in report

    def test_entity_name_appears_in_card(self) -> None:
        report = format_quality_report([_make_report(entity="Acme Corp")])
        assert "Acme Corp" in report

    def test_multiple_files_all_present(self) -> None:
        reports = [
            _make_report(entity="Company A", fname="a.xlsm"),
            _make_report(entity="Company B", fname="b.xlsm"),
        ]
        output = format_quality_report(reports)
        assert "Company A" in output
        assert "Company B" in output
        assert "1/2" in output
        assert "2/2" in output


# ---------------------------------------------------------------------------
# Validate real files
# ---------------------------------------------------------------------------

class TestValidateRealFiles:
    def test_all_real_files_pass_validation(self, all_xlsm_files, input_files_dir) -> None:
        from corporate_pipeline.extractor import extract_master_sheet, parse_master_record
        for f in all_xlsm_files:
            df = extract_master_sheet(f)
            record = parse_master_record(df, f.name)
            results = validate_record(record)
            report = generate_quality_report(results, f.name)
            assert is_valid(results), (
                f"{f.name} failed validation:\n"
                + "\n".join(
                    f"  [{x['severity']}] {x['field']}.{x['rule']}: {x['message']}"
                    for x in report["failures"]
                    if x["severity"] == "CRITICAL"
                )
            )
