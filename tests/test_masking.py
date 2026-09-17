"""Tests for column masking based on source and query sensitive-column metadata."""
import pandas as pd

from app.masking import effective_sensitive_columns, mask_dataframe
from app.registry.models import ColumnDefinition, QueryDefinition, SourceDefinition

SOURCE = SourceDefinition(
    name="test_source",
    fully_qualified_view="catalog.schema.view",
    filename_column="FileName",
    columns=[
        ColumnDefinition(name="FileName", data_type="string"),
        ColumnDefinition(name="SSN", data_type="string"),
        ColumnDefinition(name="MemberID", data_type="string"),
    ],
    sensitive_columns=["SSN", "MemberID"],
    description="test",
)


def _make_query(**overrides):
    defaults = dict(
        name="test_query",
        title="Test",
        description="Test",
        category="Test",
        source="test_source",
        sql="SELECT SSN, MemberID, FileName FROM catalog.schema.view WHERE FileName = :filename",
        additional_sensitive_columns=[],
        unmasked_columns=[],
    )
    defaults.update(overrides)
    return QueryDefinition(**defaults)


def test_effective_sensitive_columns_combines_source_and_additional():
    query = _make_query(additional_sensitive_columns=["ExtraSecret"])
    assert effective_sensitive_columns(query, SOURCE) == {"SSN", "MemberID", "ExtraSecret"}


def test_unmasked_columns_override_source_sensitivity():
    query = _make_query(unmasked_columns=["SSN"])
    assert effective_sensitive_columns(query, SOURCE) == {"MemberID"}


def test_mask_dataframe_shows_last_four_characters_only():
    query = _make_query()
    df = pd.DataFrame(
        {
            "SSN": ["XXX-XX-1234"],
            "MemberID": ["MEMBER_TEST_001"],
            "FileName": ["sample_file_001.csv"],
        }
    )
    masked = mask_dataframe(df, query, SOURCE)
    assert masked.loc[0, "SSN"] == "*******1234"
    assert masked.loc[0, "MemberID"] == "***********_001"
    assert masked.loc[0, "FileName"] == "sample_file_001.csv"


def test_mask_dataframe_handles_none_and_short_values():
    query = _make_query()
    df = pd.DataFrame({"SSN": [None], "MemberID": ["ab"], "FileName": ["x"]})
    masked = mask_dataframe(df, query, SOURCE)
    assert masked.loc[0, "SSN"] is None
    assert masked.loc[0, "MemberID"] == "**"


def test_mask_dataframe_is_noop_when_nothing_is_sensitive():
    query = _make_query(unmasked_columns=["SSN", "MemberID"])
    df = pd.DataFrame({"SSN": ["XXX-XX-1234"], "MemberID": ["MEMBER_TEST_001"], "FileName": ["x"]})
    masked = mask_dataframe(df, query, SOURCE)
    pd.testing.assert_frame_equal(masked, df)
