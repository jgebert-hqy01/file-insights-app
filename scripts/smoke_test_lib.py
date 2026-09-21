"""Pure-Python helpers shared by the smoke test notebook and scripts/smoke_test.py.

Nothing here touches Spark, dbutils, or a Databricks connection -- that keeps
these functions unit-testable without pyspark installed.
"""
from dataclasses import dataclass, field
from typing import List, Optional

_MASK_VISIBLE_SUFFIX_LENGTH = 4
_MASK_CHAR = "*"


@dataclass
class CheckResult:
    check: str
    status: str  # "PASS" or "FAIL"
    duration_seconds: float
    note: str = field(default="")


def mask_reference(raw_value) -> Optional[str]:
    """Independent reimplementation of the masking formula in app/masking.py,
    used to verify that module's actual output rather than call it directly."""
    if raw_value is None:
        return None
    text = str(raw_value)
    if len(text) <= _MASK_VISIBLE_SUFFIX_LENGTH:
        return _MASK_CHAR * len(text)
    return _MASK_CHAR * (len(text) - _MASK_VISIBLE_SUFFIX_LENGTH) + text[-_MASK_VISIBLE_SUFFIX_LENGTH:]


def normalize_name(name: str) -> str:
    """Loose match key for pairing a QueryParameter name (e.g. 'partner_id')
    with a source column (e.g. 'PartnerID') when sampling a real filter value."""
    return name.replace("_", "").lower()


def compute_row_cap_hit(row_count: int, cap: int) -> bool:
    return row_count > cap


def bogus_filename_for(filename: str) -> str:
    """A filename derived from the real one so it's guaranteed distinct, but
    still shaped like a real filename (passes the same validation regex)."""
    return "{0}.smoketest-bogus-9f3a".format(filename)


def format_report(results: List[CheckResult]) -> str:
    """Builds the plain-text summary table: check, status, duration, note.

    Callers must never put row data into a CheckResult.note -- only counts,
    durations, column names, and error messages belong here.
    """
    headers = ("check", "status", "duration_s", "note")
    rows = [(r.check, r.status, "{0:.2f}".format(r.duration_seconds), r.note) for r in results]
    widths = [
        max([len(headers[i])] + [len(row[i]) for row in rows])
        for i in range(len(headers))
    ]

    def _format_row(values):
        return " | ".join(value.ljust(widths[i]) for i, value in enumerate(values))

    lines = [_format_row(headers), "-+-".join("-" * w for w in widths)]
    lines.extend(_format_row(row) for row in rows)
    return "\n".join(lines)


def overall_status(results: List[CheckResult]) -> str:
    return "FAIL" if any(r.status == "FAIL" for r in results) else "PASS"
