"""Tests for the SQL-connector executor: read-only enforcement, parameter
binding, and masking.

These use a mocked connector throughout -- no test here calls out to a real
Databricks SQL Warehouse.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig, AuthMode
from app.db.client import SqlConnectorExecutor, check_filename_exists, is_read_only_statement
from app.db.executor import NotReadOnlyError, QueryExecutionError
from app.registry.models import (
    ColumnDefinition,
    ParameterControl,
    ParameterType,
    QueryDefinition,
    QueryParameter,
    SourceDefinition,
)

CONFIG = AppConfig(
    databricks_host="test.azuredatabricks.net",
    databricks_http_path="/sql/1.0/warehouses/test",
    auth_mode=AuthMode.LOCAL_INTERACTIVE,
)

SOURCES = {
    "test_source": SourceDefinition(
        name="test_source",
        fully_qualified_view="catalog.schema.view",
        filename_column="FileName",
        columns=[],
        sensitive_columns=[],
        description="test",
    ),
    "sensitive_source": SourceDefinition(
        name="sensitive_source",
        fully_qualified_view="catalog.schema.view",
        filename_column="FileName",
        columns=[ColumnDefinition(name="SSN", data_type="string")],
        sensitive_columns=["SSN"],
        description="test",
    ),
}


def _query(sql, parameters=None, row_cap=None, source="test_source"):
    return QueryDefinition(
        name="test_query",
        title="Test",
        description="Test",
        category="Test",
        source=source,
        sql=sql,
        parameters=parameters or [],
        row_cap=row_cap,
    )


def _mock_cursor(mock_connect):
    cursor = MagicMock()
    mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cursor
    return cursor


def test_is_read_only_statement_accepts_select_and_with():
    assert is_read_only_statement("SELECT 1")
    assert is_read_only_statement("  with x as (select 1) select * from x")


def test_is_read_only_statement_rejects_other_statements():
    assert not is_read_only_statement("DELETE FROM table")
    assert not is_read_only_statement("INSERT INTO table VALUES (1)")


def test_execute_refuses_non_select_even_if_the_object_is_mutated_after_validation():
    query_def = _query("SELECT 1 AS x WHERE 1 = :filename")
    query_def.sql = "DELETE FROM samples.nyctaxi.trips WHERE id = :filename"
    executor = SqlConnectorExecutor(CONFIG, SOURCES)
    with pytest.raises(NotReadOnlyError):
        executor.execute(query_def, "sample_file_001.csv")


@patch("app.db.client.databricks_sql.connect")
def test_execute_binds_filename_and_declared_parameters(mock_connect):
    cursor = _mock_cursor(mock_connect)
    cursor.fetchall.return_value = [(1, "a")]
    cursor.description = [("col1", None), ("col2", None)]

    query_def = _query(
        "SELECT col1, col2 FROM t WHERE FileName = :filename AND PartnerID = :partner_id",
        parameters=[
            QueryParameter(
                name="partner_id",
                label="Partner ID",
                type=ParameterType.INTEGER,
                control=ParameterControl.NUMBER,
            )
        ],
    )

    executor = SqlConnectorExecutor(CONFIG, SOURCES)
    result = executor.execute(query_def, "sample_file_001.csv", filter_values={"partner_id": 42})

    args, kwargs = cursor.execute.call_args
    assert args[0] == query_def.sql
    bound_by_name = {p.name: p.value for p in kwargs["parameters"]}
    assert bound_by_name["filename"] == "sample_file_001.csv"
    assert bound_by_name["partner_id"] == 42
    assert list(result.dataframe.columns) == ["col1", "col2"]
    assert result.dataframe.iloc[0]["col1"] == 1


@patch("app.db.client.databricks_sql.connect")
def test_execute_binds_missing_optional_filter_as_typed_null(mock_connect):
    cursor = _mock_cursor(mock_connect)
    cursor.fetchall.return_value = []
    cursor.description = [("col1", None)]

    query_def = _query(
        "SELECT col1 FROM t WHERE FileName = :filename AND (:partner_id IS NULL OR PartnerID = :partner_id)",
        parameters=[
            QueryParameter(
                name="partner_id",
                label="Partner ID",
                type=ParameterType.INTEGER,
                control=ParameterControl.NUMBER,
            )
        ],
    )

    executor = SqlConnectorExecutor(CONFIG, SOURCES)
    executor.execute(query_def, "sample_file_001.csv", filter_values={"partner_id": None})

    _, kwargs = cursor.execute.call_args
    partner_param = next(p for p in kwargs["parameters"] if p.name == "partner_id")
    assert partner_param.value is None


@patch("app.db.client.databricks_sql.connect")
def test_execute_applies_row_cap_and_reports_when_it_was_hit(mock_connect):
    cursor = _mock_cursor(mock_connect)
    cursor.fetchmany.return_value = [(1,), (2,), (3,)]
    cursor.description = [("col1", None)]

    query_def = _query("SELECT col1 FROM t WHERE FileName = :filename", row_cap=2)

    executor = SqlConnectorExecutor(CONFIG, SOURCES)
    result = executor.execute(query_def, "sample_file_001.csv")

    cursor.fetchmany.assert_called_once_with(3)
    assert len(result.dataframe) == 2
    assert result.row_cap_hit is True


@patch("app.db.client.databricks_sql.connect")
def test_execute_masks_sensitive_columns_before_returning(mock_connect):
    cursor = _mock_cursor(mock_connect)
    cursor.fetchall.return_value = [("XXX-XX-1234",)]
    cursor.description = [("SSN", None)]

    query_def = _query(
        "SELECT SSN FROM t WHERE FileName = :filename", source="sensitive_source"
    )

    executor = SqlConnectorExecutor(CONFIG, SOURCES)
    result = executor.execute(query_def, "sample_file_001.csv")

    assert result.dataframe.iloc[0]["SSN"] == "*******1234"


@patch("app.db.client.databricks_sql.connect")
def test_execute_wraps_connector_errors(mock_connect):
    mock_connect.side_effect = RuntimeError("warehouse is starting up")
    query_def = _query("SELECT 1 AS x FROM t WHERE FileName = :filename")

    executor = SqlConnectorExecutor(CONFIG, SOURCES)
    with pytest.raises(QueryExecutionError):
        executor.execute(query_def, "sample_file_001.csv")


@patch("app.db.client.databricks_sql.connect")
def test_check_filename_exists_true_and_false(mock_connect):
    cursor = _mock_cursor(mock_connect)
    source = SOURCES["test_source"]

    cursor.fetchone.return_value = (1,)
    assert check_filename_exists(CONFIG, source, "sample_file_001.csv") is True

    cursor.fetchone.return_value = None
    assert check_filename_exists(CONFIG, source, "sample_file_001.csv") is False
