# Deployment

Neither the Azure App Service instance nor the Databricks service principal /
Key Vault exist yet (as of 2026-09-18). This doc describes what's needed;
replace every `<placeholder>` once the real resources are provisioned.

## Azure resources needed

- **App Service plan + Web App**, Linux, Python 3.11 runtime stack.
- **Azure Key Vault** holding the Databricks service principal's OAuth client
  secret.
- **Databricks service principal** (see [Authenticate with a service
  principal using OAuth
  M2M](https://learn.microsoft.com/azure/databricks/dev-tools/auth/oauth-m2m)),
  with `SELECT` granted on the sources this app reads from (see the "View vs.
  base table" note below) -- not on catalogs/schemas more broadly.
- **Network path to Databricks**: VNet integration or an IP access list entry
  so the App Service instance can reach the SQL Warehouse's server hostname.
  The platform team coordinates this.
- **App Service Authentication (Entra ID)** enabled on the Web App, so
  `X-MS-CLIENT-PRINCIPAL-NAME` is populated for every request. `app/auth.py`
  reads this header directly; it never implements its own login.

## App Service configuration

### Startup command

Set the App Service **Configuration > General settings > Startup Command**
to:

```
bash startup.sh
```

### App settings (environment variables)

| Name | Value | Notes |
| --- | --- | --- |
| `DATABRICKS_HOST` | `<workspace-host>.azuredatabricks.net` | Not a secret. |
| `DATABRICKS_HTTP_PATH` | `/sql/1.0/warehouses/<warehouse-id>` | Not a secret. |
| `DATABRICKS_AUTH_MODE` | `service_principal` | Selects the OAuth M2M path in `app/config.py`. |
| `DATABRICKS_CLIENT_ID` | the service principal's Application ID | Not a secret, but keep alongside the secret for clarity. |
| `DATABRICKS_CLIENT_SECRET` | `@Microsoft.KeyVault(VaultName=<vault-name>;SecretName=<secret-name>)` | Key Vault reference -- never a literal value. |
| `DEFAULT_ROW_CAP` | `500` | Optional; this is the default if unset. |
| `WEBSITES_PORT` | `8000` | Must match the port `startup.sh` binds to. |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` | Lets Oryx install from `requirements.txt` server-side on deploy. |

Set `DATABRICKS_CLIENT_ID`/`DATABRICKS_CLIENT_SECRET` as **Key Vault
references** (Configuration > Application settings > value picker > Key
Vault Reference), not literal values, so the App Service's managed identity
(not this app's code) is what reads the vault. That requires:

1. A **system-assigned managed identity** enabled on the App Service.
2. That identity granted a Key Vault **"Key Vault Secrets User"** role (or an
   access policy with `get` permission) on `<vault-name>`.

### Python version

Set the runtime stack to Python 3.11 (or 3.12 if that's what's available in
the App Service Linux gallery when this is provisioned -- check
`az webapp list-runtimes --os linux` first). Local dev on this project
currently runs Python 3.9 (see `CLAUDE.md`); that's a local-machine
limitation, not a target for App Service.

## GitHub Actions deployment

`.github/workflows/deploy.yml` is written but set to `workflow_dispatch`
(manual trigger only) until the App Service exists and the secrets below are
set, to avoid a workflow that fails on every push. Once ready:

1. Set up an Entra ID app registration with a **federated credential**
   trusting this GitHub repo (Settings > Security > Federated credentials in
   the app registration), scoped to `environment` or `branch:main` --
   this avoids storing any Azure secret in GitHub at all.
2. Add these as **GitHub Actions repository secrets**:
   - `AZURE_CLIENT_ID` -- the app registration's client ID.
   - `AZURE_TENANT_ID`
   - `AZURE_SUBSCRIPTION_ID`
3. Add this as a **GitHub Actions repository variable**:
   - `AZURE_WEBAPP_NAME` -- the App Service's name.
4. Change the workflow's `on:` trigger from `workflow_dispatch` to
   `push: branches: [main]` once the above is in place.

## View vs. base table (open item)

`raw_classic.correlation.file` is currently a managed base table, not a
view. The brief's intent is for the app's identity to have `SELECT` on
narrow views, not base tables. Before granting the service principal
access, ask whoever administers the `raw_classic.correlation` schema to
create a view exposing just the columns this app uses:

```sql
CREATE VIEW raw_classic.correlation.vw_file AS
SELECT FileID, FileName, BatchID, PartnerID, AuditInfo_CreatedAt,
       AuditInfo_ModifiedAt, AuditInfo_CreatedBy, AuditInfo_ModifiedBy, hvr_timestamp
FROM raw_classic.correlation.file;
```

Then grant the service principal `SELECT` on the view, and update
`app/sources/correlation.py`'s `fully_qualified_view` to point at it -- no
other code changes needed.
