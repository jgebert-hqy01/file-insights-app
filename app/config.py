"""Environment-derived application configuration.

No secret has a default: every value that could be sensitive is required to
come from the environment (App Service Key Vault references in production,
values exported in the terminal session for local dev), never from a file.
"""
import os
from dataclasses import dataclass, field
from enum import Enum


class MissingConfigError(RuntimeError):
    """Raised when a required environment variable is not set."""


class AuthModeNotAllowedError(RuntimeError):
    """Raised when an auth mode is disallowed in the current environment."""


class AuthMode(str, Enum):
    PAT = "pat"  # personal access token: local, temporary use only -- see docs/local-connection.md
    LOCAL_INTERACTIVE = "oauth-u2m"  # OAuth U2M: browser sign-in, no stored secret
    SERVICE_PRINCIPAL = "oauth-m2m"  # OAuth M2M: client id/secret from Key Vault


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingConfigError(f"Required environment variable '{name}' is not set.")
    return value


def _running_in_production_or_app_service() -> bool:
    return os.environ.get("APP_ENV") == "production" or bool(os.environ.get("WEBSITE_SITE_NAME"))


@dataclass(frozen=True)
class AppConfig:
    databricks_host: str
    databricks_http_path: str
    auth_mode: AuthMode
    client_id: str = ""
    client_secret: str = field(default="", repr=False)
    token: str = field(default="", repr=False)
    default_row_cap: int = 500


def load_config() -> AppConfig:
    host = _require("DATABRICKS_HOST")
    http_path = _require("DATABRICKS_HTTP_PATH")
    auth_mode = AuthMode(os.environ.get("DATABRICKS_AUTH_MODE", AuthMode.LOCAL_INTERACTIVE.value))

    client_id = ""
    client_secret = ""
    token = ""

    if auth_mode is AuthMode.PAT:
        if _running_in_production_or_app_service():
            raise AuthModeNotAllowedError(
                "DATABRICKS_AUTH_MODE=pat is not allowed when APP_ENV=production or "
                "WEBSITE_SITE_NAME is set (App Service). This mode is for local, "
                "temporary use only -- see docs/local-connection.md."
            )
        token = _require("DATABRICKS_TOKEN")
    elif auth_mode is AuthMode.SERVICE_PRINCIPAL:
        client_id = _require("DATABRICKS_CLIENT_ID")
        client_secret = _require("DATABRICKS_CLIENT_SECRET")

    return AppConfig(
        databricks_host=host,
        databricks_http_path=http_path,
        auth_mode=auth_mode,
        client_id=client_id,
        client_secret=client_secret,
        token=token,
        default_row_cap=int(os.environ.get("DEFAULT_ROW_CAP", "500")),
    )
