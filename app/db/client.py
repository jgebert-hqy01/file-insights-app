"""Databricks SQL Warehouse client: connection, execution, and read-only enforcement.

Every value bound to a query -- the filename and every filter -- goes through
this module as a typed, named `databricks.sql.parameters.native` object. None
values become a typed SQL NULL (VoidParameter) rather than being interpolated,
so an unset optional filter still reaches the warehouse as a bound parameter,
never as a change to the SQL text.
"""
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd
from databricks import sql as databricks_sql
from databricks.sql.parameters.native import (
    DateParameter,
    IntegerParameter,
    StringParameter,
    TDbsqlParameter,
    VoidParameter,
)

from app.config import AppConfig, AuthMode
from app.registry.models import ParameterType, QueryDefinition, SourceDefinition
from app.registry.models import is_read_only_sql as _is_read_only_sql

logger = logging.getLogger(__name__)

_PARAMETER_TYPE_TO_CLASS = {
    ParameterType.STRING: StringParameter,
    ParameterType.INTEGER: IntegerParameter,
    ParameterType.DATE: DateParameter,
}


class NotReadOnlyError(ValueError):
    """Raised when a statement does not start with SELECT or WITH."""


class QueryExecutionError(RuntimeError):
    """Raised when the warehouse call fails, times out, or the warehouse is cold-starting."""


@dataclass
class QueryResult:
    query_name: str
    dataframe: pd.DataFrame
    ran_at: float
    latency_seconds: float
    row_cap_hit: bool


def is_read_only_statement(sql: str) -> bool:
    return _is_read_only_sql(sql)


def _build_bind_parameters(
    query_def: QueryDefinition, filename: str, filter_values: Dict[str, Any]
) -> List[TDbsqlParameter]:
    bound: List[TDbsqlParameter] = [StringParameter(name="filename", value=filename)]
    for parameter in query_def.parameters:
        value = filter_values.get(parameter.name)
        if value is None:
            bound.append(VoidParameter(name=parameter.name, value=None))
        else:
            param_cls = _PARAMETER_TYPE_TO_CLASS[parameter.type]
            bound.append(param_cls(name=parameter.name, value=value))
    return bound


def _connect(config: AppConfig):
    if config.auth_mode is AuthMode.SERVICE_PRINCIPAL:
        from databricks.sdk.core import Config as SdkConfig
        from databricks.sdk.core import oauth_service_principal

        def credentials_provider():
            sdk_config = SdkConfig(
                host=f"https://{config.databricks_host}",
                client_id=config.client_id,
                client_secret=config.client_secret,
            )
            return oauth_service_principal(sdk_config)

        return databricks_sql.connect(
            server_hostname=config.databricks_host,
            http_path=config.databricks_http_path,
            credentials_provider=credentials_provider,
        )

    return databricks_sql.connect(
        server_hostname=config.databricks_host,
        http_path=config.databricks_http_path,
        auth_type="databricks-oauth",
    )


def execute(
    config: AppConfig,
    query_def: QueryDefinition,
    filename: str,
    filter_values: Optional[Dict[str, Any]] = None,
    row_cap: Optional[int] = None,
) -> QueryResult:
    """Run a single QueryDefinition against the configured warehouse."""
    if not is_read_only_statement(query_def.sql):
        raise NotReadOnlyError(
            f"Refusing to execute '{query_def.name}': SQL must start with SELECT or WITH."
        )

    bind_parameters = _build_bind_parameters(query_def, filename, filter_values or {})
    effective_cap = row_cap if row_cap is not None else query_def.row_cap

    ran_at = time.time()
    started_at = time.monotonic()
    try:
        with _connect(config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query_def.sql, parameters=bind_parameters)
                if effective_cap is not None:
                    rows = cursor.fetchmany(effective_cap + 1)
                    row_cap_hit = len(rows) > effective_cap
                    rows = rows[:effective_cap]
                else:
                    rows = cursor.fetchall()
                    row_cap_hit = False
                columns = [col[0] for col in cursor.description] if cursor.description else []
                dataframe = pd.DataFrame([tuple(row) for row in rows], columns=columns)
    except Exception as exc:
        raise QueryExecutionError(f"Query '{query_def.name}' failed: {exc}") from exc
    latency = time.monotonic() - started_at

    logger.info(
        "query_run query_name=%s latency_seconds=%.3f row_count=%d row_cap_hit=%s",
        query_def.name,
        latency,
        len(dataframe),
        row_cap_hit,
    )
    return QueryResult(
        query_name=query_def.name,
        dataframe=dataframe,
        ran_at=ran_at,
        latency_seconds=latency,
        row_cap_hit=row_cap_hit,
    )


def check_filename_exists(config: AppConfig, source: SourceDefinition, filename: str) -> bool:
    """Parameterized existence check for a single source that declares a filename_column."""
    if source.filename_column is None:
        raise ValueError(f"Source '{source.name}' has no filename_column to check against.")

    sql = (
        f"SELECT 1 FROM {source.fully_qualified_view} "
        f"WHERE {source.filename_column} = :filename LIMIT 1"
    )
    if not is_read_only_statement(sql):
        raise NotReadOnlyError("Existence check SQL must start with SELECT or WITH.")

    try:
        with _connect(config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, parameters=[StringParameter(name="filename", value=filename)])
                return cursor.fetchone() is not None
    except Exception as exc:
        raise QueryExecutionError(f"Existence check against '{source.name}' failed: {exc}") from exc
