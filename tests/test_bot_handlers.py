"""Tests for bot/handlers.py, using a fake turn context (no SDK needed) and
a mocked SQL connector (no real Databricks call -- same pattern as
tests/test_client.py)."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from bot.cards import ACTION_ASK_QUESTION, ACTION_RUN_QUERY, ACTION_SHOW_MORE
from bot.handlers import _NOT_AUTHORIZED_MESSAGE, handle_message
from app.config import AppConfig, AuthMode
from app.registry.models import (
    ColumnDefinition,
    ParameterControl,
    ParameterType,
    QueryDefinition,
    QueryParameter,
    SourceDefinition,
)

CONFIG = AppConfig(
    databricks_host="test.azuredatabricks.net",
    databricks_http_path="/sql/1.0/warehouses/test",
    auth_mode=AuthMode.LOCAL_INTERACTIVE,
)

SOURCE = SourceDefinition(
    name="correlation_file",
    fully_qualified_view="catalog.schema.file",
    filename_column="FileName",
    columns=[ColumnDefinition(name="FileName", data_type="string")],
    sensitive_columns=[],
    description="test",
)
SOURCES = {"correlation_file": SOURCE}

SUMMARY_QUERY = QueryDefinition(
    name="last_loaded_at",
    title="Last loaded at",
    description="test",
    category="Overview",
    source="correlation_file",
    sql="SELECT MAX(x) AS last_loaded_at FROM t WHERE FileName = :filename",
    run_on_load=True,
)
HISTORY_QUERY = QueryDefinition(
    name="load_history",
    title="When did it load?",
    description="test",
    category="Load history",
    source="correlation_file",
    sql="SELECT BatchID FROM t WHERE FileName = :filename AND (:partner_id IS NULL OR PartnerID = :partner_id)",
    run_on_load=False,
    parameters=[
        QueryParameter(
            name="partner_id", label="Partner ID", type=ParameterType.INTEGER, control=ParameterControl.NUMBER
        )
    ],
)
QUERIES = {"last_loaded_at": SUMMARY_QUERY, "load_history": HISTORY_QUERY}


class FakeFromProperty:
    def __init__(self, id=None, aad_object_id=None):
        self.id = id
        self.aad_object_id = aad_object_id


class FakeActivity:
    def __init__(self, text=None, value=None, from_property=None):
        self.text = text
        self.value = value
        self.from_property = from_property if from_property is not None else FakeFromProperty(id="user-1")


class FakeTurnContext:
    def __init__(self, activity):
        self.activity = activity
        self.sent = []

    async def send_activity(self, content):
        self.sent.append(content)


def run_async(coro):
    return asyncio.run(coro)


def _allow(monkeypatch, caller_id="user-1"):
    monkeypatch.setenv("BOT_ALLOWED_CALLER_IDS", caller_id)


def _mock_cursor(mock_connect):
    cursor = MagicMock()
    mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cursor
    return cursor


def test_handle_message_denies_unauthorized_caller(monkeypatch):
    monkeypatch.delenv("BOT_ALLOWED_CALLER_IDS", raising=False)
    context = FakeTurnContext(FakeActivity(text="sample.csv"))

    run_async(handle_message(context, CONFIG, SOURCES, QUERIES))

    assert context.sent == [_NOT_AUTHORIZED_MESSAGE]


def test_handle_message_with_empty_text_sends_filename_prompt_card(monkeypatch):
    _allow(monkeypatch)
    context = FakeTurnContext(FakeActivity(text=""))

    run_async(handle_message(context, CONFIG, SOURCES, QUERIES))

    assert len(context.sent) == 1
    card = context.sent[0]["attachments"][0]["content"]
    assert card["body"][1]["text"] == "Send me a filename to look it up."


def test_handle_message_with_invalid_filename_sends_error(monkeypatch):
    _allow(monkeypatch)
    context = FakeTurnContext(FakeActivity(text="bad;name.csv"))

    run_async(handle_message(context, CONFIG, SOURCES, QUERIES))

    assert len(context.sent) == 1
    assert "doesn't look like a valid filename" in context.sent[0]


@patch("app.db.client.databricks_sql.connect")
def test_handle_message_existence_check_not_found(mock_connect, monkeypatch):
    _allow(monkeypatch)
    cursor = _mock_cursor(mock_connect)
    cursor.fetchone.return_value = None
    context = FakeTurnContext(FakeActivity(text="sample.csv"))

    run_async(handle_message(context, CONFIG, SOURCES, QUERIES))

    assert context.sent[0] == "Looking up `sample.csv`..."
    assert "was not found in any known source" in context.sent[1]


@patch("app.db.client.databricks_sql.connect")
def test_handle_message_full_flow_acks_then_sends_summary_card(mock_connect, monkeypatch):
    _allow(monkeypatch)
    cursor = _mock_cursor(mock_connect)
    cursor.fetchone.return_value = (1,)  # existence check: found
    cursor.fetchmany.return_value = [("2026-09-01",)]
    cursor.description = [("last_loaded_at", None)]
    context = FakeTurnContext(FakeActivity(text="sample.csv"))

    run_async(handle_message(context, CONFIG, SOURCES, QUERIES))

    assert context.sent[0] == "Looking up `sample.csv`..."
    card = context.sent[1]["attachments"][0]["content"]
    assert card["body"][1]["text"] == "sample.csv"


@patch("app.db.client.databricks_sql.connect")
def test_handle_message_existence_check_error_is_reported_and_stops(mock_connect, monkeypatch):
    _allow(monkeypatch)
    mock_connect.side_effect = RuntimeError("warehouse unreachable")
    context = FakeTurnContext(FakeActivity(text="sample.csv"))

    run_async(handle_message(context, CONFIG, SOURCES, QUERIES))

    assert context.sent[0] == "Looking up `sample.csv`..."
    assert "Could not check whether the file exists" in context.sent[1]
    assert len(context.sent) == 2  # never got to running summary queries


def test_handle_action_ask_question_sends_question_card(monkeypatch):
    _allow(monkeypatch)
    value = {"action": ACTION_ASK_QUESTION, "filename": "sample.csv"}
    context = FakeTurnContext(FakeActivity(value=value))

    run_async(handle_message(context, CONFIG, SOURCES, QUERIES))

    assert len(context.sent) == 1
    card = context.sent[0]["attachments"][0]["content"]
    assert card["body"][0]["text"] == "Pick a question"


@patch("app.db.client.databricks_sql.connect")
def test_handle_action_run_query_acks_then_sends_result_card(mock_connect, monkeypatch):
    _allow(monkeypatch)
    cursor = _mock_cursor(mock_connect)
    cursor.fetchmany.return_value = [(1,), (2,)]
    cursor.description = [("BatchID", None)]
    value = {
        "action": ACTION_RUN_QUERY,
        "filename": "sample.csv",
        "question": "load_history",
        "filter_partner_id": "309",
    }
    context = FakeTurnContext(FakeActivity(value=value))

    run_async(handle_message(context, CONFIG, SOURCES, QUERIES))

    assert context.sent[0] == "Running `load_history`..."
    card = context.sent[1]["attachments"][0]["content"]
    assert card["body"][0]["text"] == "When did it load?"

    args, kwargs = cursor.execute.call_args
    bound_by_name = {p.name: p.value for p in kwargs["parameters"]}
    assert bound_by_name["partner_id"] == 309


def test_handle_action_run_query_with_unknown_question_reports_friendly_error(monkeypatch):
    _allow(monkeypatch)
    value = {"action": ACTION_RUN_QUERY, "filename": "sample.csv", "question": "does_not_exist"}
    context = FakeTurnContext(FakeActivity(value=value))

    run_async(handle_message(context, CONFIG, SOURCES, QUERIES))

    assert "couldn't find that question" in context.sent[0]


@patch("app.db.client.databricks_sql.connect")
def test_handle_action_show_more_reruns_with_bigger_display_cap(mock_connect, monkeypatch):
    _allow(monkeypatch)
    cursor = _mock_cursor(mock_connect)
    cursor.fetchmany.return_value = [(i,) for i in range(20)]
    cursor.description = [("BatchID", None)]
    value = {
        "action": ACTION_SHOW_MORE,
        "filename": "sample.csv",
        "query": "load_history",
        "filter_values": {"partner_id": None},
        "display_row_cap": 20,
    }
    context = FakeTurnContext(FakeActivity(value=value))

    run_async(handle_message(context, CONFIG, SOURCES, QUERIES))

    card = context.sent[1]["attachments"][0]["content"]
    table = next(item for item in card["body"] if item.get("type") == "Table")
    assert len(table["rows"]) - 1 == 20  # header + all 20 rows, none hidden this time


def test_handle_action_missing_filename_reports_friendly_error(monkeypatch):
    _allow(monkeypatch)
    value = {"action": ACTION_RUN_QUERY, "question": "load_history"}
    context = FakeTurnContext(FakeActivity(value=value))

    run_async(handle_message(context, CONFIG, SOURCES, QUERIES))

    assert "lost track of which file" in context.sent[0]
