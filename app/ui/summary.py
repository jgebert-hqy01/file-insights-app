"""Renders every run_on_load query for the current filename."""
from typing import Callable, Dict, Optional

import streamlit as st

from app.db.executor import QueryExecutionError, QueryResult
from app.registry.models import QueryDefinition
from app.ui.components import render_footer, render_table

RunQuery = Callable[[QueryDefinition, Optional[Dict]], QueryResult]


def render_summary(
    run_query: RunQuery,
    row_cap: int,
    queries: Dict[str, QueryDefinition],
) -> None:
    summary_queries = [q for q in queries.values() if q.run_on_load]
    if not summary_queries:
        st.info("No summary queries are defined yet.")
        return

    for query_def in summary_queries:
        st.subheader(query_def.title)
        st.caption(query_def.description)
        try:
            result = run_query(query_def, None)
        except QueryExecutionError as exc:
            st.error(f"Could not run '{query_def.title}': {exc}")
            continue
        render_table(result.dataframe, result.row_cap_hit, row_cap)
        render_footer(query_def, result.ran_at, result.latency_seconds)
