"""The shared contract both executors implement.

`SqlConnectorExecutor` (client.py, used by the deployed app) and
`SparkExecutor` (spark_client.py, used by notebooks) both implement
`execute(query_def, filename, filter_values=None, row_cap=None) -> QueryResult`,
returning a dataframe that is already masked and already capped. Callers --
the Streamlit UI, the demo notebook, the smoke test -- never call masking
themselves; that's the executor's job, so there's exactly one place that
can get it wrong.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from app.registry.models import QueryDefinition


class NotReadOnlyError(ValueError):
    """Raised when a statement does not start with SELECT or WITH."""


class QueryExecutionError(RuntimeError):
    """Raised when the warehouse call fails, times out, or the warehouse is cold-starting."""


@dataclass
class QueryResult:
    query_name: str
    dataframe: pd.DataFrame  # masked, capped -- safe to render directly
    ran_at: float
    latency_seconds: float
    row_cap_hit: bool


class QueryExecutor(ABC):
    """Runs a QueryDefinition and returns a masked, row-capped QueryResult."""

    @abstractmethod
    def execute(
        self,
        query_def: QueryDefinition,
        filename: str,
        filter_values: Optional[Dict[str, Any]] = None,
        row_cap: Optional[int] = None,
    ) -> QueryResult:
        ...
