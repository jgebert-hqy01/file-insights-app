"""Tests for bot/cards.py: pure Adaptive Card builders.

Every card is validated against the real Adaptive Card JSON Schema
(bundled at tests/fixtures/adaptive-card-schema.json, downloaded from
https://adaptivecards.io/schemas/adaptive-card.json) so a structurally
invalid card fails here, not in Teams.
"""
import json
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import validate

from bot.cards import (
    ACTION_ASK_QUESTION,
    ACTION_RUN_QUERY,
    ACTION_SHOW_MORE,
    CardTooLargeError,
    build_filename_prompt_card,
    build_question_card,
    build_result_card,
    build_summary_card,
)
from app.db.executor import QueryResult
from app.registry.models import (
    ParameterControl,
    ParameterType,
    QueryDefinition,
    QueryParameter,
)

_SCHEMA_PATH = Path(__file__).parent / "fixtures" / "adaptive-card-schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _assert_valid_card(card):
    validate(instance=card, schema=_SCHEMA)


def _query(name="q1", title="Question", category="Overview", run_on_load=False, parameters=None):
    return QueryDefinition(
        name=name,
        title=title,
        description="A test query.",
        category=category,
        source="test_source",
        sql="SELECT 1 AS x FROM t WHERE FileName = :filename",
        run_on_load=run_on_load,
        parameters=parameters or [],
    )


def _result(rows, columns, ran_at=1700000000.0, latency=0.5, row_cap_hit=False):
    return QueryResult(
        query_name="q1",
        dataframe=pd.DataFrame(rows, columns=columns),
        ran_at=ran_at,
        latency_seconds=latency,
        row_cap_hit=row_cap_hit,
    )


def test_filename_prompt_card_is_a_valid_adaptive_card():
    _assert_valid_card(build_filename_prompt_card())


def test_summary_card_is_valid_and_has_ask_question_action_when_found():
    query_def = _query(run_on_load=True)
    result = _result([("2026-09-01",)], ["last_loaded_at"])
    card = build_summary_card("sample.csv", ["correlation_file"], [(query_def, result)])

    _assert_valid_card(card)
    actions = card.get("actions", [])
    assert len(actions) == 1
    assert actions[0]["data"] == {"action": ACTION_ASK_QUESTION, "filename": "sample.csv"}


def test_summary_card_has_no_ask_question_action_when_not_found():
    card = build_summary_card("sample.csv", [], [])
    _assert_valid_card(card)
    assert card.get("actions", []) == []


def test_question_card_is_valid_and_lists_choices_by_category():
    queries = {
        "history": _query(name="history", title="When did it load?", category="Load history"),
        "count": _query(name="count", title="How many times?", category="Overview"),
        "summary_only": _query(name="summary_only", title="Summary", run_on_load=True),
    }
    card = build_question_card("sample.csv", queries)
    _assert_valid_card(card)

    choice_set = next(item for item in card["body"] if item.get("type") == "Input.ChoiceSet")
    values = {c["value"] for c in choice_set["choices"]}
    # run_on_load queries are never offered as drill-down questions.
    assert values == {"history", "count"}
    titles = {c["title"] for c in choice_set["choices"]}
    assert "Load history: When did it load?" in titles
    assert "Overview: How many times?" in titles

    run_action = card["actions"][0]
    assert run_action["data"] == {"action": ACTION_RUN_QUERY, "filename": "sample.csv"}


def test_question_card_includes_a_filter_input_per_distinct_parameter():
    partner_param = QueryParameter(
        name="partner_id", label="Partner ID", type=ParameterType.INTEGER, control=ParameterControl.NUMBER
    )
    queries = {"history": _query(name="history", parameters=[partner_param])}
    card = build_question_card("sample.csv", queries)
    _assert_valid_card(card)

    filter_inputs = [item for item in card["body"] if item.get("id") == "filter_partner_id"]
    assert len(filter_inputs) == 1
    assert filter_inputs[0]["type"] == "Input.Text"
    assert filter_inputs[0]["isRequired"] is False


def test_question_card_raises_for_a_control_with_no_renderer_yet():
    unsupported_param = QueryParameter(
        name="date_param", label="Date", type=ParameterType.DATE, control=ParameterControl.SELECT
    )
    queries = {"history": _query(name="history", parameters=[unsupported_param])}
    with pytest.raises(NotImplementedError):
        build_question_card("sample.csv", queries)


def test_question_card_with_no_drilldown_queries_is_still_valid():
    card = build_question_card("sample.csv", {"summary_only": _query(run_on_load=True)})
    _assert_valid_card(card)
    assert card.get("actions", []) == []


def test_result_card_is_valid_and_has_footer_and_no_show_more_when_all_rows_shown():
    query_def = _query()
    result = _result([(1, "a"), (2, "b")], ["id", "name"])
    card = build_result_card("sample.csv", query_def, result, filter_values={"partner_id": 42})

    _assert_valid_card(card)
    footer_texts = [b["text"] for b in card["body"] if b.get("type") == "TextBlock"]
    assert any("Produced by `q1` at" in t for t in footer_texts)
    assert card.get("actions", []) == []


def test_result_card_has_show_more_action_carrying_filename_and_filter_values_when_capped():
    query_def = _query()
    rows = [(i, "row{0}".format(i)) for i in range(20)]
    result = _result(rows, ["id", "name"])
    card = build_result_card(
        "sample.csv", query_def, result, filter_values={"partner_id": 42}, display_row_cap=5
    )

    _assert_valid_card(card)
    actions = card.get("actions", [])
    assert len(actions) == 1
    show_more = actions[0]
    assert show_more["data"]["action"] == ACTION_SHOW_MORE
    assert show_more["data"]["filename"] == "sample.csv"
    assert show_more["data"]["query"] == "q1"
    assert show_more["data"]["filter_values"] == {"partner_id": 42}
    assert show_more["data"]["display_row_cap"] == 10


def test_result_card_shrinks_table_to_fit_size_budget_for_a_large_dataframe():
    query_def = _query()
    rows = [(i, "value-{0}-{1}".format(i, "x" * 50)) for i in range(500)]
    result = _result(rows, ["id", "name"])

    card = build_result_card("sample.csv", query_def, result, filter_values={}, display_row_cap=500)

    _assert_valid_card(card)
    card_bytes = len(json.dumps(card).encode("utf-16-le"))
    assert card_bytes <= 20 * 1024
    table = next(item for item in card["body"] if item.get("type") == "Table")
    assert len(table["rows"]) - 1 < 500  # header row + fewer than all 500 data rows


def test_result_card_raises_card_too_large_error_when_even_one_row_does_not_fit():
    query_def = _query()
    huge_value = "x" * (30 * 1024)
    result = _result([(huge_value,)], ["giant_column"])

    with pytest.raises(CardTooLargeError):
        build_result_card("sample.csv", query_def, result, filter_values={}, display_row_cap=10)


def test_result_card_with_empty_dataframe_is_valid():
    query_def = _query()
    result = _result([], ["id", "name"])
    card = build_result_card("sample.csv", query_def, result, filter_values={})
    _assert_valid_card(card)
