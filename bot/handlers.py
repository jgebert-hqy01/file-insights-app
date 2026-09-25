"""SDK-agnostic bot business logic.

Nothing here imports the Microsoft 365 Agents SDK -- it only needs a "turn
context" duck-typed object exposing `.activity` (with `.text`, `.value`,
`.from_property`) and an async `send_activity(content)` method. Any real
SDK's TurnContext satisfies this; tests use a small fake instead. See
bot/app.py for the actual SDK wiring (not part of this file on purpose).

Every handler sends an immediate acknowledgement before doing any
Databricks work, then sends the real result as a follow-up activity in the
same turn -- so a slow warehouse cold start never looks like a hang.
"""
from typing import Any, Dict, Optional

from app.config import AppConfig
from app.db.client import SqlConnectorExecutor, check_filename_exists
from app.db.executor import QueryExecutionError
from app.registry.models import QueryDefinition, SourceDefinition
from app.validation import is_valid_filename
from bot.cards import (
    ACTION_ASK_QUESTION,
    ACTION_RUN_QUERY,
    ACTION_SHOW_MORE,
    build_filename_prompt_card,
    build_question_card,
    build_result_card,
    build_summary_card,
)
from bot.permissions import is_caller_allowed

_NOT_AUTHORIZED_MESSAGE = "Sorry, you're not authorized to use this bot yet."


def _caller_id(activity: Any) -> Optional[str]:
    from_property = getattr(activity, "from_property", None)
    if from_property is None:
        return None
    return getattr(from_property, "aad_object_id", None) or getattr(from_property, "id", None)


async def _send_card(context: Any, card: Dict[str, Any]) -> None:
    await context.send_activity(
        {
            "type": "message",
            "attachments": [
                {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}
            ],
        }
    )


async def handle_message(
    context: Any,
    config: AppConfig,
    sources: Dict[str, SourceDefinition],
    queries: Dict[str, QueryDefinition],
) -> None:
    """Routes an incoming message: either a plain-text filename, or an
    Adaptive Card action's submitted `value`."""
    activity = context.activity

    if not is_caller_allowed(_caller_id(activity)):
        await context.send_activity(_NOT_AUTHORIZED_MESSAGE)
        return

    value = getattr(activity, "value", None)
    if isinstance(value, dict) and value.get("action"):
        await _handle_action(context, value, config, sources, queries)
        return

    filename = (getattr(activity, "text", None) or "").strip()
    if not filename:
        await _send_card(context, build_filename_prompt_card())
        return
    if not is_valid_filename(filename):
        await context.send_activity(
            "'{0}' doesn't look like a valid filename (letters, digits, '.', "
            "'_', '-' only, max 255 chars).".format(filename)
        )
        return

    await context.send_activity("Looking up `{0}`...".format(filename))

    filename_sources = [s for s in sources.values() if s.filename_column]
    try:
        found_in = [
            source.name for source in filename_sources if check_filename_exists(config, source, filename)
        ]
    except QueryExecutionError as exc:
        await context.send_activity("Could not check whether the file exists: {0}".format(exc))
        return

    if not found_in:
        await context.send_activity("'{0}' was not found in any known source.".format(filename))
        return

    executor = SqlConnectorExecutor(config, sources)
    summary_results = []
    for query_def in queries.values():
        if not query_def.run_on_load:
            continue
        try:
            result = executor.execute(query_def, filename, row_cap=config.default_row_cap)
        except QueryExecutionError as exc:
            await context.send_activity("Could not run '{0}': {1}".format(query_def.title, exc))
            continue
        summary_results.append((query_def, result))

    await _send_card(context, build_summary_card(filename, found_in, summary_results))


async def _handle_action(
    context: Any,
    value: Dict[str, Any],
    config: AppConfig,
    sources: Dict[str, SourceDefinition],
    queries: Dict[str, QueryDefinition],
) -> None:
    action = value.get("action")
    filename = value.get("filename")
    if not filename:
        await context.send_activity("I lost track of which file this was about -- send the filename again.")
        return

    if action == ACTION_ASK_QUESTION:
        await _send_card(context, build_question_card(filename, queries))
        return

    if action == ACTION_RUN_QUERY:
        query_def = queries.get(value.get("question"))
        if query_def is None:
            await context.send_activity("I couldn't find that question anymore -- try again.")
            return
        filter_values = _extract_filter_values(query_def, value)
        await _run_and_send_result(context, config, sources, filename, query_def, filter_values)
        return

    if action == ACTION_SHOW_MORE:
        query_def = queries.get(value.get("query"))
        if query_def is None:
            await context.send_activity("I couldn't find that question anymore -- try again.")
            return
        filter_values = value.get("filter_values") or {}
        display_row_cap = value.get("display_row_cap")
        await _run_and_send_result(
            context, config, sources, filename, query_def, filter_values, display_row_cap
        )
        return

    await context.send_activity("Sorry, I didn't understand that action.")


def _extract_filter_values(query_def: QueryDefinition, value: Dict[str, Any]) -> Dict[str, Any]:
    filter_values = {}
    for parameter in query_def.parameters:
        raw = value.get("filter_{0}".format(parameter.name))
        raw = raw.strip() if isinstance(raw, str) else raw
        filter_values[parameter.name] = int(raw) if raw else None
    return filter_values


async def _run_and_send_result(
    context: Any,
    config: AppConfig,
    sources: Dict[str, SourceDefinition],
    filename: str,
    query_def: QueryDefinition,
    filter_values: Dict[str, Any],
    display_row_cap: Optional[int] = None,
) -> None:
    await context.send_activity("Running `{0}`...".format(query_def.name))

    executor = SqlConnectorExecutor(config, sources)
    try:
        result = executor.execute(
            query_def, filename, filter_values=filter_values, row_cap=config.default_row_cap
        )
    except QueryExecutionError as exc:
        await context.send_activity("Could not run '{0}': {1}".format(query_def.title, exc))
        return

    card_kwargs = {}
    if display_row_cap is not None:
        card_kwargs["display_row_cap"] = display_row_cap
    card = build_result_card(filename, query_def, result, filter_values, **card_kwargs)
    await _send_card(context, card)
