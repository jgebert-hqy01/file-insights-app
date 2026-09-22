# Databricks notebook source
# MAGIC %md
# MAGIC # File Insight App -- demo
# MAGIC
# MAGIC A thin presentation layer over the same registry the real app uses --
# MAGIC enter a filename, see which sources have it, the summary, and one
# MAGIC drill-down question, all under your own Databricks identity. No
# MAGIC provisioning, no stored tokens.
# MAGIC
# MAGIC ## Quick steps
# MAGIC 1. Attach to compute (serverless, or a Unity Catalog-enabled cluster on
# MAGIC    DBR 14+).
# MAGIC 2. **Run All** once to create the widgets.
# MAGIC 3. Set **filename**, pick a **category** and **question**, fill in any
# MAGIC    filter widgets that appear, then **Run All** again.
# MAGIC
# MAGIC See `docs/demo.md` for upload steps and what this does and doesn't
# MAGIC prove.

# COMMAND ----------

# MAGIC %pip install pydantic==2.13.5

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md ### Locate and import the registry
# MAGIC Same zip bundle and detection logic as `notebooks/smoke_test.py` -- see
# MAGIC `docs/smoke-test.md` if this cell fails to find anything.

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

from datetime import datetime

from app.db.spark_client import SparkExecutor, check_filename_exists
from app.registry.loader import load_registries
from app.registry.models import ParameterControl
from app.validation import is_valid_filename

ROW_CAP = 500

# COMMAND ----------

# MAGIC %md ### Load the registry and build the executor

# COMMAND ----------

sources, queries = load_registries()
spark_executor = SparkExecutor(spark, sources)
print("{0} source(s), {1} query(ies) loaded.".format(len(sources), len(queries)))

# COMMAND ----------

# MAGIC %md ### Widgets
# MAGIC `category` and `question` cascade: pick a category, run this cell (or
# MAGIC Run All), and the question dropdown's choices narrow to match. Filter
# MAGIC widgets are created for every parameter across every question up front
# MAGIC (Databricks widgets can't be created/removed dynamically mid-run) --
# MAGIC only the ones belonging to your chosen question are actually read.

# COMMAND ----------

dbutils.widgets.text("filename", "", "Filename to test")

drilldown_queries = [q for q in queries.values() if not q.run_on_load]
if not drilldown_queries:
    raise ValueError("No drill-down questions are defined yet.")

categories = sorted({q.category for q in drilldown_queries})
dbutils.widgets.dropdown("category", categories[0], categories, "Category")
category = dbutils.widgets.get("category")

titles_in_category = sorted(q.title for q in drilldown_queries if q.category == category)
dbutils.widgets.dropdown("question", titles_in_category[0], titles_in_category, "Question")
question_title = dbutils.widgets.get("question")

chosen_query = next(
    q for q in drilldown_queries if q.category == category and q.title == question_title
)

all_parameters = {}
for q in drilldown_queries:
    for p in q.parameters:
        all_parameters[p.name] = p

for parameter in sorted(all_parameters.values(), key=lambda p: p.name):
    dbutils.widgets.text("filter_{0}".format(parameter.name), "", parameter.label)


def _read_filter_value(parameter):
    if parameter.control != ParameterControl.NUMBER:
        raise NotImplementedError(
            "Widget control '{0}' has no renderer yet in this notebook.".format(
                parameter.control.value
            )
        )
    raw = dbutils.widgets.get("filter_{0}".format(parameter.name)).strip()
    return int(raw) if raw else None


filter_values = {p.name: _read_filter_value(p) for p in chosen_query.parameters}

filename = dbutils.widgets.get("filename").strip()
if not filename:
    raise ValueError("Set the 'filename' widget above and Run All again.")
if not is_valid_filename(filename):
    raise ValueError(
        "'{0}' does not look like a valid filename (letters, digits, '.', "
        "'_', '-' only, max 255 chars).".format(filename)
    )
print("filename={0} category={1} question={2!r} filters={3}".format(
    filename, category, question_title, filter_values
))

# COMMAND ----------

# MAGIC %md ## Existence check

# COMMAND ----------

filename_sources = [s for s in sources.values() if s.filename_column]
found_in = [s.name for s in filename_sources if check_filename_exists(spark, s, filename)]
if not found_in:
    raise ValueError("'{0}' was not found in any known source.".format(filename))
displayHTML("<p><strong>Found in:</strong> {0}</p>".format(", ".join(found_in)))

# COMMAND ----------

# MAGIC %md ## Summary

# COMMAND ----------


def _render_footer(query, result):
    ran_at_label = datetime.fromtimestamp(result.ran_at).strftime("%Y-%m-%d %H:%M:%S")
    note = "Produced by <code>{0}</code> at {1} ({2:.2f}s)".format(
        query.name, ran_at_label, result.latency_seconds
    )
    if result.row_cap_hit:
        note += " -- showing the first {0} rows".format(ROW_CAP)
    displayHTML("<p><em>{0}</em></p>".format(note))


for query in queries.values():
    if not query.run_on_load:
        continue
    result = spark_executor.execute(query, filename, row_cap=ROW_CAP)
    displayHTML("<h4>{0}</h4><p>{1}</p>".format(query.title, query.description))
    display(result.dataframe)
    _render_footer(query, result)

# COMMAND ----------

# MAGIC %md ## Your question

# COMMAND ----------

result = spark_executor.execute(chosen_query, filename, filter_values=filter_values, row_cap=ROW_CAP)
displayHTML("<h4>{0}</h4><p>{1}</p>".format(chosen_query.title, chosen_query.description))
display(result.dataframe)
_render_footer(chosen_query, result)
