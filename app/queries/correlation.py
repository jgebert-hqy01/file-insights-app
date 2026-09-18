"""Query definitions for the correlation domain (file ingestion metadata)."""
from app.registry.models import ParameterControl, ParameterType, QueryDefinition, QueryParameter

last_loaded_at = QueryDefinition(
    name="correlation_file_last_loaded_at",
    title="Last loaded at",
    description="Most recent load timestamp recorded for this file.",
    category="Overview",
    source="correlation_file",
    sql="""
        SELECT MAX(AuditInfo_CreatedAt) AS last_loaded_at
        FROM raw_classic.correlation.file
        WHERE FileName = :filename
    """,
    run_on_load=True,
)

load_count = QueryDefinition(
    name="correlation_file_load_count",
    title="How many times has the file loaded?",
    description="Count of distinct load events recorded for this file.",
    category="Overview",
    source="correlation_file",
    sql="""
        SELECT COUNT(DISTINCT FileID) AS load_count
        FROM raw_classic.correlation.file
        WHERE FileName = :filename
    """,
    run_on_load=True,
)

load_history = QueryDefinition(
    name="correlation_file_load_history",
    title="When did the file load?",
    description="Every load event recorded for this file, optionally narrowed to one partner.",
    category="Load history",
    source="correlation_file",
    sql="""
        SELECT
            BatchID,
            PartnerID,
            AuditInfo_CreatedAt,
            AuditInfo_ModifiedAt,
            AuditInfo_CreatedBy,
            AuditInfo_ModifiedBy
        FROM raw_classic.correlation.file
        WHERE FileName = :filename
            AND (:partner_id IS NULL OR PartnerID = :partner_id)
        ORDER BY AuditInfo_CreatedAt DESC
    """,
    run_on_load=False,
    parameters=[
        QueryParameter(
            name="partner_id",
            label="Partner ID",
            type=ParameterType.INTEGER,
            control=ParameterControl.NUMBER,
            required=False,
        ),
    ],
)
