"""Domain-specific checks for correlation queries, beyond generic registry completeness."""
from app.registry.loader import load_queries


def test_load_count_is_a_summary_metric_counting_distinct_loads():
    query = load_queries()["correlation_file_load_count"]
    assert query.run_on_load is True
    assert query.category == "Overview"
    assert query.source == "correlation_file"
    assert "COUNT(DISTINCT FileID)" in query.sql
