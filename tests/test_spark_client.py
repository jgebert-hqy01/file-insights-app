"""Tests for the Spark-based executor: read-only enforcement, parameter
binding, and masking -- mirroring test_client.py but for spark_client.py.

Uses a minimal fake stand-in for pyspark.sql.SparkSession/DataFrame (just
.sql()/.limit()/.toPandas()/.collect(), scripted per test) so these tests
run without pyspark installed.
"""
import pandas as pd
import pytest

from app.db.executor import NotReadOnlyError, QueryExecutionError
from app.db.spark_client import SparkExecutor, check_filename_exists, describe_columns
from app.registry.models import (
    ColumnDefinition,
    ParameterControl,
    ParameterType,
    QueryDefinition,
    QueryParameter,
    SourceDefinition,
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


class FakeDataFrame:
    def __init__(self, rows, columns):
        self._rows = rows
        self.columns = columns

    def limit(self, n):
        return FakeDataFrame(self._rows[:n], self.columns)

    def toPandas(self):
        return pd.DataFrame(self._rows, columns=self.columns)

    def collect(self):
        return [dict(zip(self.columns, row)) for row in self._rows]


class FakeSparkSession:
    def __init__(self, sql_fn):
        self._sql_fn = sql_fn
        self.calls = []

    def sql(self, sql_text, args=None):
        self.calls.append((sql_text, args))
        return self._sql_fn(sql_text, args)


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


def test_execute_refuses_non_select_even_if_the_object_is_mutated_after_validation():
    query_def = _query("SELECT 1 AS x WHERE 1 = :filename")
    query_def.sql = "DELETE FROM samples.nyctaxi.trips WHERE id = :filename"
    spark = FakeSparkSession(lambda sql_text, args: (_ for _ in ()).throw(AssertionError("should not run")))
    executor = SparkExecutor(spark, SOURCES)
    with pytest.raises(NotReadOnlyError):
        executor.execute(query_def, "sample_file_001.csv")


def test_execute_binds_filename_and_declared_parameters():
    def sql_fn(sql_text, args):
        assert args == {"filename": "sample_file_001.csv", "partner_id": 42}
        return FakeDataFrame([(1, "a")], ["col1", "col2"])

    spark = FakeSparkSession(sql_fn)
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

    executor = SparkExecutor(spark, SOURCES)
    result = executor.execute(query_def, "sample_file_001.csv", filter_values={"partner_id": 42})

    assert list(result.dataframe.columns) == ["col1", "col2"]
    assert result.dataframe.iloc[0]["col1"] == 1


def test_execute_binds_missing_optional_filter_as_none():
    def sql_fn(sql_text, args):
        assert args["partner_id"] is None
        return FakeDataFrame([], ["col1"])

    spark = FakeSparkSession(sql_fn)
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

    executor = SparkExecutor(spark, SOURCES)
    executor.execute(query_def, "sample_file_001.csv", filter_values={"partner_id": None})


def test_execute_applies_row_cap_and_reports_when_it_was_hit():
    spark = FakeSparkSession(lambda sql_text, args: FakeDataFrame([(1,), (2,), (3,)], ["col1"]))
    query_def = _query("SELECT col1 FROM t WHERE FileName = :filename", row_cap=2)

    executor = SparkExecutor(spark, SOURCES)
    result = executor.execute(query_def, "sample_file_001.csv")

    assert len(result.dataframe) == 2
    assert result.row_cap_hit is True


def test_execute_masks_sensitive_columns_before_returning():
    spark = FakeSparkSession(lambda sql_text, args: FakeDataFrame([("XXX-XX-1234",)], ["SSN"]))
    query_def = _query("SELECT SSN FROM t WHERE FileName = :filename", source="sensitive_source")

    executor = SparkExecutor(spark, SOURCES)
    result = executor.execute(query_def, "sample_file_001.csv")

    assert result.dataframe.iloc[0]["SSN"] == "*******1234"


def test_execute_wraps_spark_errors():
    def sql_fn(sql_text, args):
        raise RuntimeError("warehouse is starting up")

    spark = FakeSparkSession(sql_fn)
    query_def = _query("SELECT 1 AS x FROM t WHERE FileName = :filename")

    executor = SparkExecutor(spark, SOURCES)
    with pytest.raises(QueryExecutionError):
        executor.execute(query_def, "sample_file_001.csv")


def test_describe_columns_binds_table_name_via_identifier_and_skips_hash_rows():
    def sql_fn(sql_text, args):
        assert sql_text == "DESCRIBE TABLE IDENTIFIER(:fqn)"
        assert args == {"fqn": "catalog.schema.view"}
        return FakeDataFrame(
            [("FileName", "string"), ("BatchID", "int"), ("# Partitioning", "")],
            ["col_name", "data_type"],
        )

    spark = FakeSparkSession(sql_fn)
    columns = describe_columns(spark, "catalog.schema.view")

    assert columns == {"FileName": "string", "BatchID": "int"}


def test_check_filename_exists_true_and_false():
    source = SOURCES["test_source"]

    spark_hit = FakeSparkSession(lambda sql_text, args: FakeDataFrame([(1,)], ["1"]))
    assert check_filename_exists(spark_hit, source, "sample_file_001.csv") is True

    spark_miss = FakeSparkSession(lambda sql_text, args: FakeDataFrame([], ["1"]))
    assert check_filename_exists(spark_miss, source, "sample_file_001.csv") is False


def test_check_filename_exists_binds_table_and_column_via_identifier():
    captured = {}

    def sql_fn(sql_text, args):
        captured["sql"] = sql_text
        captured["args"] = args
        return FakeDataFrame([], ["1"])

    spark = FakeSparkSession(sql_fn)
    check_filename_exists(spark, SOURCES["test_source"], "sample_file_001.csv")

    assert "IDENTIFIER(:fqn)" in captured["sql"]
    assert "IDENTIFIER(:col)" in captured["sql"]
    assert captured["args"] == {
        "fqn": "catalog.schema.view",
        "col": "FileName",
        "filename": "sample_file_001.csv",
    }
