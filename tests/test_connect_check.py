"""Tests for scripts/connect_check.py's diagnostic flow: a mocked
SqlConnectorExecutor and mocked registries throughout -- nothing here calls
out to a real Databricks SQL Warehouse, and no test asserts on row data."""
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from app.config import AppConfig, AuthMode, MissingConfigError
from app.registry.models import (
    ParameterControl,
    ParameterType,
    QueryDefinition,
    QueryParameter,
    SourceDefinition,
)
from scripts import connect_check

FAKE_TOKEN = "fake-test-token-do-not-use-xyz123"

CONFIG = AppConfig(
    databricks_host="test.azuredatabricks.net",
    databricks_http_path="/sql/1.0/warehouses/abc123def456",
    auth_mode=AuthMode.PAT,
    token=FAKE_TOKEN,
)

SOURCE = SourceDefinition(
    name="test_source",
    fully_qualified_view="catalog.schema.view",
    filename_column="FileName",
    columns=[],
    sensitive_columns=[],
    description="test",
)

SUMMARY_QUERY = QueryDefinition(
    name="summary_query",
    title="Summary",
    description="test",
    category="Diagnostics",
    source="test_source",
    sql="SELECT 1 AS x FROM t WHERE FileName = :filename",
    run_on_load=True,
)

DRILLDOWN_QUERY = QueryDefinition(
    name="drilldown_query",
    title="Drilldown",
    description="test",
    category="Diagnostics",
    source="test_source",
    sql=(
        "SELECT 1 AS x FROM t WHERE FileName = :filename "
        "AND (:partner_id IS NULL OR PartnerID = :partner_id)"
    ),
    parameters=[
        QueryParameter(
            name="partner_id",
            label="Partner ID",
            type=ParameterType.INTEGER,
            control=ParameterControl.NUMBER,
        )
    ],
)


def _fake_result(rows):
    return SimpleNamespace(dataframe=pd.DataFrame(rows))


def _run_main(monkeypatch, filename="sample_file_001.csv"):
    monkeypatch.setattr(sys, "argv", ["connect_check.py", "--filename", filename])
    return connect_check.main()


def test_invalid_filename_rejected_before_any_connection_attempt(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["connect_check.py", "--filename", "../etc/passwd"])
    with pytest.raises(SystemExit):
        connect_check.main()


@patch("scripts.connect_check.load_config", side_effect=MissingConfigError("Required environment variable 'DATABRICKS_HOST' is not set."))
def test_missing_env_vars_fails_fast_without_attempting_a_connection(mock_load_config, monkeypatch, capsys):
    exit_code = _run_main(monkeypatch)

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "Overall: FAIL" in output


@patch("scripts.connect_check.SqlConnectorExecutor")
@patch("scripts.connect_check.check_filename_exists", return_value=True)
@patch("scripts.connect_check.load_registries")
@patch("scripts.connect_check.load_config", return_value=CONFIG)
def test_full_run_passes_and_never_prints_the_token_or_row_data(
    mock_load_config, mock_load_registries, mock_check_exists, mock_executor_cls, monkeypatch, capsys
):
    mock_load_registries.return_value = (
        {"test_source": SOURCE},
        {"summary_query": SUMMARY_QUERY, "drilldown_query": DRILLDOWN_QUERY},
    )
    executor_instance = mock_executor_cls.return_value
    executor_instance.execute.side_effect = [
        _fake_result([{"user_name": "test.user@example.com"}]),  # connectivity probe
        _fake_result([{"user_name": "test.user@example.com"}]),  # warehouse-state probe
        _fake_result([{"x": 1}]),  # summary query
        _fake_result([{"x": 1}]),  # drill-down query, filter unset
    ]

    exit_code = _run_main(monkeypatch)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Overall: PASS" in output
    assert FAKE_TOKEN not in output
    assert "current_user() = test.user@example.com" in output
    assert "Warehouse ID: abc123def456" in output
    assert "catalog.schema.view" in output
    assert "Grants needed: SELECT" in output


@patch("scripts.connect_check.SqlConnectorExecutor")
@patch("scripts.connect_check.check_filename_exists", return_value=False)
@patch("scripts.connect_check.load_registries")
@patch("scripts.connect_check.load_config", return_value=CONFIG)
def test_existence_check_failure_marks_overall_fail(
    mock_load_config, mock_load_registries, mock_check_exists, mock_executor_cls, monkeypatch, capsys
):
    mock_load_registries.return_value = ({"test_source": SOURCE}, {})
    executor_instance = mock_executor_cls.return_value
    executor_instance.execute.return_value = _fake_result([{"user_name": "test.user@example.com"}])

    exit_code = _run_main(monkeypatch)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Overall: FAIL" in output
    assert FAKE_TOKEN not in output
