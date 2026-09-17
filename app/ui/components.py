"""Shared rendering helpers: capped tables, metrics, and the 'produced by' footer."""
from datetime import datetime

import pandas as pd
import streamlit as st

from app.registry.models import QueryDefinition


def render_footer(query_def: QueryDefinition, ran_at: float, latency_seconds: float) -> None:
    ran_at_label = datetime.fromtimestamp(ran_at).strftime("%Y-%m-%d %H:%M:%S")
    st.caption(f"Produced by `{query_def.name}` at {ran_at_label} ({latency_seconds:.2f}s)")


def render_table(dataframe: pd.DataFrame, row_cap_hit: bool, row_cap: int) -> None:
    if dataframe.empty:
        st.info("No rows returned.")
        return
    st.dataframe(dataframe, width="stretch")
    if row_cap_hit:
        st.caption(f"Showing the first {row_cap} rows.")
