"""Source definitions for the correlation domain (file ingestion metadata)."""
from app.registry.models import ColumnDefinition, SourceDefinition

file = SourceDefinition(
    name="correlation_file",
    fully_qualified_view="raw_classic.correlation.file",
    filename_column="FileName",
    columns=[
        ColumnDefinition(name="FileID", data_type="int"),
        ColumnDefinition(name="FileName", data_type="string"),
        ColumnDefinition(name="BatchID", data_type="int"),
        ColumnDefinition(name="PartnerID", data_type="int"),
        ColumnDefinition(name="AuditInfo_CreatedAt", data_type="timestamp"),
        ColumnDefinition(name="AuditInfo_ModifiedAt", data_type="timestamp"),
        ColumnDefinition(name="AuditInfo_CreatedBy", data_type="string"),
        ColumnDefinition(name="AuditInfo_ModifiedBy", data_type="string"),
        ColumnDefinition(name="hvr_timestamp", data_type="timestamp"),
    ],
    sensitive_columns=[],
    description="One row per file load batch recorded by the correlation ingestion pipeline.",
)
