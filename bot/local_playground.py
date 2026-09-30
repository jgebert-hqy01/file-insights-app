"""Local-only entry point for testing the bot with the Microsoft 365 Agents
Playground -- no Azure Bot resource, no app registration, no managed
identity, no auth at all. Never use this for anything but local testing;
see bot/app.py for the real, authenticated production entry point.

Run:

    python bot/local_playground.py

then, in a separate terminal:

    npx @microsoft/teams-app-test-tool

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
from microsoft_agents.hosting.aiohttp import CloudAdapter, start_agent_process
from microsoft_agents.hosting.core import AgentApplication, MemoryStorage, TurnContext, TurnState

from app.config import load_config
from app.registry.loader import load_registries
from bot.handlers import _caller_id, handle_message  # _caller_id: diagnostic use only, see below

_config = load_config()
_sources, _queries = load_registries()

AGENT_APP = AgentApplication[TurnState](storage=MemoryStorage(), adapter=CloudAdapter())


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
