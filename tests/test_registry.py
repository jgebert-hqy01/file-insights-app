"""Registry metadata-completeness tests.

Every query must be parameterized, read-only, reference a known source,
declare every parameter it uses in its SQL, and have a title and description.
A half-defined query should fail here, in CI, not at runtime.
"""
import types

import pytest

from app.db.client import is_read_only_statement
from app.registry import loader
from app.registry.loader import RegistryError, load_queries, load_registries, load_sources
from app.registry.models import ColumnDefinition, QueryDefinition, SourceDefinition


def test_sources_load_without_error():
    sources = load_sources()
    assert sources, "expected at least one source to be discovered"


def test_queries_load_without_error():
    queries = load_queries()
    assert queries, "expected at least one query to be discovered"


def test_load_registries_validates_source_references():
    sources, queries = load_registries()
    for query in queries.values():
        assert query.source in sources


def test_every_query_is_read_only():
    _, queries = load_registries()
    for query in queries.values():
        assert is_read_only_statement(query.sql), f"{query.name} is not read-only"


def test_read_only_check_uses_word_boundaries_not_substring_match():
    # Column names that contain a forbidden keyword as a substring (not as a
    # standalone SQL keyword) must not trip the DDL/DML guard.
    assert is_read_only_statement(
        "SELECT update_date, created_at, deleted_flag FROM t WHERE FileName = :filename"
    )
    assert is_read_only_statement("SELECT dropdown_value FROM t WHERE FileName = :filename")
    # A real forbidden keyword, even disguised as a trailing statement after
    # a valid SELECT prefix, must still be rejected.
    assert not is_read_only_statement(
        "SELECT 1 FROM t WHERE FileName = :filename; DROP TABLE members"
    )
    assert not is_read_only_statement("UPDATE t SET x = 1 WHERE FileName = :filename")


def test_query_definition_accepts_columns_with_keyword_substrings():
    query = QueryDefinition(
        name="test_query",
        title="Test",
        description="Test",
        category="Test",
        source="test_source",
        sql="SELECT update_date, created_at, deleted_flag FROM t WHERE FileName = :filename",
    )
    assert "update_date" in query.sql


def test_query_definition_rejects_forbidden_keyword_after_valid_select_prefix():
    with pytest.raises(ValueError):
        QueryDefinition(
            name="test_query",
            title="Test",
            description="Test",
            category="Test",
            source="test_source",
            sql="SELECT 1 FROM t WHERE FileName = :filename; DROP TABLE members",
        )


def test_every_query_binds_filename():
    _, queries = load_registries()
    for query in queries.values():
        assert "filename" in query.sql_parameter_names(), f"{query.name} does not bind :filename"


def test_every_query_declares_exactly_the_parameters_it_uses():
    _, queries = load_registries()
    for query in queries.values():
        declared = {p.name for p in query.parameters} | {"filename"}
        used = query.sql_parameter_names()
        assert used <= declared, f"{query.name} uses undeclared parameters: {used - declared}"
        assert declared - {"filename"} <= used, (
            f"{query.name} declares unused parameters: {declared - used - {'filename'}}"
        )


def test_every_query_has_title_and_description():
    _, queries = load_registries()
    for query in queries.values():
        assert query.title.strip()
        assert query.description.strip()


def test_load_registries_rejects_query_with_unknown_source():
    real_query = next(iter(load_queries().values()))
    orphan_query = real_query.model_copy(update={"source": "does_not_exist"})
    with pytest.raises(RegistryError):
        loader.validate_query_sources({"orphan": orphan_query}, sources={})


def test_discover_raises_on_duplicate_definition_names(monkeypatch):
    def make_source(name):
        return SourceDefinition(
            name=name,
            fully_qualified_view="catalog.schema.view",
            filename_column=None,
            columns=[ColumnDefinition(name="a", data_type="string")],
            sensitive_columns=[],
            description="test",
        )

    module_a = types.ModuleType("fake_pkg.a")
    module_a.source_one = make_source("dup")
    module_b = types.ModuleType("fake_pkg.b")
    module_b.source_two = make_source("dup")

    fake_package = types.ModuleType("fake_pkg")
    fake_package.__path__ = ["fake_pkg"]

    monkeypatch.setattr(
        loader.pkgutil,
        "iter_modules",
        lambda path, prefix: [
            types.SimpleNamespace(name="fake_pkg.a"),
            types.SimpleNamespace(name="fake_pkg.b"),
        ],
    )
    monkeypatch.setattr(
        loader.importlib,
        "import_module",
        lambda name: {"fake_pkg.a": module_a, "fake_pkg.b": module_b}[name],
    )

    with pytest.raises(RegistryError):
        loader._discover(fake_package, SourceDefinition)
