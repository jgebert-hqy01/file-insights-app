"""Environment-derived application configuration.

No secret has a default: every value that could be sensitive is required to
come from the environment (App Service Key Vault references in production,
values exported in the terminal session for local dev), never from a file.
"""
import os
from dataclasses import dataclass
from enum import Enum


class MissingConfigError(RuntimeError):
    """Raised when a required environment variable is not set."""


class AuthMode(str, Enum):
    LOCAL_INTERACTIVE = "local_interactive"  # OAuth U2M: browser sign-in, no stored secret
    SERVICE_PRINCIPAL = "service_principal"  # OAuth M2M: client id/secret from Key Vault


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingConfigError(f"Required environment variable '{name}' is not set.")
    return value


@dataclass(frozen=True)
class AppConfig:
    databricks_host: str
    databricks_http_path: str
    auth_mode: AuthMode
    client_id: str = ""
    client_secret: str = ""
    default_row_cap: int = 500


def load_config() -> AppConfig:
    host = _require("DATABRICKS_HOST")
    http_path = _require("DATABRICKS_HTTP_PATH")
    auth_mode = AuthMode(os.environ.get("DATABRICKS_AUTH_MODE", AuthMode.LOCAL_INTERACTIVE.value))

    client_id = ""
    client_secret = ""
    if auth_mode is AuthMode.SERVICE_PRINCIPAL:
        client_id = _require("DATABRICKS_CLIENT_ID")
        client_secret = _require("DATABRICKS_CLIENT_SECRET")

    return AppConfig(
        databricks_host=host,
        databricks_http_path=http_path,
        auth_mode=auth_mode,
        client_id=client_id,
        client_secret=client_secret,
        default_row_cap=int(os.environ.get("DEFAULT_ROW_CAP", "500")),
    )
