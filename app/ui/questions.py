"""Question menu grouped by category, with filter controls generated from parameter metadata."""
from typing import Any, Callable, Dict, List, Optional

import streamlit as st

from app.db.executor import QueryExecutionError, QueryResult
from app.registry.models import ParameterControl, QueryDefinition, QueryParameter
from app.ui.components import render_footer, render_table

RunQuery = Callable[[QueryDefinition, Optional[Dict]], QueryResult]


def _render_parameter_control(parameter: QueryParameter, key_prefix: str) -> Any:
    key = f"{key_prefix}_{parameter.name}"
    if parameter.control == ParameterControl.NUMBER:
        value = st.number_input(parameter.label, value=None, step=1, key=key, format="%d")
        return int(value) if value is not None else None
    raise NotImplementedError(
        f"UI control '{parameter.control.value}' has no renderer yet. Add one to "
        f"app/ui/questions.py when the first query using it is added."
    )


def render_questions(
    run_query: RunQuery,
    row_cap: int,
    queries: Dict[str, QueryDefinition],
) -> None:
    drilldown_queries = [q for q in queries.values() if not q.run_on_load]
    if not drilldown_queries:
        st.info("No drill-down questions are defined yet.")
        return

    categories: Dict[str, List[QueryDefinition]] = {}
    for query_def in drilldown_queries:
        categories.setdefault(query_def.category, []).append(query_def)

    category = st.selectbox("Category", options=sorted(categories.keys()))
    options_by_title = {q.title: q for q in categories[category]}
    title = st.selectbox("Question", options=sorted(options_by_title.keys()))
    query_def = options_by_title[title]
    st.caption(query_def.description)

    filter_values = {}
    for parameter in query_def.parameters:
        filter_values[parameter.name] = _render_parameter_control(
            parameter, key_prefix=query_def.name
        )

    if st.button("Run", key=f"run_{query_def.name}"):
        try:
            result = run_query(query_def, filter_values)
        except QueryExecutionError as exc:
            st.error(f"Could not run '{query_def.title}': {exc}")
            return
        render_table(result.dataframe, result.row_cap_hit, row_cap)
        render_footer(query_def, result.ran_at, result.latency_seconds)
