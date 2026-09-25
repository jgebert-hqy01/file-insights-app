"""Wires bot/handlers.py's business logic to the Microsoft 365 Agents SDK.

This is the only file in bot/ that imports the SDK -- bot/handlers.py and
bot/cards.py stay SDK-agnostic and unit-testable without it (see their
docstrings). Nothing here is unit-tested for the same reason app/db/client.py's
actual databricks_sql.connect() call isn't: it's thin wiring around a
real, external, hard-to-fake system, verified by actually running it,
not by mocking the SDK.

Auth configuration comes entirely from environment variables (never a
.env file -- this repo never writes secrets to disk), using the SDK's own
CONNECTIONS__SERVICE_CONNECTION__SETTINGS__* convention via
MsalConnectionManager. See docs/deploy.md for the exact variables to set
for managed identity (preferred) vs. a client-secret app registration.
This is the bot's *own* identity for talking to Azure Bot Service --
unrelated to how the app talks to Databricks (app/config.py, separately).
"""
import os

from aiohttp.web import Application, Request, Response, run_app
from microsoft_agents.activity import load_configuration_from_env
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import (
    CloudAdapter,
    jwt_authorization_middleware,
    start_agent_process,
)
from microsoft_agents.hosting.core import (
    AgentApplication,
    Authorization,
    MemoryStorage,
    TurnContext,
    TurnState,
)

from app.config import load_config
from app.registry.loader import load_registries
from bot.handlers import handle_message

_config = load_config()
_sources, _queries = load_registries()

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
    await handle_message(context, _config, _sources, _queries)


def create_web_app() -> Application:
    async def entry_point(req: Request) -> Response:
        agent: AgentApplication = req.app["agent_app"]
        adapter: CloudAdapter = req.app["adapter"]
        return await start_agent_process(req, agent, adapter)

    web_app = Application(middlewares=[jwt_authorization_middleware])
    web_app.router.add_post("/api/messages", entry_point)
    web_app.router.add_get("/api/messages", lambda _: Response(status=200))
    web_app["agent_configuration"] = _connection_manager.get_default_connection_configuration()
    web_app["agent_app"] = AGENT_APP
    web_app["adapter"] = AGENT_APP.adapter
    return web_app


if __name__ == "__main__":
    run_app(create_web_app(), host="0.0.0.0", port=int(os.environ.get("PORT", 3978)))
