"""Caller-identity allowlist check.

Stubbed: compares the caller's identifier against a configured
comma-separated allowlist. Real Entra ID security-group membership
checking (via Microsoft Graph) is a follow-up task, not implemented here.
Secure by default: an unconfigured or missing caller id is denied, not
allowed.
"""
import os
from typing import Optional

_ALLOWED_CALLER_IDS_ENV_VAR = "BOT_ALLOWED_CALLER_IDS"


def is_caller_allowed(caller_id: Optional[str]) -> bool:
    if not caller_id:
        return False
    allowed_raw = os.environ.get(_ALLOWED_CALLER_IDS_ENV_VAR)
    if not allowed_raw:
        return False
    allowed = {value.strip() for value in allowed_raw.split(",") if value.strip()}
    return caller_id in allowed
