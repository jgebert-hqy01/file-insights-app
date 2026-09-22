"""Spark-based executor: the same QueryExecutor contract as client.py, used
by notebooks (the demo app and the smoke test) instead of the SQL connector.

Every table/column name is bound via SQL's IDENTIFIER() clause and every
value via a named :parameter -- never string-formatted into the SQL text.
An unset optional filter binds as Python None, which spark.sql(args=...)
treats as a typed SQL NULL, matching the VoidParameter semantics client.py
uses for the same case.
"""
import time
from typing import Any, Dict, Optional

from app.db.executor import NotReadOnlyError, QueryExecutionError, QueryExecutor, QueryResult
from app.masking import mask_dataframe
from app.registry.models import QueryDefinition, SourceDefinition
from app.registry.models import is_read_only_sql


class SparkExecutor(QueryExecutor):
    """Runs QueryDefinitions via spark.sql(), for use inside a Databricks notebook."""

    def __init__(self, spark, sources: Dict[str, SourceDefinition]):
        self.spark = spark
        self.sources = sources

    def execute(
        self,
        query_def: QueryDefinition,
        filename: str,
        filter_values: Optional[Dict[str, Any]] = None,
        row_cap: Optional[int] = None,
    ) -> QueryResult:
        if not is_read_only_sql(query_def.sql):
            raise NotReadOnlyError(
                f"Refusing to execute '{query_def.name}': SQL must start with SELECT or WITH."
            )

        filter_values = filter_values or {}
        args = {"filename": filename}
        for parameter in query_def.parameters:
            args[parameter.name] = filter_values.get(parameter.name)

        effective_cap = row_cap if row_cap is not None else query_def.row_cap

        ran_at = time.time()
        started_at = time.monotonic()
        try:
            df = self.spark.sql(query_def.sql, args=args)
            if effective_cap is not None:
                pdf = df.limit(effective_cap + 1).toPandas()
                row_cap_hit = len(pdf) > effective_cap
                dataframe = pdf.head(effective_cap)
            else:
                dataframe = df.toPandas()
                row_cap_hit = False
        except Exception as exc:
            raise QueryExecutionError(f"Query '{query_def.name}' failed: {exc}") from exc
        latency = time.monotonic() - started_at

        source = self.sources[query_def.source]
        dataframe = mask_dataframe(dataframe, query_def, source)

        return QueryResult(
            query_name=query_def.name,
            dataframe=dataframe,
            ran_at=ran_at,
            latency_seconds=latency,
            row_cap_hit=row_cap_hit,
        )


def describe_columns(spark, fully_qualified_view: str) -> Dict[str, str]:
    """Column name -> data type, via DESCRIBE TABLE with the table name bound
    through IDENTIFIER() -- never string-formatted."""
    rows = spark.sql("DESCRIBE TABLE IDENTIFIER(:fqn)", args={"fqn": fully_qualified_view}).collect()
    return {r["col_name"]: r["data_type"] for r in rows if not r["col_name"].startswith("#")}


def check_filename_exists(spark, source: SourceDefinition, filename: str) -> bool:
    """Parameterized existence check, mirroring client.check_filename_exists but via Spark."""
    if source.filename_column is None:
        raise ValueError(f"Source '{source.name}' has no filename_column to check against.")

    sql = "SELECT 1 FROM IDENTIFIER(:fqn) WHERE IDENTIFIER(:col) = :filename LIMIT 1"
    if not is_read_only_sql(sql):
        raise NotReadOnlyError("Existence check SQL must start with SELECT or WITH.")

    try:
        rows = spark.sql(
            sql,
            args={
                "fqn": source.fully_qualified_view,
                "col": source.filename_column,
                "filename": filename,
            },
        ).collect()
        return len(rows) > 0
    except Exception as exc:
        raise QueryExecutionError(f"Existence check against '{source.name}' failed: {exc}") from exc
