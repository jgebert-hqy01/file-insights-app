"""CLI smoke test: the same checks as notebooks/smoke_test.py, but running
through the real app/db/client.py with OAuth user-to-machine auth, for
environments where the full stack imports (e.g. GitHub Codespaces). No
tokens. Since it reuses the real SqlConnectorExecutor/check_filename_exists
code paths directly, this is much shorter than the notebook, which had to
reimplement the equivalent logic with spark.sql.

Usage:
    export DATABRICKS_HOST=<workspace-host>.azuredatabricks.net
    export DATABRICKS_WAREHOUSE_ID=<warehouse-id>
    python scripts/smoke_test.py <filename>
"""
import os
import sys
import time

from app.config import AppConfig, AuthMode
from app.db.client import SqlConnectorExecutor, check_filename_exists
from app.masking import effective_sensitive_columns
from app.registry.loader import load_registries
from app.registry.models import QueryDefinition, SourceDefinition
from app.validation import is_valid_filename
from scripts.smoke_test_lib import CheckResult, bogus_filename_for, format_report, overall_status

ROW_CAP = 500

# A tautological :filename bind, used only to satisfy the QueryDefinition
# contract for a plain connectivity probe -- not a registered source/query.
_CURRENT_USER_QUERY = QueryDefinition(
    name="smoke_test_current_user",
    title="Current user",
    description="Smoke test connectivity probe.",
    category="Smoke test",
    source="__smoke_test__",
    sql="SELECT current_user() AS user_name, :filename AS smoke_test_filename",
)
_SMOKE_TEST_SOURCE = SourceDefinition(
    name="__smoke_test__",
    fully_qualified_view="smoke_test.smoke_test.smoke_test",
    filename_column=None,
    columns=[],
    sensitive_columns=[],
    description="Not a real source -- only satisfies the executor's masking lookup.",
)


def _require_env(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit("Required environment variable '{0}' is not set.".format(name))
    return value


def _build_config():
    host = _require_env("DATABRICKS_HOST")
    warehouse_id = _require_env("DATABRICKS_WAREHOUSE_ID")
    return AppConfig(
        databricks_host=host,
        databricks_http_path="/sql/1.0/warehouses/{0}".format(warehouse_id),
        auth_mode=AuthMode.LOCAL_INTERACTIVE,
    )


def _run(results, name, fn):
    start = time.monotonic()
    try:
        note = fn()
        results.append(CheckResult(name, "PASS", time.monotonic() - start, note or ""))
    except Exception as exc:
        results.append(CheckResult(name, "FAIL", time.monotonic() - start, str(exc)))
    print(format_report(results[-1:]))


def _looks_properly_masked(value):
    """Structural check: every character except the last 4 must be '*'."""
    text = str(value)
    if len(text) <= 4:
        return text == "*" * len(text)
    return text[:-4] == "*" * (len(text) - 4)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/smoke_test.py <filename>")
    filename = sys.argv[1]
    if not is_valid_filename(filename):
        raise SystemExit("'{0}' does not look like a valid filename.".format(filename))
    bogus_filename = bogus_filename_for(filename)

    config = _build_config()
    results = []
    state = {"sources": {}, "queries": {}, "executor": None}

    def check_registry_loads():
        sources, queries = load_registries()
        state["sources"], state["queries"] = sources, queries
        state["executor"] = SqlConnectorExecutor(
            config, {**sources, "__smoke_test__": _SMOKE_TEST_SOURCE}
        )
        return "{0} source(s), {1} query(ies), all validators passed".format(
            len(sources), len(queries)
        )

    _run(results, "Registry loads", check_registry_loads)

    def check_connectivity():
        result = state["executor"].execute(_CURRENT_USER_QUERY, filename="smoke-test")
        return "current_user() = {0}".format(result.dataframe.iloc[0]["user_name"])

    _run(results, "Connectivity", check_connectivity)

    def check_existence():
        filename_sources = [s for s in state["sources"].values() if s.filename_column]
        if not filename_sources:
            return "no sources declare a filename_column"
        found_in = [s.name for s in filename_sources if check_filename_exists(config, s, filename)]
        bogus_hits = [
            s.name for s in filename_sources if check_filename_exists(config, s, bogus_filename)
        ]
        if not found_in:
            raise AssertionError("'{0}' was not found in any source".format(filename))
        if bogus_hits:
            raise AssertionError("bogus filename unexpectedly matched in: {0}".format(bogus_hits))
        return "found in {0}; bogus filename matched none".format(found_in)

    _run(results, "Existence check", check_existence)

    def check_summary_and_drilldown():
        notes = []
        for query in state["queries"].values():
            filter_values = {p.name: None for p in query.parameters}
            result = state["executor"].execute(
                query, filename, filter_values=filter_values, row_cap=ROW_CAP
            )
            notes.append("{0}: {1} row(s)".format(query.name, len(result.dataframe)))
        return "; ".join(notes)

    _run(results, "Summary and drill-down queries (filters unset)", check_summary_and_drilldown)

    def check_masking():
        notes = []
        for query in state["queries"].values():
            source = state["sources"][query.source]
            result = state["executor"].execute(query, filename, row_cap=ROW_CAP)
            sensitive = effective_sensitive_columns(query, source)
            if not sensitive:
                notes.append("{0}: no sensitive columns declared".format(query.name))
                continue
            for column in sensitive & set(result.dataframe.columns):
                if not result.dataframe[column].map(_looks_properly_masked).all():
                    raise AssertionError(
                        "{0}.{1}: a value did not look properly masked".format(
                            query.name, column
                        )
                    )
            notes.append("{0}: masked columns {1} look correctly masked".format(
                query.name, sorted(sensitive)
            ))
        return "; ".join(notes)

    _run(results, "Masking", check_masking)

    def check_row_cap():
        notes = []
        for query in state["queries"].values():
            tiny_cap_result = state["executor"].execute(query, filename, row_cap=1)
            notes.append("{0}: row_cap_hit={1}".format(query.name, tiny_cap_result.row_cap_hit))
        return "; ".join(notes)

    _run(results, "Row cap", check_row_cap)

    print()
    print(format_report(results))
    print("Overall: {0}".format(overall_status(results)))
    return 0 if overall_status(results) == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
