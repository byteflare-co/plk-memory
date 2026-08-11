from plk_memory.postgres.schema import (
    TENANT_TABLES,
    action_events,
    decision_events,
    decision_search_links,
    intent_events,
    search_events,
)


def test_telemetry_tables_are_tenant_scoped_and_link_each_search_once():
    tenant_names = {table.name for table in TENANT_TABLES}
    assert {
        "search_events",
        "decision_events",
        "decision_search_links",
        "intent_events",
        "action_events",
    } <= tenant_names
    assert [column.name for column in intent_events.primary_key.columns] == [
        "organization_id",
        "trace_id",
    ]
    assert [column.name for column in action_events.primary_key.columns] == [
        "organization_id",
        "event_id",
    ]
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
    assert any(
        constraint.name == "ck_search_events_query_preview_hash_only"
        for constraint in search_events.constraints
    )
    assert "used_fact_refs" in decision_events.c
