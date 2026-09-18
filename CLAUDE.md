# File Insight App

A Streamlit app for HealthEquity teammates: enter a filename, get a summary and a
menu of predefined drill-down questions, all backed by static, parameterized SQL
against a Databricks SQL Warehouse. Claude is a development tool for this
project, not a runtime component -- the deployed app never calls an LLM.

## Conventions

- **Parameterized SQL only.** Every value bound to a query -- `:filename` and every
  filter -- goes through `databricks.sql.parameters.native` typed parameter
  objects (see `app/db/client.py`). Never build SQL with f-strings, `.format()`,
  or concatenation. An unset optional filter binds as `VoidParameter(value=None)`,
  never as a change to the SQL text.
- **Static, allowlisted queries only.** All SQL lives in `QueryDefinition`s under
  `app/queries/`. Nothing at runtime generates or modifies SQL.
- **Read-only, enforced twice.** `app/registry/models.py` defines the single
  `is_read_only_sql()` check (SQL must start with `SELECT`/`WITH`, and must not
  contain a DDL/DML keyword) -- once at `QueryDefinition` construction time (fails
  fast, in CI) and again in `app/db/client.py` immediately before execution
  (defends against a definition being mutated after validation). Both call sites
  use the same function; don't reintroduce a second copy of the regex.
- **Masking is on by default.** `SourceDefinition.sensitive_columns` plus a
  query's `additional_sensitive_columns`, minus its `unmasked_columns`, get
  masked to the last 4 characters by `app/masking.py`. A query only shows a
  sensitive column unmasked if `unmasked_columns` says so explicitly -- get that
  reviewed before adding it.
- **Registries auto-discover.** Anything you add under `app/sources/` or
  `app/queries/` is picked up automatically by `app/registry/loader.py`. There is
  no central list to edit, and no UI file to touch when adding a query that reuses
  an existing filter control type.
- **No secrets in the repo.** `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH`, and auth
  values come from environment variables. `.env.example` holds variable names and
  placeholders only. Never a Databricks personal access token, in this app or
  anywhere else -- local dev uses OAuth U2M (interactive browser sign-in, no
  secret); production uses OAuth M2M service principal or Azure managed identity.
- **Python version:** target 3.11+ (CI and App Service both pin 3.11). Keep
  syntax 3.9-compatible where practical (avoid `X | Y` union syntax, `match`
  statements) since local dev on this machine currently only has Python 3.9
  available.

## Adding a source

1. Get the fully qualified view name from Josh.
2. Run `DESCRIBE TABLE` (or `DESCRIBE TABLE EXTENDED` to also confirm view vs.
   table) and show Josh the columns; he confirms the filename column and the
   sensitive columns.
3. Create a `SourceDefinition` in the right domain file under `app/sources/`
   (create the file if the domain is new).
4. Run the registry tests. Confirm the existence check now includes this source.
5. Summarize what was added and open a pull request.

## Adding a query

1. Josh describes the question in plain English and names the source(s) it
   uses. If a source is missing, run **Adding a source** first.
2. Draft the SQL with `:filename` and named parameters for every filter. Show it
   to Josh before writing the definition.
3. Create a `QueryDefinition` in the right domain file under `app/queries/` with
   complete metadata. Decide `run_on_load` with Josh.
4. Run the registry tests. Run the query against a test filename and show Josh
   the masked output.
5. Summarize what was added and open a pull request.

Note: if a filter needs a UI control type not yet implemented in
`app/ui/questions.py` (currently only `NUMBER` is implemented), adding that
renderer is a one-time exception to "no UI edits" -- every later query that reuses
the same control type needs none.
