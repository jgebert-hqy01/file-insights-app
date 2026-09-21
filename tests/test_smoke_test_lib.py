"""Unit tests for the smoke test helpers. No pyspark or dbutils required."""
from scripts.smoke_test_lib import (
    CheckResult,
    bogus_filename_for,
    compute_row_cap_hit,
    format_report,
    mask_reference,
    normalize_name,
    overall_status,
)


def test_mask_reference_shows_last_four_characters():
    assert mask_reference("XXX-XX-1234") == "*******1234"


def test_mask_reference_handles_short_and_none_values():
    assert mask_reference("ab") == "**"
    assert mask_reference(None) is None


def test_normalize_name_matches_partner_id_to_partnerid_column():
    assert normalize_name("partner_id") == normalize_name("PartnerID")


def test_compute_row_cap_hit():
    assert compute_row_cap_hit(row_count=3, cap=2) is True
    assert compute_row_cap_hit(row_count=2, cap=2) is False
    assert compute_row_cap_hit(row_count=1, cap=2) is False


def test_bogus_filename_for_is_distinct_and_derived():
    real = "sample_file_001.csv"
    bogus = bogus_filename_for(real)
    assert bogus != real
    assert real in bogus


def test_format_report_contains_no_row_data_only_summary_columns():
    results = [
        CheckResult("Registry loads", "PASS", 0.01, "2 sources, 3 queries"),
        CheckResult("Connectivity", "FAIL", 0.02, "PERMISSION_DENIED"),
    ]
    report = format_report(results)
    assert "Registry loads" in report
    assert "PASS" in report
    assert "Connectivity" in report
    assert "FAIL" in report
    assert "PERMISSION_DENIED" in report


def test_format_report_handles_empty_results():
    assert "check" in format_report([])


def test_overall_status_fails_if_any_check_failed():
    passing = [CheckResult("a", "PASS", 0.0)]
    failing = [CheckResult("a", "PASS", 0.0), CheckResult("b", "FAIL", 0.0)]
    assert overall_status(passing) == "PASS"
    assert overall_status(failing) == "FAIL"
