# Databricks notebook source
# MAGIC %md
# MAGIC # File Insight App -- smoke test
# MAGIC
# MAGIC Proves two things against real data, under your own Databricks identity,
# MAGIC with no provisioning, no local installs, and no stored tokens:
# MAGIC 1. The Databricks connection works (via this notebook's own session).
# MAGIC 2. The registry, validators, query definitions, existence check, masking,
# MAGIC    and row cap logic hold up against real data.
# MAGIC
# MAGIC Runs queries through the same `SparkExecutor` (`app/db/spark_client.py`)
# MAGIC that `notebooks/demo_app.py` uses -- masking and the row cap are applied
# MAGIC inside the executor, not by this notebook.
# MAGIC
# MAGIC ## Quick steps
# MAGIC 1. Attach this notebook to compute (serverless, or a Unity Catalog-enabled
# MAGIC    cluster on DBR 14+).
# MAGIC 2. Set the **filename** widget at the top of the notebook to a real,
# MAGIC    de-identified filename you expect to find.
# MAGIC 3. **Run All**. The first run just creates the widget and fails fast with
# MAGIC    a reminder to set it -- that's expected, not a bug.
# MAGIC
# MAGIC See `docs/smoke-test.md` for full setup steps and how to read each result.
# MAGIC This notebook does **not** prove service principal auth, App Service, the
# MAGIC Entra header, or the network path from App Service to Databricks -- see
# MAGIC `docs/deploy.md` for those.

# COMMAND ----------

# MAGIC %pip install pydantic==2.13.5

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md ### Filename widget
# MAGIC Fails fast if empty -- expected on the very first run, before you've had
# MAGIC a chance to type into the widget this cell creates.

# COMMAND ----------

dbutils.widgets.text("filename", "", "Filename to test")
filename = dbutils.widgets.get("filename").strip()
if not filename:
    raise ValueError(
        "The 'filename' widget is empty. Set it in the widget bar above "
        "(it was just created if this is the first run) and click 'Run All' again."
    )
print("Testing filename: {0}".format(filename))

# COMMAND ----------

# MAGIC %md ### Locate and import the registry
# MAGIC Looks for `app_src.zip` next to this notebook first (manual upload path),
# MAGIC then an `app/` folder (Git folder path), trying a couple of candidate
# MAGIC directories since notebook-directory detection varies slightly by compute
# MAGIC type. Detects the app package by *content*, not by name, since
# MAGIC Databricks' Workspace Import UI does not reliably preserve a multi-folder
# MAGIC zip's structure or names -- see `docs/smoke-test.md` if this cell fails.

# COMMAND ----------

import os
import sys
import types

_APP_PACKAGE_MARKERS = (
    os.path.join("registry", "__init__.py"),
    os.path.join("sources", "__init__.py"),
    os.path.join("queries", "__init__.py"),
    "masking.py",
    "validation.py",
    os.path.join("db", "executor.py"),
    os.path.join("db", "spark_client.py"),
)


def _looks_like_app_package_dir(directory):
    return all(os.path.exists(os.path.join(directory, marker)) for marker in _APP_PACKAGE_MARKERS)


def _register_as_app_package(directory):
    if "app" not in sys.modules:
        module = types.ModuleType("app")
        module.__path__ = [directory]
        sys.modules["app"] = module


def _candidate_dirs():
    dirs = []
    try:
        dirs.append(os.getcwd())
    except Exception:
        pass
    try:
        ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
        notebook_path = ctx.notebookPath().get()
        dirs.append("/Workspace" + os.path.dirname(notebook_path))
    except Exception:
        pass
    seen = set()
    unique_dirs = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            unique_dirs.append(d)
    return unique_dirs


def _locate_and_register_app_source():
    tried = []
    for directory in _candidate_dirs():
        zip_candidate = os.path.join(directory, "app_src.zip")
        tried.append(zip_candidate)
        if os.path.isfile(zip_candidate):
            sys.path.insert(0, zip_candidate)
            return zip_candidate

        app_dir_candidate = os.path.join(directory, "app")
        tried.append(app_dir_candidate)
        if os.path.isdir(app_dir_candidate) and _looks_like_app_package_dir(app_dir_candidate):
            sys.path.insert(0, directory)
            return app_dir_candidate

        if os.path.isdir(directory):
            for entry in sorted(os.listdir(directory)):
                candidate = os.path.join(directory, entry)
                tried.append(candidate)
                if os.path.isdir(candidate) and _looks_like_app_package_dir(candidate):
                    _register_as_app_package(candidate)
                    return candidate

    raise ImportError(
        "Could not find app_src.zip, an app/ folder, or any folder containing "
        "the expected registry/executor contents next to this notebook. "
        "Tried: {0}. See docs/smoke-test.md.".format(tried)
    )


source_location = _locate_and_register_app_source()
print("Using app source from: {0}".format(source_location))

import pandas as pd

from app.db.spark_client import SparkExecutor, check_filename_exists, describe_columns
from app.masking import effective_sensitive_columns
from app.registry.loader import load_registries
from app.validation import is_valid_filename

if not is_valid_filename(filename):
    raise ValueError(
        "'{0}' does not look like a valid filename (letters, digits, '.', "
        "'_', '-' only, max 255 chars).".format(filename)
    )

# COMMAND ----------

# MAGIC %md ### Helpers
# MAGIC Small, obviously-correct helpers used only in this notebook. The
# MAGIC canonical, unit-tested version of the masking-reference formula lives in
# MAGIC `scripts/smoke_test_lib.py` (tested in `tests/test_smoke_test_lib.py`) --
# MAGIC this notebook can't import that module directly since it isn't part of
# MAGIC `app_src.zip`.

# COMMAND ----------

import time
from datetime import datetime

results = []  # list of dict(check, status, duration_s, note) -- never row data


def record(check_name, status, duration_seconds, note=""):
    results.append(
        {
            "check": check_name,
            "status": status,
            "duration_s": round(duration_seconds, 2),
            "note": note,
        }
    )
    print("[{0}] {1} ({2:.2f}s) {3}".format(status, check_name, duration_seconds, note))


def run_check(check_name, fn):
    start = time.monotonic()
    try:
        note = fn()
        record(check_name, "PASS", time.monotonic() - start, note or "")
    except Exception as exc:
        record(check_name, "FAIL", time.monotonic() - start, str(exc))


def normalize_name(name):
    return name.replace("_", "").lower()


def mask_reference(raw_value):
    if raw_value is None:
        return None
    text = str(raw_value)
    if len(text) <= 4:
        return "*" * len(text)
    return "*" * (len(text) - 4) + text[-4:]


BOGUS_FILENAME = "{0}.smoketest-bogus-9f3a".format(filename)
ROW_CAP = 500

# COMMAND ----------

# MAGIC %md ## Check 1: Registry loads

# COMMAND ----------

sources = {}
queries = {}


def _check_registry_loads():
    global sources, queries
    sources, queries = load_registries()
    return "{0} source(s), {1} query(ies), all validators passed".format(
        len(sources), len(queries)
    )


run_check("Registry loads", _check_registry_loads)

# COMMAND ----------

# MAGIC %md Construct the shared executor now that the registry has loaded --
# MAGIC the same `SparkExecutor` class `notebooks/demo_app.py` uses.

# COMMAND ----------

spark_executor = SparkExecutor(spark, sources)

# COMMAND ----------

# MAGIC %md ## Check 2: Connectivity

# COMMAND ----------


def _check_connectivity():
    global current_user
    row = spark.sql("SELECT current_user() AS user").collect()[0]
    current_user = row["user"]
    return "current_user() = {0}".format(current_user)


current_user = None
run_check("Connectivity", _check_connectivity)

# COMMAND ----------

# MAGIC %md ## Check 3: Sources reachable
# MAGIC Runs `DESCRIBE TABLE IDENTIFIER(:fqn)` for each source (table/column
# MAGIC names are parameter-bound via `IDENTIFIER()`, never string-formatted) and
# MAGIC compares the result to the registry's declared columns.

# COMMAND ----------


def _check_sources_reachable():
    notes = []
    for source in sources.values():
        actual_columns = describe_columns(spark, source.fully_qualified_view)
        declared = {c.name: c.data_type for c in source.columns}

        missing = sorted(set(declared) - set(actual_columns))
        extra = sorted(set(actual_columns) - set(declared))
        type_drift = sorted(
            name
            for name in set(declared) & set(actual_columns)
            if declared[name].lower() != actual_columns[name].lower()
        )

        if source.filename_column and source.filename_column not in actual_columns:
            raise AssertionError(
                "{0}: filename_column '{1}' not found in DESCRIBE TABLE output".format(
                    source.name, source.filename_column
                )
            )

        drift_bits = []
        if missing:
            drift_bits.append("missing: {0}".format(missing))
        if extra:
            drift_bits.append("undeclared: {0}".format(extra))
        if type_drift:
            drift_bits.append("type drift: {0}".format(type_drift))
        notes.append(
            "{0}: {1} column(s){2}".format(
                source.name,
                len(actual_columns),
                " -- DRIFT " + "; ".join(drift_bits) if drift_bits else "",
            )
        )
    return "; ".join(notes)


run_check("Sources reachable", _check_sources_reachable)

# COMMAND ----------

# MAGIC %md ## Check 4: Existence check
# MAGIC Same parameterized-lookup logic as `check_filename_exists` in
# MAGIC `app/db/client.py` (and `app/db/spark_client.py`, used here). Runs for
# MAGIC the real filename (expect matches) and a derived bogus filename (expect
# MAGIC none).

# COMMAND ----------


def _check_existence():
    filename_sources = [s for s in sources.values() if s.filename_column]
    if not filename_sources:
        return "no sources declare a filename_column"

    found_in = [s.name for s in filename_sources if check_filename_exists(spark, s, filename)]
    bogus_hits = [
        s.name for s in filename_sources if check_filename_exists(spark, s, BOGUS_FILENAME)
    ]

    if not found_in:
        raise AssertionError(
            "'{0}' was not found in any of: {1}".format(
                filename, [s.name for s in filename_sources]
            )
        )
    if bogus_hits:
        raise AssertionError(
            "bogus filename unexpectedly matched in: {0}".format(bogus_hits)
        )
    return "found in {0}; bogus filename matched none (checked {1} source(s))".format(
        found_in, len(filename_sources)
    )


run_check("Existence check", _check_existence)

# COMMAND ----------

# MAGIC %md ## Check 5: Summary queries (run_on_load)
# MAGIC Runs through `spark_executor.execute()` -- masking and the row cap are
# MAGIC already applied to the returned result.

# COMMAND ----------

summary_results = {}  # query name -> QueryResult (already masked, capped)


def _check_summary_queries():
    notes = []
    for query in queries.values():
        if not query.run_on_load:
            continue
        result = spark_executor.execute(query, filename, row_cap=ROW_CAP)
        summary_results[query.name] = result
        notes.append("{0}: {1} row(s)".format(query.name, len(result.dataframe)))
    if not notes:
        return "no run_on_load queries defined"
    return "; ".join(notes)


run_check("Summary queries", _check_summary_queries)

# COMMAND ----------

# MAGIC %md ## Check 6: Drill-down queries
# MAGIC Each runs twice through `spark_executor.execute()`: once with every
# MAGIC optional filter unset (bound as SQL `NULL`), and once with a sampled
# MAGIC real value for each filter.

# COMMAND ----------

drilldown_results = {}  # (query name, "unset"/"filtered") -> QueryResult
drilldown_filter_values = {}  # (query name, "unset"/"filtered") -> filter_values used


def _sample_parameter_value(source, parameter):
    if parameter.allowed_values:
        return parameter.allowed_values[0]
    matching = [c.name for c in source.columns if normalize_name(c.name) == normalize_name(parameter.name)]
    if not matching:
        return None
    column = matching[0]
    rows = spark.sql(
        "SELECT IDENTIFIER(:col) AS sampled_value FROM IDENTIFIER(:fqn) "
        "WHERE IDENTIFIER(:filename_col) = :filename AND IDENTIFIER(:col) IS NOT NULL "
        "LIMIT 1",
        args={
            "col": column,
            "fqn": source.fully_qualified_view,
            "filename_col": source.filename_column,
            "filename": filename,
        },
    ).collect()
    return rows[0]["sampled_value"] if rows else None


def _check_drilldown_queries():
    notes = []
    for query in queries.values():
        if query.run_on_load:
            continue
        source = sources[query.source]

        result_unset = spark_executor.execute(query, filename, filter_values={}, row_cap=ROW_CAP)
        drilldown_results[(query.name, "unset")] = result_unset
        drilldown_filter_values[(query.name, "unset")] = {}
        notes.append(
            "{0} (filters unset): {1} row(s)".format(query.name, len(result_unset.dataframe))
        )

        sampled = {p.name: _sample_parameter_value(source, p) for p in query.parameters}
        result_filtered = spark_executor.execute(
            query, filename, filter_values=sampled, row_cap=ROW_CAP
        )
        drilldown_results[(query.name, "filtered")] = result_filtered
        drilldown_filter_values[(query.name, "filtered")] = sampled
        notes.append(
            "{0} (filters={1}): {2} row(s)".format(
                query.name, sampled, len(result_filtered.dataframe)
            )
        )
    if not notes:
        return "no drill-down queries defined"
    return "; ".join(notes)


run_check("Drill-down queries", _check_drilldown_queries)

# COMMAND ----------

# MAGIC %md ## Check 7: Masking
# MAGIC The results captured above are already masked (the executor does that).
# MAGIC To verify masking independently, this check re-fetches each query's raw
# MAGIC (unmasked) data directly via `spark.sql` -- bypassing the executor on
# MAGIC purpose, since that's the only way to get something to compare against --
# MAGIC and checks it against an independent reimplementation of the masking
# MAGIC formula, not by calling `app.masking` a second time.

# COMMAND ----------

masked_samples = {}  # label -> masked pandas.DataFrame (sample only, <=5 rows)


def _fetch_raw(query_def, filter_values):
    args = {"filename": filename}
    for parameter in query_def.parameters:
        args[parameter.name] = (filter_values or {}).get(parameter.name)
    pdf = spark.sql(query_def.sql, args=args).limit(ROW_CAP + 1).toPandas()
    return pdf.head(ROW_CAP)


def _check_masking():
    notes = []
    labeled_results = []  # (label, query, result, filter_values_used)
    for query_name, result in summary_results.items():
        labeled_results.append((query_name, queries[query_name], result, {}))
    for (query_name, variant), result in drilldown_results.items():
        label = "{0} ({1})".format(query_name, variant)
        filter_values = drilldown_filter_values[(query_name, variant)]
        labeled_results.append((label, queries[query_name], result, filter_values))

    for label, query, result, filter_values in labeled_results:
        source = sources[query.source]
        sensitive = effective_sensitive_columns(query, source)
        masked_samples[label] = result.dataframe.head(5)

        if not sensitive:
            notes.append("{0}: no sensitive columns declared".format(label))
            continue

        raw_pdf = _fetch_raw(query, filter_values)
        for column in sensitive & set(raw_pdf.columns):
            for raw, masked in zip(raw_pdf[column], result.dataframe[column]):
                expected = mask_reference(raw)
                if masked != expected:
                    raise AssertionError(
                        "{0}.{1}: masked value did not match the expected "
                        "masking formula".format(label, column)
                    )
        notes.append("{0}: masked columns {1} verified".format(label, sorted(sensitive)))
    return "; ".join(notes)


run_check("Masking", _check_masking)

# COMMAND ----------

# MAGIC %md ### Masked sample (<= 5 rows per result)
# MAGIC This is the only cell that displays row data, and it's already masked.
# MAGIC Not part of the summary report below -- don't paste this cell's output
# MAGIC anywhere sensitive data shouldn't go, even though it's masked.

# COMMAND ----------

for label, masked_pdf in masked_samples.items():
    print("--- {0} ---".format(label))
    display(masked_pdf)

# COMMAND ----------

# MAGIC %md ## Check 8: Row cap
# MAGIC First proves the cap+1 truncation-detection arithmetic itself against a
# MAGIC synthetic relation with a known row count (independent of how much real
# MAGIC data exists today), then reports what `spark_executor` sees on a real
# MAGIC registry query.

# COMMAND ----------


def _fetch_with_cap(df, cap):
    rows = df.limit(cap + 1).collect()
    hit = len(rows) > cap
    return rows[:cap], hit


def _check_row_cap():
    synthetic = spark.sql("SELECT * FROM (VALUES (1), (2), (3)) AS t(x)")

    rows, hit = _fetch_with_cap(synthetic, cap=2)
    if not (hit and len(rows) == 2):
        raise AssertionError("expected cap=2 against 3 rows to report a hit with 2 rows back")

    rows, hit = _fetch_with_cap(synthetic, cap=5)
    if hit or len(rows) != 3:
        raise AssertionError("expected cap=5 against 3 rows to report no hit with 3 rows back")

    real_query = next((q for q in queries.values() if q.run_on_load), None)
    if real_query is None:
        return "synthetic cases passed; no run_on_load query to sample against ROW_CAP"
    real_result = spark_executor.execute(real_query, filename, row_cap=ROW_CAP)
    return "synthetic cases passed; '{0}' against ROW_CAP={1}: hit={2}".format(
        real_query.name, ROW_CAP, real_result.row_cap_hit
    )


run_check("Row cap", _check_row_cap)

# COMMAND ----------

# MAGIC %md ## Summary
# MAGIC PASS/FAIL, counts, durations, column names, and error messages only --
# MAGIC safe to paste anywhere.

# COMMAND ----------

report_df = pd.DataFrame(results, columns=["check", "status", "duration_s", "note"])
overall = "FAIL" if (report_df["status"] == "FAIL").any() else "PASS"
print("Overall: {0}  (run at {1}, user={2})".format(overall, datetime.now().isoformat(), current_user))
display(report_df)
