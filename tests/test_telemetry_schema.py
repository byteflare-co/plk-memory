from plk_memory.postgres.schema import (
    TENANT_TABLES,
    decision_events,
    decision_search_links,
    search_events,
)


def test_telemetry_tables_are_tenant_scoped_and_link_each_search_once():
    tenant_names = {table.name for table in TENANT_TABLES}
    assert {"search_events", "decision_events", "decision_search_links"} <= tenant_names
    assert [column.name for column in decision_search_links.primary_key.columns] == [
        "organization_id",
        "search_id",
    ]
    assert [column.name for column in search_events.primary_key.columns] == [
        "organization_id",
        "search_id",
    ]
    assert [column.name for column in decision_events.primary_key.columns] == [
        "organization_id",
        "decision_id",
    ]
    assert "query_preview" in search_events.c
    assert "query_hash" in search_events.c
    assert "used_fact_refs" in decision_events.c
