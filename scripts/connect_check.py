"""CLI diagnostic: proves this machine's Databricks connection works,
under whichever DATABRICKS_AUTH_MODE is configured (pat, oauth-u2m, or
oauth-m2m), against real data through the real SQL connector.

Run this yourself, in your own terminal. It never asks for or prints a
token value, and it never tries to route around a failure it finds
(network policy, missing grant, cold warehouse, etc.) -- it only reports
it. See docs/local-connection.md for setup steps.

Usage:
    python scripts/connect_check.py --filename <filename>
"""
import argparse
import os
import re
import sys
import time

# `python scripts/connect_check.py` puts this file's own directory
# (scripts/) on sys.path[0], not the repo root -- see the identical fix
# already applied to scripts/smoke_test.py, app/main.py, and bot/app.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import AuthMode, load_config
from app.db.client import SqlConnectorExecutor, check_filename_exists
from app.registry.loader import load_registries
from app.registry.models import QueryDefinition, SourceDefinition
from app.validation import is_valid_filename
from scripts.smoke_test_lib import CheckResult, format_report, overall_status

ROW_CAP = 500

# Not a real source -- only satisfies the executor's masking lookup for the
# connectivity probe below.
_DIAGNOSTIC_SOURCE = SourceDefinition(
    name="__connect_check__",
    fully_qualified_view="connect_check.connect_check.connect_check",
    filename_column=None,
    columns=[],
    sensitive_columns=[],
    description="Not a real source -- only satisfies the executor's masking lookup.",
)
# A tautological :filename bind, used only to satisfy the QueryDefinition
# contract for a plain connectivity probe -- not a registered source/query.
_CURRENT_USER_QUERY = QueryDefinition(
    name="connect_check_current_user",
    title="Current user",
    description="connect_check.py connectivity probe.",
    category="Diagnostics",
    source="__connect_check__",
    sql="SELECT current_user() AS user_name, :filename AS probe_filename",
)

_WAREHOUSE_ID_PATTERN = re.compile(r"/warehouses/([A-Za-z0-9]+)")


def _warehouse_id_from_http_path(http_path):
    match = _WAREHOUSE_ID_PATTERN.search(http_path)
    return match.group(1) if match else "<could not parse from DATABRICKS_HTTP_PATH>"


def _run(results, name, fn):
    start = time.monotonic()
    try:
        note = fn()
        results.append(CheckResult(name, "PASS", time.monotonic() - start, note or ""))
    except Exception as exc:
        results.append(CheckResult(name, "FAIL", time.monotonic() - start, str(exc)))
    print(format_report(results[-1:]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--filename", required=True, help="A real, de-identified filename to test against."
    )
    args = parser.parse_args()

    if not is_valid_filename(args.filename):
        raise SystemExit("'{0}' does not look like a valid filename.".format(args.filename))

    results = []
    state = {"config": None, "sources": {}, "queries": {}, "executor": None, "touched_views": set()}

    def check_env_vars():
        config = load_config()
        state["config"] = config
        names = ["DATABRICKS_HOST", "DATABRICKS_HTTP_PATH"]
        if config.auth_mode is AuthMode.PAT:
            names.append("DATABRICKS_TOKEN")
        elif config.auth_mode is AuthMode.SERVICE_PRINCIPAL:
            names.extend(["DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"])
        return "mode={0}; present: {1}".format(config.auth_mode.value, ", ".join(names))

    _run(results, "Required env vars present", check_env_vars)

    if state["config"] is None:
        print()
        print(format_report(results))
        print("Overall: FAIL")
        return 1

    config = state["config"]

    def check_connectivity():
        executor = SqlConnectorExecutor(config, {"__connect_check__": _DIAGNOSTIC_SOURCE})
        result = executor.execute(_CURRENT_USER_QUERY, filename="connect-check")
        return "current_user() = {0}".format(result.dataframe.iloc[0]["user_name"])

    _run(results, "Connectivity (mode={0})".format(config.auth_mode.value), check_connectivity)

    def check_warehouse_state():
        executor = SqlConnectorExecutor(config, {"__connect_check__": _DIAGNOSTIC_SOURCE})
        probe_start = time.monotonic()
        executor.execute(_CURRENT_USER_QUERY, filename="connect-check")
        latency = time.monotonic() - probe_start
        inferred = "already Running" if latency < 5 else "was slow to respond (possibly cold-starting)"
        return "inferred from a {0:.2f}s round trip: warehouse {1} (not a direct state API call)".format(
            latency, inferred
        )

    _run(results, "Warehouse reachable", check_warehouse_state)

    def check_registry_loads():
        sources, queries = load_registries()
        state["sources"], state["queries"] = sources, queries
        state["executor"] = SqlConnectorExecutor(config, sources)
        return "{0} source(s), {1} query(ies)".format(len(sources), len(queries))

    _run(results, "Registry loads", check_registry_loads)

    def check_existence():
        filename_sources = [s for s in state["sources"].values() if s.filename_column]
        if not filename_sources:
            return "no sources declare a filename_column"
        found_in = []
        for source in filename_sources:
            if check_filename_exists(config, source, args.filename):
                found_in.append(source.name)
                state["touched_views"].add(source.fully_qualified_view)
        if not found_in:
            raise AssertionError("'{0}' was not found in any source".format(args.filename))
        return "found in {0}".format(found_in)

    _run(results, "Existence check", check_existence)

    def check_summary_queries():
        notes = []
        for query in state["queries"].values():
            if not query.run_on_load:
                continue
            result = state["executor"].execute(query, args.filename, row_cap=ROW_CAP)
            state["touched_views"].add(state["sources"][query.source].fully_qualified_view)
            notes.append("{0}: {1} row(s)".format(query.name, len(result.dataframe)))
        if not notes:
            return "no run_on_load queries defined"
        return "; ".join(notes)

    _run(results, "Summary queries", check_summary_queries)

    def check_drilldown_with_unset_filter():
        candidate = next(
            (q for q in state["queries"].values() if not q.run_on_load and q.parameters), None
        )
        if candidate is None:
            return "no drill-down query with an optional filter parameter exists to test"
        filter_values = {p.name: None for p in candidate.parameters}
        result = state["executor"].execute(
            candidate, args.filename, filter_values=filter_values, row_cap=ROW_CAP
        )
        state["touched_views"].add(state["sources"][candidate.source].fully_qualified_view)
        return "{0} (filters unset -> VoidParameter): {1} row(s)".format(
            candidate.name, len(result.dataframe)
        )

    _run(results, "Drill-down query (optional filter unset)", check_drilldown_with_unset_filter)

    print()
    print(format_report(results))
    print("Overall: {0}".format(overall_status(results)))

    print()
    print("What the service principal will need to reproduce this:")
    print("  Workspace host: {0}".format(config.databricks_host))
    print("  Warehouse ID: {0}".format(_warehouse_id_from_http_path(config.databricks_http_path)))
    print("  View(s) touched: {0}".format(", ".join(sorted(state["touched_views"])) or "(none)"))
    print("  Grants needed: SELECT on those view(s); CAN USE on the warehouse.")

    return 0 if overall_status(results) == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
