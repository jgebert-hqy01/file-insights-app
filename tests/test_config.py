"""Tests for app/config.py: auth mode selection, the pat-mode production
refusal, and that secrets never show up in AppConfig's repr."""
import pytest

from app.config import AppConfig, AuthMode, AuthModeNotAllowedError, MissingConfigError, load_config


def _clear_databricks_env(monkeypatch):
    for name in (
        "DATABRICKS_HOST",
        "DATABRICKS_HTTP_PATH",
        "DATABRICKS_AUTH_MODE",
        "DATABRICKS_CLIENT_ID",
        "DATABRICKS_CLIENT_SECRET",
        "DATABRICKS_TOKEN",
        "APP_ENV",
        "WEBSITE_SITE_NAME",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_auth_mode_is_oauth_u2m(monkeypatch):
    _clear_databricks_env(monkeypatch)
    monkeypatch.setenv("DATABRICKS_HOST", "test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/test")

    config = load_config()

    assert config.auth_mode is AuthMode.LOCAL_INTERACTIVE
    assert config.auth_mode.value == "oauth-u2m"
    assert config.token == ""


def test_oauth_m2m_mode_requires_client_id_and_secret(monkeypatch):
    _clear_databricks_env(monkeypatch)
    monkeypatch.setenv("DATABRICKS_HOST", "test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/test")
    monkeypatch.setenv("DATABRICKS_AUTH_MODE", "oauth-m2m")

    with pytest.raises(MissingConfigError):
        load_config()

    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "test-client-secret")
    config = load_config()
    assert config.auth_mode is AuthMode.SERVICE_PRINCIPAL
    assert config.client_id == "test-client-id"
    assert config.client_secret == "test-client-secret"


def test_pat_mode_requires_token(monkeypatch):
    _clear_databricks_env(monkeypatch)
    monkeypatch.setenv("DATABRICKS_HOST", "test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/test")
    monkeypatch.setenv("DATABRICKS_AUTH_MODE", "pat")

    with pytest.raises(MissingConfigError):
        load_config()

    monkeypatch.setenv("DATABRICKS_TOKEN", "fake-test-token-xyz")
    config = load_config()
    assert config.auth_mode is AuthMode.PAT
    assert config.token == "fake-test-token-xyz"


def test_pat_mode_refused_when_app_env_is_production(monkeypatch):
    _clear_databricks_env(monkeypatch)
    monkeypatch.setenv("DATABRICKS_HOST", "test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/test")
    monkeypatch.setenv("DATABRICKS_AUTH_MODE", "pat")
    monkeypatch.setenv("DATABRICKS_TOKEN", "fake-test-token-xyz")
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(AuthModeNotAllowedError):
        load_config()


def test_pat_mode_refused_when_website_site_name_is_set(monkeypatch):
    _clear_databricks_env(monkeypatch)
    monkeypatch.setenv("DATABRICKS_HOST", "test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/test")
    monkeypatch.setenv("DATABRICKS_AUTH_MODE", "pat")
    monkeypatch.setenv("DATABRICKS_TOKEN", "fake-test-token-xyz")
    monkeypatch.setenv("WEBSITE_SITE_NAME", "file-insights-app")

    with pytest.raises(AuthModeNotAllowedError):
        load_config()


def test_pat_mode_allowed_when_app_env_is_not_production(monkeypatch):
    _clear_databricks_env(monkeypatch)
    monkeypatch.setenv("DATABRICKS_HOST", "test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/test")
    monkeypatch.setenv("DATABRICKS_AUTH_MODE", "pat")
    monkeypatch.setenv("DATABRICKS_TOKEN", "fake-test-token-xyz")
    monkeypatch.setenv("APP_ENV", "development")

    config = load_config()
    assert config.auth_mode is AuthMode.PAT


def test_app_config_repr_never_includes_token_or_client_secret():
    config = AppConfig(
        databricks_host="test.azuredatabricks.net",
        databricks_http_path="/sql/1.0/warehouses/test",
        auth_mode=AuthMode.PAT,
        client_secret="super-secret-value",
        token="super-secret-token",
    )

    representation = repr(config)

    assert "super-secret-value" not in representation
    assert "super-secret-token" not in representation
    assert "test.azuredatabricks.net" in representation  # non-secret fields still show
