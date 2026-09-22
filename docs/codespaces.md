# Running and demoing the app in GitHub Codespaces

Runs the real app -- Streamlit, the SQL connector, everything -- under your
own Databricks identity, with no provisioning and no stored tokens. Same
`local_interactive` (OAuth U2M) auth path as running locally; no code
changes needed for Codespaces.

## Start it

1. Open this repo in a Codespace (**Code → Codespaces → Create codespace**).
   The devcontainer installs Python 3.11 and `pip install -r
   requirements.txt` automatically.
2. In the terminal, export the two required variables (never write these to
   a file):
   ```
   export DATABRICKS_HOST=<workspace-host>.azuredatabricks.net
   export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
   ```
3. Start Streamlit, binding to `0.0.0.0` (not the default `localhost` --
   required for Codespaces' port forwarding to reach it) and headless (no
   GUI to open a browser from inside the container):
   ```
   streamlit run app/main.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
   ```
4. Codespaces forwards port 8501 and should open it automatically
   (`onAutoForward: openBrowser` in `devcontainer.json`); if not, open the
   **Ports** tab and click the forwarded 8501 URL.

## How the OAuth browser callback works through the forwarded port

`app/db/client.py` uses `auth_type="databricks-oauth"` exactly as it does
locally -- no code path differs in Codespaces. That flow (confirmed by
reading `databricks-sql-connector`'s and the Databricks SDK's source, not
assumed):

1. Opens your browser to a Databricks login page.
2. After you sign in, Databricks redirects to `http://localhost:<port>/...`
   where `<port>` is one of a **fixed, known range: 8020-8024** (the
   connector tries them in order until one is free) -- not a random
   ephemeral port. That's exactly why `devcontainer.json` forwards all
   five: whichever one gets picked is already set up for forwarding, no
   dynamic detection race.
3. A short-lived local HTTP server inside the container receives that
   redirect and completes the login.

For step 2 to actually reach the container, `localhost:<port>` in your
browser has to tunnel back into the codespace. This works reliably when
you're connected via **VS Code Desktop** (Remote Explorer → Codespaces),
which transparently forwards `localhost` ports end-to-end. It is **not
guaranteed** the same way in the browser-only editor (`github.dev` or the
codespace's web UI with no VS Code Desktop attached), since forwarded ports
there are exposed as HTTPS URLs
(`https://<codespace>-8020.app.github.dev`), not literal `localhost`, and
the OAuth redirect is hardcoded to `localhost` by the SDK. **If you hit a
stuck or failed callback, connect with VS Code Desktop instead of the
browser editor and retry.**

I verified the fixed-port-range behavior by reading the connector/SDK
source directly, but haven't run this end-to-end in a live Codespace
myself. Please run the first real login and let me know what happens --
particularly whether the browser-only editor case above actually fails or
turns out to work, so this doc can stop hedging on it.

## What this does and doesn't prove

Proves: the real deployed app's code runs correctly against real data,
under your own identity, without any Azure/Databricks resources
provisioned yet.

Does not prove: the production service principal's OAuth M2M path, App
Service itself, the Entra ID header, or the App Service-to-Databricks
network path. See [docs/deploy.md](deploy.md) for those, and
[docs/smoke-test.md](smoke-test.md) for the notebook-based alternative if
you'd rather not run the full app.
