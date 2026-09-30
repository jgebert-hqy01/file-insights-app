# Proving the Databricks connection from your own machine

A temporary, local-only way to prove the app's Databricks connection
works, under your own identity, using a short-lived personal access token
(PAT) set only in your terminal session. **Production stays OAuth M2M
with a service principal** -- this PAT path is explicitly refused if
`APP_ENV=production` or `WEBSITE_SITE_NAME` is set (App Service always
sets that), so it can't accidentally end up live.

**Try OAuth U2M first.** If it already works for you (it's the same
`local_interactive`... now renamed `oauth-u2m` -- see below -- path the
Streamlit app and the bot's local Playground testing already use), skip
the PAT entirely: it needs no token at all.

```
export DATABRICKS_HOST=<workspace-host>.azuredatabricks.net
export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
python scripts/preflight.py
python scripts/connect_check.py --filename <a-real-de-identified-filename>
```

(`DATABRICKS_AUTH_MODE` defaults to `oauth-u2m`, so nothing else needs
setting.) If that succeeds, you're done -- no PAT needed. If it fails on
a network-level error (not an auth error), a PAT won't help either, since
that's the same network reachability problem regardless of credential
type -- see `docs/deploy.md`'s note on this.

If OAuth U2M doesn't work for you, or you specifically want to test PAT
mode:

## 1. Create a PAT

In the Databricks UI: **Settings → Developer → Access tokens → Generate
new token**. Set the **lifetime to 1 day** -- short-lived on purpose,
since this is temporary.

Some workspaces disable PAT creation entirely (an org security policy,
not a bug). If the "Generate new token" option is missing or errors,
that's the workspace telling you PATs aren't allowed here -- don't try to
work around it. Fall back to OAuth U2M, or ask whoever administers the
workspace.

## 2. Set environment variables -- this session only

**Never write these to a `.env` file.** Set them directly in your current
terminal session so they disappear when it closes.

**PowerShell:**
```powershell
$env:DATABRICKS_HOST = "<workspace-host>.azuredatabricks.net"
$env:DATABRICKS_HTTP_PATH = "/sql/1.0/warehouses/<warehouse-id>"
$env:DATABRICKS_AUTH_MODE = "pat"
$env:DATABRICKS_TOKEN = "<paste the token here>"
```
**Never use `setx`** for `DATABRICKS_TOKEN` -- `setx` writes to the
Windows registry and persists across sessions indefinitely, defeating
the entire point of a short-lived, session-only token.

**cmd:**
```cmd
set DATABRICKS_HOST=<workspace-host>.azuredatabricks.net
set DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
set DATABRICKS_AUTH_MODE=pat
set DATABRICKS_TOKEN=<paste the token here>
```

**bash:**
```bash
export DATABRICKS_HOST=<workspace-host>.azuredatabricks.net
export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
export DATABRICKS_AUTH_MODE=pat
export DATABRICKS_TOKEN=<paste the token here>
```

## 3. Run preflight, then connect_check

```
python scripts/preflight.py
```
This only checks whether `pydantic`, `pandas`, `pyarrow`, and
`databricks.sql` actually import on this machine -- no network, no
Databricks connection. If something fails here (especially anything
mentioning a blocked file or an Application Control policy), stop: that's
a local-machine/IT policy question, and `connect_check.py` will hit the
identical wall. The same checks still work from an environment without
that restriction (e.g. Codespaces), using the same environment variables.

If preflight passes:
```
python scripts/connect_check.py --filename <a-real-de-identified-filename>
```
Use a real filename you expect to find, following this repo's usual rule:
de-identified test data only, never anything containing member PHI/PII in
a prompt or a filename chosen for convenience -- the same reminder that
applies everywhere else in this project.

The final report is PASS/FAIL, counts, durations, and error messages
only -- safe to paste anywhere, including back to Claude if something
needs debugging. It never contains a token or row data. It ends with a
short summary of exactly what the production service principal will need
(host, warehouse ID, the views actually touched, and the grants) so that
information doesn't have to be rediscovered later.

## 4. Revoke the token when done

Databricks UI: **Settings → Developer → Access tokens**, find the token
you created, click the trash/delete icon next to it. Do this even though
it's set to expire in a day -- there's no reason to leave it valid a
minute longer than needed.

Also close the terminal session (or at minimum `unset DATABRICKS_TOKEN` /
remove the `$env:DATABRICKS_TOKEN` variable) so it doesn't linger in that
shell's environment either.
