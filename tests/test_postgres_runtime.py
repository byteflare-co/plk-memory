import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update

from plk_memory.app import create_app
from plk_memory.auth import current_actor
from plk_memory.domain import ActorContext
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.graph_adapter import PostgresGraphSearchIndex
from plk_memory.postgres.outbox import (
    PostgresChangeFeed,
    PostgresIndexStateRepository,
)
from plk_memory.postgres.repository import PostgresFactRepository
from plk_memory.postgres.schema import search_events
from plk_memory.postgres.worker import PostgresIndexWorker
from plk_memory.settings import Settings
from tests.fakes import FakeGraphIndex

pytestmark = pytest.mark.postgres


async def test_postgres_runtime_write_worker_search_invalidate_roundtrip():
    database_url = os.environ.get("PLK_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PLK_TEST_DATABASE_URL is not configured")
    organization_id = uuid4()
    settings = Settings(
        storage_backend="postgres",
        database_url=database_url,
        worker_database_url=database_url,
        default_organization_id=str(organization_id),
        tokens={"test-token": "runtime-test"},
        usage_raw_query_retention_days=30,
        outbox_batch_size=1,
        worker_consumer_name=f"runtime-worker-{uuid4()}",
    )
    graph = FakeGraphIndex()
    app = create_app(settings=settings, graph=graph)
    services = app.state.services
    worker_database = PostgresDatabase(
        database_url,
        pool_size=2,
        allow_cross_organization=True,
        application_name="plk-runtime-test-worker",
    )
    worker_index = PostgresGraphSearchIndex(
        graph=graph,
        api_database=worker_database,
        worker_database=worker_database,
        settings=settings,
    )
    index_state = PostgresIndexStateRepository(
        worker_database, backend="graphiti"
    )
    worker = PostgresIndexWorker(
        repository=PostgresFactRepository(worker_database),
        change_feed=PostgresChangeFeed(worker_database),
        index_state=index_state,
        search_index=worker_index,
        settings=settings,
    )
    actor = ActorContext(
        organization_id=organization_id,
        actor_id="service:runtime-test",
        actor_type="service",
        roles=frozenset({"writer"}),
    )
    token = current_actor.set(actor)

    async def project_until(org_id, fact_id, revision):
        for _ in range(1000):
            state = await index_state.get(str(org_id), fact_id)
            if state is not None and state.indexed_revision >= revision:
                return
            await worker.run_once()
        raise AssertionError(f"projection did not reach revision {revision}")

    try:
        await services.check_database()
        await services.start()
        added = await services.tool_add(
            namespace="plk.domain.dev",
            kind="knowhow",
            statement="PostgreSQL runtime roundtrip keeps current knowledge canonical",
            why="multiple writers require one transactionally consistent source of truth",
            how_to_apply="write to PostgreSQL and project through the outbox worker",
            source="session 00000000-0000-0000-0000-000000000001",
            idempotency_key="runtime-roundtrip-add",
        )
        assert "error" not in added
        replayed_add = await services.tool_add(
            namespace="plk.domain.dev",
            kind="knowhow",
            statement="PostgreSQL runtime roundtrip keeps current knowledge canonical",
            why="multiple writers require one transactionally consistent source of truth",
            how_to_apply="write to PostgreSQL and project through the outbox worker",
            source="session 00000000-0000-0000-0000-000000000001",
            idempotency_key="runtime-roundtrip-add",
        )
        assert replayed_add["replayed"] is True
        await project_until(actor.organization_id, added["fact_id"], 1)

        search = await services.tool_search("PostgreSQL runtime roundtrip")
        assert [hit["fact_id"] for hit in search["hits"]] == [added["fact_id"]]
        decision = await services.tool_record_decision(
            decision_id=f"runtime-decision-{organization_id}",
            search_ids=[search["search_id"]],
            used_fact_ids=[added["fact_id"]],
            effect="changed_action",
        )
        assert decision["recorded"] is True
        replay = await services.tool_record_decision(
            decision_id=f"runtime-decision-{organization_id}",
            search_ids=[search["search_id"]],
            used_fact_ids=[added["fact_id"]],
            effect="changed_action",
        )
        assert replay["replayed"] is True
        usage = await services.ui_usage_records()
        assert any(
            row.get("decision_id") == f"runtime-decision-{organization_id}"
            and row.get("used_fact_ids") == [added["fact_id"]]
            for row in usage
        )
        search_usage = next(
            row for row in usage if row.get("search_id") == search["search_id"]
        )
        assert search_usage["query"] == "PostgreSQL runtime roundtrip"
        assert len(search_usage["query_hash"]) == 64

        other_actor = actor.model_copy(update={"organization_id": uuid4()})
        other_token = current_actor.set(other_actor)
        try:
            other = await services.tool_add(
                namespace="plk.domain.dev",
                kind="knowhow",
                statement="PostgreSQL runtime roundtrip remains tenant isolated",
                why="physical graph partitions must include the organization identifier",
                how_to_apply="search only the current organization graph partitions",
                source="session 00000000-0000-0000-0000-000000000001",
                idempotency_key="runtime-roundtrip-add",
            )
            assert "error" not in other
        finally:
            current_actor.reset(other_token)
        await project_until(other_actor.organization_id, other["fact_id"], 1)
        own_search = await services.tool_search("PostgreSQL runtime roundtrip")
        assert [hit["fact_id"] for hit in own_search["hits"]] == [added["fact_id"]]

        invalidated = await services.tool_invalidate(
            added["fact_id"],
            "superseded during runtime roundtrip",
            expected_revision=1,
            idempotency_key="runtime-roundtrip-invalidate",
        )
        assert invalidated["revision"] == 2
        replayed_invalidation = await services.tool_invalidate(
            added["fact_id"],
            "superseded during runtime roundtrip",
            idempotency_key="runtime-roundtrip-invalidate",
        )
        assert replayed_invalidation["replayed"] is True
        await project_until(actor.organization_id, added["fact_id"], 2)
        search = await services.tool_search("PostgreSQL runtime roundtrip")
        assert search["hits"] == []

        # A restart must resume retention cleanup for existing rows even when
        # that tenant performs no later search or metrics read.
        original_search_id = search_usage["search_id"]
        await services.close()
        async with worker_database.worker_transaction() as session:
            await session.execute(
                update(search_events)
                .where(
                    search_events.c.organization_id == organization_id,
                    search_events.c.search_id == original_search_id,
                )
                .values(created_at=datetime.now(UTC) - timedelta(days=31))
            )
        restarted_app = create_app(settings=settings, graph=FakeGraphIndex())
        services = restarted_app.state.services
        await services.check_database()
        await services.start()
        restarted_usage = await services.ui_usage_records()
        restarted_search = next(
            row
            for row in restarted_usage
            if row.get("search_id") == original_search_id
        )
        assert restarted_search["query"] is None
        assert len(restarted_search["query_hash"]) == 64
    finally:
        current_actor.reset(token)
        await services.close()
        await worker_database.close()
