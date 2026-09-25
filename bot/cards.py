"""Pure functions that build Adaptive Card JSON from registry metadata and
query results.

No I/O, no Teams/Bot Framework SDK imports -- these take plain data (registry
objects, already-executed QueryResults) and return plain dicts. bot/handlers.py
does the actual work (existence checks, running queries) and hands the
results to these functions to render.

Every action's `data` payload carries `filename` and (where relevant) the
current filter values, so a handler receiving an action never needs to look
anything up from prior turns -- see bot/handlers.py.
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from app.db.executor import QueryResult
from app.registry.models import ParameterControl, QueryDefinition

ADAPTIVE_CARD_VERSION = "1.5"
DEFAULT_DISPLAY_ROW_CAP = 10

ACTION_ASK_QUESTION = "ask_question"
ACTION_RUN_QUERY = "run_query"
ACTION_SHOW_MORE = "show_more"

# Conservative margin under Teams' ~40 KB (UTF-16-encoded) bot message limit,
# leaving room for the surrounding Activity envelope (conversation id,
# channel data, etc.) that isn't part of the card itself.
_MAX_CARD_SIZE_BYTES = 20 * 1024


class CardTooLargeError(ValueError):
    """Raised when a card can't be shrunk enough to fit the size budget."""


def _card_size_bytes(card: Dict[str, Any]) -> int:
    return len(json.dumps(card).encode("utf-16-le"))


def _text_block(text: str, **kwargs: Any) -> Dict[str, Any]:
    block: Dict[str, Any] = {"type": "TextBlock", "text": text, "wrap": True}
    block.update(kwargs)
    return block


def _submit_action(title: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "Action.Submit", "title": title, "data": data}


def _card_shell(body: List[Dict[str, Any]], actions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    card: Dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": ADAPTIVE_CARD_VERSION,
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return card


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def _table_row(values: Sequence[str], is_header: bool) -> Dict[str, Any]:
    return {
        "type": "TableRow",
        "cells": [
            {
                "type": "TableCell",
                "items": [_text_block(value, weight="Bolder" if is_header else "Default")],
            }
            for value in values
        ],
    }


def _dataframe_to_table(dataframe: pd.DataFrame, max_rows: int) -> Dict[str, Any]:
    if dataframe.empty:
        return _text_block("No rows returned.", isSubtle=True)
    columns = [str(c) for c in dataframe.columns]
    shown = dataframe.head(max_rows)
    rows = [_table_row(columns, is_header=True)]
    for row in shown.itertuples(index=False):
        rows.append(_table_row([_cell_text(v) for v in row], is_header=False))
    return {
        "type": "Table",
        "columns": [{"width": 1} for _ in columns],
        "rows": rows,
        "firstRowAsHeader": False,
    }


def _footer_text_block(query_def: QueryDefinition, result: QueryResult) -> Dict[str, Any]:
    ran_at_label = datetime.fromtimestamp(result.ran_at).strftime("%Y-%m-%d %H:%M:%S")
    text = "Produced by `{0}` at {1} ({2:.2f}s)".format(
        query_def.name, ran_at_label, result.latency_seconds
    )
    return _text_block(text, isSubtle=True, size="Small")


def _build_result_body_and_actions(
    filename: str,
    query_def: QueryDefinition,
    result: QueryResult,
    filter_values: Dict[str, Any],
    display_row_cap: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    total_rows = len(result.dataframe)
    shown_rows = min(total_rows, display_row_cap)

    body = [
        _text_block(query_def.title, size="Large", weight="Bolder"),
        _text_block(query_def.description, isSubtle=True, size="Small"),
        _dataframe_to_table(result.dataframe, max_rows=display_row_cap),
    ]
    if shown_rows < total_rows:
        body.append(_text_block("Showing {0} of {1} row(s).".format(shown_rows, total_rows), isSubtle=True, size="Small"))
    elif result.row_cap_hit:
        body.append(_text_block("More rows exist beyond what was fetched.", isSubtle=True, size="Small"))
    body.append(_footer_text_block(query_def, result))

    actions = []
    if shown_rows < total_rows:
        actions.append(
            _submit_action(
                "Show more",
                {
                    "action": ACTION_SHOW_MORE,
                    "filename": filename,
                    "query": query_def.name,
                    "filter_values": filter_values,
                    "display_row_cap": min(total_rows, display_row_cap * 2),
                },
            )
        )
    return body, actions


def build_filename_prompt_card() -> Dict[str, Any]:
    """Shown when the bot doesn't yet have a filename to work with."""
    return _card_shell(
        body=[
            _text_block("File Insight", size="Large", weight="Bolder"),
            _text_block("Send me a filename to look it up."),
        ]
    )


def _build_summary_body(
    filename: str,
    found_in: List[str],
    summary_results: List[Tuple[QueryDefinition, QueryResult]],
    per_query_row_cap: int,
) -> List[Dict[str, Any]]:
    body = [
        _text_block("File Insight", size="Large", weight="Bolder"),
        _text_block(filename, weight="Bolder"),
        _text_block(
            "Found in: " + ", ".join(found_in) if found_in else "Not found in any known source."
        ),
    ]
    for query_def, result in summary_results:
        body.append(_text_block(query_def.title, weight="Bolder", spacing="Medium"))
        body.append(_text_block(query_def.description, isSubtle=True, size="Small"))
        body.append(_dataframe_to_table(result.dataframe, max_rows=per_query_row_cap))
        body.append(_footer_text_block(query_def, result))
    return body


def _build_within_size_budget(build_body_and_actions, initial_cap: int, label: str) -> Dict[str, Any]:
    """Calls `build_body_and_actions(cap) -> (body, actions)` with a shrinking
    per-table row cap until the resulting card fits `_MAX_CARD_SIZE_BYTES`."""
    cap = initial_cap
    while True:
        body, actions = build_body_and_actions(cap)
        card = _card_shell(body=body, actions=actions)
        if _card_size_bytes(card) <= _MAX_CARD_SIZE_BYTES:
            return card
        if cap <= 1:
            raise CardTooLargeError(
                "Could not shrink {0} under the {1} byte budget even at 1 row per table.".format(
                    label, _MAX_CARD_SIZE_BYTES
                )
            )
        cap = max(1, cap // 2)


def build_summary_card(
    filename: str,
    found_in: List[str],
    summary_results: List[Tuple[QueryDefinition, QueryResult]],
) -> Dict[str, Any]:
    """The existence check result plus every run_on_load query's result."""
    actions = []
    if found_in:
        actions.append(_submit_action("Ask a question", {"action": ACTION_ASK_QUESTION, "filename": filename}))

    return _build_within_size_budget(
        lambda cap: (_build_summary_body(filename, found_in, summary_results, cap), actions),
        DEFAULT_DISPLAY_ROW_CAP,
        "summary card",
    )


def build_question_card(filename: str, queries: Dict[str, QueryDefinition]) -> Dict[str, Any]:
    """A question dropdown (labeled by category) plus every possible filter
    input across every drill-down question. Only the inputs belonging to
    whichever question gets chosen are read when the form is submitted --
    see bot/handlers.py."""
    drilldown_queries = [q for q in queries.values() if not q.run_on_load]
    if not drilldown_queries:
        return _card_shell(body=[_text_block("No drill-down questions are defined yet.")])

    choices = [
        {"title": "{0}: {1}".format(q.category, q.title), "value": q.name}
        for q in sorted(drilldown_queries, key=lambda q: (q.category, q.title))
    ]
    body: List[Dict[str, Any]] = [
        _text_block("Pick a question", size="Large", weight="Bolder"),
        {
            "type": "Input.ChoiceSet",
            "id": "question",
            "label": "Question",
            "style": "compact",
            "choices": choices,
            "isRequired": True,
        },
    ]

    all_parameters = {}
    for q in drilldown_queries:
        for parameter in q.parameters:
            all_parameters[parameter.name] = parameter
    for parameter in sorted(all_parameters.values(), key=lambda p: p.name):
        body.append(_filter_input(parameter))

    actions = [_submit_action("Run", {"action": ACTION_RUN_QUERY, "filename": filename})]
    return _card_shell(body=body, actions=actions)


def _filter_input(parameter) -> Dict[str, Any]:
    if parameter.control != ParameterControl.NUMBER:
        raise NotImplementedError(
            "Card control for '{0}' has no renderer yet. Add one to "
            "bot/cards.py when the first query using it is added.".format(parameter.control.value)
        )
    return {
        "type": "Input.Text",
        "id": "filter_{0}".format(parameter.name),
        "label": "{0} (optional)".format(parameter.label),
        "isRequired": False,
    }


def build_result_card(
    filename: str,
    query_def: QueryDefinition,
    result: QueryResult,
    filter_values: Dict[str, Any],
    display_row_cap: int = DEFAULT_DISPLAY_ROW_CAP,
) -> Dict[str, Any]:
    """The chosen question's masked result: a table capped at
    `display_row_cap` rows, a "Show more" action if more rows exist, and a
    "produced by" footer."""
    return _build_within_size_budget(
        lambda cap: _build_result_body_and_actions(filename, query_def, result, filter_values, cap),
        display_row_cap,
        "result card",
    )
