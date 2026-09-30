"""Local-only entry point for testing the bot with the Microsoft 365 Agents
Playground -- no Azure Bot resource, no real app registration, no managed
identity. Never use this for anything but local testing; see bot/app.py
for the real, authenticated production entry point.

The installed SDK version requires both CloudAdapter and AgentApplication
to be constructed with a connection_manager (AgentApplication needs its
own, to build an Authorization instance) -- there's no bare-anonymous-mode
constructor in the current API, despite older docs describing one. So
this uses the exact same MsalConnectionManager/CloudAdapter/Authorization
pattern bot/app.py uses, just fed obviously-fake, local-only placeholder
credentials via CONNECTIONS__SERVICE_CONNECTION__SETTINGS__* env vars.
These are never real secrets and this path should never need to make a
real Azure AD call for the Playground's "emulator" channel; if that
assumption turns out wrong, the error will look different from the one
this fixes -- report back.

Run (with fake placeholder values, never real credentials):

    export CONNECTIONS__SERVICE_CONNECTION__SETTINGS__AUTHTYPE=ClientSecret
    export CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID=local-playground-test
    export CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET=local-playground-test
    export CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID=local-playground-test
    python bot/local_playground.py

then, in a separate terminal, install and run the Agents Playground
(renamed from @microsoft/teams-app-test-tool as of late 2026):

    npm install -g @microsoft/m365agentsplayground
    agentsplayground -e "http://localhost:3978/api/messages" -c "emulator"

which opens a browser-based chat simulator that talks to this bot exactly
the way Teams would, without needing real Teams, a tenant, or a network
path to Azure Bot Service.
"""
import os
import sys

# `python bot/local_playground.py` puts this file's own directory (bot/) on
# sys.path[0], not the repo root -- and bot/ also contains a file literally
# named app.py, which would otherwise shadow the real app/ package for
# `from app.X import Y` below. Same fix as app/main.py and
# scripts/smoke_test.py, for the same underlying reason.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiohttp.web import Application, Request, Response, run_app
from microsoft_agents.activity import load_configuration_from_env
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter, start_agent_process
from microsoft_agents.hosting.core import (
    AgentApplication,
    Authorization,
    MemoryStorage,
    TurnContext,
    TurnState,
)

from app.config import load_config
from app.registry.loader import load_registries
from bot.handlers import _caller_id, handle_message  # _caller_id: diagnostic use only, see below

_config = load_config()
_sources, _queries = load_registries()

# Mirrors bot/app.py's construction exactly (AgentApplication itself needs
# its own connection_manager to build an Authorization instance, separate
# from the adapter's) -- only the credential *values* differ, and only the
# jwt_authorization_middleware on the web app below is intentionally
# skipped, since this is local-only.
_agents_sdk_config = load_configuration_from_env(os.environ)
_storage = MemoryStorage()
_connection_manager = MsalConnectionManager(**_agents_sdk_config)
_adapter = CloudAdapter(connection_manager=_connection_manager)
_authorization = Authorization(_storage, _connection_manager, **_agents_sdk_config)

AGENT_APP = AgentApplication[TurnState](
    storage=_storage,
    adapter=_adapter,
    authorization=_authorization,
    **_agents_sdk_config,
)


@AGENT_APP.activity("message")
async def _on_message(context: TurnContext, _state: TurnState) -> None:
    # bot/permissions.py denies by default. Printing the caller id the
    # Playground's simulated user presents means you can see what to put in
    # BOT_ALLOWED_CALLER_IDS instead of guessing -- local testing only, never
    # do this in bot/app.py (production).
    print("[local_playground] caller_id from this activity: {0}".format(_caller_id(context.activity)))
    await handle_message(context, _config, _sources, _queries)


async def _entry_point(req: Request) -> Response:
    return await start_agent_process(req, req.app["agent_app"], req.app["adapter"])


def create_web_app() -> Application:
    web_app = Application()
    web_app.router.add_post("/api/messages", _entry_point)
    web_app.router.add_get("/api/messages", lambda _: Response(status=200))
    web_app["agent_app"] = AGENT_APP
    web_app["adapter"] = AGENT_APP.adapter
    return web_app


if __name__ == "__main__":
    run_app(create_web_app(), host="0.0.0.0", port=int(os.environ.get("PORT", 3978)))
