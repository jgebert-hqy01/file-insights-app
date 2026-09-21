# File Insight App

A Streamlit app for HealthEquity teammates: enter a filename, see a summary of
what's known about it, and drill into a menu of predefined questions -- all
backed by static, parameterized SQL against a Databricks SQL Warehouse.

This is a growing tool. New tables and questions get added one at a time via
the checklists in [CLAUDE.md](CLAUDE.md); the underlying design (see
"Architecture" below) is meant to make each addition a small, contained
change.

## Security posture

- Every SQL statement is static and lives in a `QueryDefinition` under
  `app/queries/` -- nothing at runtime generates or modifies SQL, and there is
  no free-text query input.
- Every value bound to a query (the filename, every filter) is a native,
  typed parameter -- never string-interpolated.
- Every statement is checked read-only (`SELECT`/`WITH` only, no DDL/DML)
  both when the query is defined and again immediately before it runs.
- Sensitive columns are masked to their last 4 characters by default.
- No personal access tokens, anywhere. Local dev uses OAuth U2M (interactive
  browser sign-in); production uses an OAuth M2M service principal or Azure
  managed identity.
- The deployed app never calls an LLM or any AI API.

## Architecture

```
app/
  main.py            Streamlit entry point
  config.py          env var loading (no secret defaults)
  auth.py            signed-in user from the App Service auth header
  registry/          SourceDefinition / QueryDefinition models + auto-discovery loader
  sources/           one SourceDefinition per table/view, grouped by domain
  queries/           one QueryDefinition per question, grouped by domain
  db/client.py       Databricks connection, execution, read-only enforcement
  masking.py         sensitive-column masking
  ui/                summary, question menu, and shared rendering
tests/               registry completeness, masking, and mocked-client tests
```

Adding a table or a question is meant to require touching only one file
under `sources/`/`queries/` plus one test -- see the checklists in
[CLAUDE.md](CLAUDE.md).

## Local development

Requires Python 3.11+ (this repo's code is also syntax-compatible with 3.9,
see `CLAUDE.md`, but CI and production both target 3.11).

```bash
pip install -r requirements.txt
```

Export these in your terminal session -- never write them to a `.env` file:

```bash
export DATABRICKS_HOST=<workspace-host>.azuredatabricks.net
export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
# DATABRICKS_AUTH_MODE defaults to local_interactive (OAuth U2M, opens a
# browser to sign in) -- no secret needed for local dev.
```

Then run:

```bash
streamlit run app/main.py
```

See `.env.example` for the full list of variables.

## Tests

```bash
pytest
```

CI runs this on every push and pull request (`.github/workflows/tests.yml`).

## Deployment

See [docs/deploy.md](docs/deploy.md) for Azure App Service configuration,
Key Vault setup, and network requirements.
