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

## Teams bot (new presentation layer, alongside Streamlit)

The bot (`bot/app.py`) is a second, independent presentation layer over the
same registry/executor code Streamlit uses -- it does not replace the
Streamlit app, and neither depends on the other being deployed. None of
this exists yet (as of 2026-09-25): no Azure Bot resource, no bot Entra ID
identity, no Teams manifest, no catalog submission.

### Azure resources needed

- **Azure Bot resource** (Azure Bot Service), registered with the messaging
  endpoint `https://<your-host>/api/messages`.
- **An identity for the bot itself** -- separate from the Databricks
  service principal, and separate from whatever identity Streamlit's App
  Service uses for Key Vault. Prefer, in order:
  1. **System-assigned managed identity** on whichever App Service hosts
     `bot/app.py` (`AUTHTYPE=SystemManagedIdentity` -- no secret at all).
  2. A dedicated **Entra ID app registration with a client secret in Key
     Vault** (`AUTHTYPE=ClientSecret`), only if managed identity isn't
     workable for this Azure Bot resource.

  This mirrors the same "managed identity over secrets, secrets over
  nothing" preference already used for Databricks auth -- but it's a
  genuinely separate credential from that one. Don't reuse the Databricks
  service principal for this.
- **Where it runs**: either a **separate App Service** (or Container
  App/Function) from the Streamlit app -- simplest, and what this doc
  assumes below -- or the **same App Service**, fronted by a reverse proxy
  that routes `/api/messages` to the bot's aiohttp process (port 3978) and
  everything else to Streamlit's. The shared-instance path needs more
  infrastructure (nginx or similar) that isn't built here; don't assume it
  without deciding that explicitly first.

### App settings (environment variables)

Using managed identity (recommended):

| Name | Value |
| --- | --- |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__AUTHTYPE` | `SystemManagedIdentity` |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__SCOPES` | `https://api.botframework.com/.default` |
| `PORT` | `3978` (or whatever `WEBSITES_PORT` is set to for this App Service) |
| `BOT_ALLOWED_CALLER_IDS` | Comma-separated Entra object IDs, until real group-membership checking (`bot/permissions.py`) replaces the stub. |

Plus the same `DATABRICKS_*` variables as the Streamlit app (`bot/app.py`
calls the same `app/config.py`) -- see the App Service configuration
section above.

If using a client-secret app registration instead:

| Name | Value |
| --- | --- |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__AUTHTYPE` | `ClientSecret` |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID` | The app registration's Application ID. Not a secret. |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET` | `@Microsoft.KeyVault(VaultName=<vault-name>;SecretName=<secret-name>)` -- never a literal value. |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID` | The Entra tenant ID. |

### Startup command

```
python bot/app.py
```

`requirements.txt` lists `microsoft-agents-hosting-aiohttp` and
`microsoft-agents-authentication-msal` without version pins -- I couldn't
install them locally to verify an exact version (see the repo's README/
CLAUDE.md for why). **Pin them to whatever `pip install` actually resolves
the first time this is deployed for real.**

### No Easy Auth on `/api/messages`

If the bot ends up sharing an App Service with anything that has **App
Service Authentication (Easy Auth)** turned on (as Streamlit's does, for
its Entra sign-in): Easy Auth would intercept Bot Framework Connector
Service's server-to-server calls to `/api/messages` and try to redirect
them to an interactive login page, breaking the bot entirely, since those
calls aren't a browser session. Bot Framework has its own request
authentication (the JWT validation `jwt_authorization_middleware` already
does in `bot/app.py`) -- it doesn't need or want Easy Auth layered on top.

If the bot gets its own, separate App Service (this doc's default
assumption), this doesn't apply -- simply don't enable Easy Auth on that
App Service at all. If it ever does end up sharing an instance, App
Service Authentication V2 has an **excluded paths** setting
(Authentication > Edit > Excluded paths) -- add `/api/messages` there
before enabling Easy Auth on anything else on that instance.

### Teams app manifest and catalog publish

Package a `manifest.json` (schema version 1.17+) with at minimum:

- `id`: a new GUID for this app.
- `bots[0].botId`: the bot's Entra ID app ID (or, for managed identity, the
  Azure Bot resource's associated app ID -- confirm which once the Bot
  resource exists).
- `bots[0].scopes`: `["personal"]` to start (1:1 chat); add `"team"` later
  if channel/group use is wanted.
- `validDomains`: empty unless the bot links out to external content.
- `webApplicationInfo.id`: same as `bots[0].botId`, if using SSO later --
  not needed for the caller-identity-only permission stub in
  `bot/permissions.py`.

Package the manifest with app icons into a `.zip` per [Microsoft's Teams
app packaging
docs](https://learn.microsoft.com/microsoftteams/platform/concepts/build-and-test/apps-package).

**Catalog publish**: submitting this to HealthEquity's internal Teams app
catalog (org-wide or a specific team) is an M365 admin-driven process this
doc can't prescribe -- find out who administers the Teams admin center's
**Manage apps** catalog and what HealthEquity's internal review process
is before assuming self-service publish is available.

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
