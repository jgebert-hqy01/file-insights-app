"""Filename validation shared by the UI and the existence check.

The pattern is a defensive allowlist (safe SQL-parameter characters, bounded
length) rather than an exact business-format match, since its job is to keep
unexpected characters away from the database layer before the parameterized
existence check ever runs.
"""
import re

FILENAME_MAX_LENGTH = 255
FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


def is_valid_filename(value: str) -> bool:
    return bool(value) and len(value) <= FILENAME_MAX_LENGTH and bool(FILENAME_PATTERN.match(value))
