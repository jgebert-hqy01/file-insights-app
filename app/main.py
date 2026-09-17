"""Streamlit entry point."""
import streamlit as st

from app.auth import get_signed_in_user
from app.config import MissingConfigError, load_config
from app.db.client import QueryExecutionError, check_filename_exists, execute
from app.registry.loader import RegistryError, load_registries
from app.ui.questions import render_questions
from app.ui.summary import render_summary
from app.validation import is_valid_filename

st.set_page_config(page_title="File Insight", layout="wide")


def _load_config_or_stop():
    try:
        return load_config()
    except MissingConfigError as exc:
        st.error(f"Configuration error: {exc}")
        st.stop()


def _load_registries_or_stop():
    try:
        return load_registries()
    except RegistryError as exc:
        st.error(f"Registry error: {exc}")
        st.stop()


def main() -> None:
    config = _load_config_or_stop()
    sources, queries = _load_registries_or_stop()
    user = get_signed_in_user()

    st.title("File Insight")
    st.caption(f"Signed in as {user}")

    filename = st.text_input("Filename")
    if not filename:
        st.stop()

    if not is_valid_filename(filename):
        st.error("That filename doesn't look valid. Use letters, numbers, '.', '_', or '-' only.")
        st.stop()

    if st.session_state.get("cached_filename") != filename:
        st.session_state.query_cache = {}
        st.session_state.existence_cache = None
        st.session_state.cached_filename = filename

    query_cache = st.session_state.query_cache

    def run_query(query_def, filter_values=None):
        key = (query_def.name, tuple(sorted((filter_values or {}).items())))
        if key not in query_cache:
            query_cache[key] = execute(
                config,
                query_def,
                filename,
                filter_values=filter_values,
                row_cap=config.default_row_cap,
            )
        return query_cache[key]

    if st.session_state.existence_cache is None:
        filename_sources = [s for s in sources.values() if s.filename_column is not None]
        try:
            st.session_state.existence_cache = [
                source.name
                for source in filename_sources
                if check_filename_exists(config, source, filename)
            ]
        except QueryExecutionError as exc:
            st.error(f"Could not check whether the file exists: {exc}")
            st.stop()

    found_in = st.session_state.existence_cache
    if not found_in:
        st.warning(f"'{filename}' was not found in any known source.")
        st.stop()

    st.success(f"Found in: {', '.join(found_in)}")

    render_summary(run_query, config.default_row_cap, sources, queries)
    st.divider()
    render_questions(run_query, config.default_row_cap, sources, queries)


if __name__ == "__main__":
    main()
