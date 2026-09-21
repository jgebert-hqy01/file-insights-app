# Smoke test

Proves, against real data, under your own Databricks identity, with no
provisioning, no local installs, and no stored tokens:

1. The Databricks connection works.
2. The registry, validators, query definitions, existence check, masking,
   and row cap logic hold up against real data.

It does **not** require App Service, a service principal, or Key Vault to
exist yet -- see "What this does not prove" at the end.

## Steps

The notebook needs the registry code (`app/registry`, `app/sources`,
`app/queries`, `app/masking.py`, `app/validation.py`) available in the
workspace. Since this app isn't in a Databricks Git folder yet, upload it
directly:

### 1. Build the bundle

On a machine with this repo checked out and Python 3.9+ available, run:
```
python scripts/make_smoke_bundle.py
```
This writes `dist/app_src.zip` -- a zip of just the registry-side code
above (no Streamlit, no SQL connector, no `app/db` or `app/ui`).

### 2. Upload the bundle and the notebook via Workspace → Import

1. In the Databricks UI, click **Workspace** in the sidebar, navigate to
   (or create) a folder for this, e.g. your user folder.
2. Click the kebab menu (`...`) on that folder and choose **Import**.
3. In the Import dialog, choose **File**, and upload `dist/app_src.zip`.
4. Import again, this time uploading `notebooks/smoke_test.py` from the
   repo. Since it starts with the `# Databricks notebook source` header,
   Databricks recognizes it as a notebook (source format) and opens it as
   one, not as a plain text file.

**Known issue:** Databricks' Workspace Import UI does not reliably preserve
a multi-folder zip's structure. Observed behavior (2026-09-21): importing
`app_src.zip` as a File produced a folder named after the zip (`app_src`)
containing only some of the flattened top-level files -- nested folders
(`registry/`, `sources/`, `queries/`) and even `validation.py` were
silently dropped. `notebooks/smoke_test.py` detects the app package by
*content* (looking for `registry/__init__.py`, `sources/__init__.py`,
`queries/__init__.py`, `masking.py`, `validation.py` inside a folder,
whatever that folder is actually named) specifically to tolerate this, but
it still needs those files to actually be there. If the import drops
files, finish the structure by hand:

1. Inside the resulting folder (e.g. `app_src`), use the kebab menu →
   **Create → Folder** to create `registry`, `sources`, and `queries`.
2. For each, click into it and use kebab menu → **Import → File** to
   upload the matching files from your local checkout:
   - `registry/`: `app/registry/__init__.py`, `app/registry/loader.py`, `app/registry/models.py`
   - `sources/`: `app/sources/__init__.py`, `app/sources/correlation.py`
   - `queries/`: `app/queries/__init__.py`, `app/queries/correlation.py`
3. Back at the folder root, re-import any flat file that got dropped (in
   the observed case, `app/validation.py`).
4. Re-run the notebook -- the "Locate and import the registry" cell prints
   which directory it used; confirm it's the one you just finished.

**Alternative, for later:** once Databricks is linked to GitHub (**Settings
→ Linked accounts → Git integration**), you can instead create a **Git
folder** from this repo's URL and open `notebooks/smoke_test.py` directly
from there. Git folders correctly preserve the whole file tree, so this
sidesteps the zip-import issue entirely -- skip building the bundle; the
notebook falls back to importing directly from the real `app/` folder in
the Git folder checkout.

### 3. Open the notebook and attach compute

Open the `smoke_test` notebook and attach it to compute: serverless, or a
Unity Catalog-enabled cluster on Databricks Runtime 14 or later.

### 4. Set the filename widget and Run All

Click **Run All**. On the very first run, the notebook will fail fast with
a message reminding you to set the **filename** widget -- that's expected,
not a bug, since the widget didn't exist yet for you to type into. Set it
at the top of the notebook to a real, de-identified filename you expect to
find, then **Run All** again.

### 5. How to read the report

The final cell shows a table: `check`, `status`, `duration_s`, `note`. It
never contains row data -- safe to paste anywhere. The one cell that does
show data (already masked, at most 5 rows per query) is clearly labeled and
sits just before the "Row cap" check, separate from the final report.

| Check | What a PASS proves |
| --- | --- |
| Registry loads | Every `SourceDefinition`/`QueryDefinition` in the repo validates: read-only SQL, `:filename` bound, every parameter declared and used, sources reference real sources. |
| Connectivity | Your Databricks identity can run a query through this notebook's session -- the connection itself works. |
| Sources reachable | Every registered source's `fully_qualified_view` exists and is queryable, and its declared columns match what's actually there. |
| Existence check | The parameterized lookup used by the real app finds the filename where it exists, and correctly finds nothing for a filename that doesn't exist. |
| Summary queries | Every `run_on_load` query runs for your filename and returns rows. |
| Drill-down queries | Every other query runs both with filters unset (bound as SQL `NULL`) and with a real sampled filter value. |
| Masking | `app/masking.py`'s output matches an independently-computed expected masking, for every sensitive column in every result. |
| Row cap | The cap+1 truncation-detection logic correctly identifies both a hit and a non-hit against a controlled synthetic case, then reports what it sees on real data. |

Likely FAILs and what they mean:

- **Permission denied on the view/table** -- your identity doesn't have
  `SELECT` on that Unity Catalog object. Ask whoever administers it.
- **View/table not found** -- either a typo in `fully_qualified_view`, or
  the object was renamed/dropped since the `SourceDefinition` was written.
- **Column drift reported by "Sources reachable"** -- the source's real
  schema has changed since `DESCRIBE TABLE` was last run against it. Update
  the `SourceDefinition`'s `columns`.
- **Parameter binding error (`UNBOUND_SQL_PARAMETER` or similar)** -- a
  query's SQL references a `:param` that isn't declared on the
  `QueryDefinition`, or vice versa. The registry validators are supposed to
  catch this at load time; if it surfaces here instead, it's worth a bug
  report.
- **Empty result for the filename ("Existence check" fails to find it)** --
  either the filename genuinely isn't in any registered source, or it's in
  a source that hasn't been registered yet.

### What this does not prove

This notebook runs under **your own identity**, using the notebook's own
Spark session -- not the app's actual runtime path. It does not prove:

- The production **service principal**'s OAuth M2M authentication works.
- **App Service** itself runs correctly.
- The **Entra ID header** (`X-MS-CLIENT-PRINCIPAL-NAME`) is populated
  correctly in production.
- The **network path** from App Service to the Databricks SQL Warehouse
  (VNet integration or IP allowlist).

See [docs/deploy.md](deploy.md) for all of the above.
