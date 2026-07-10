import os
from uuid import uuid4

import pytest

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
        outbox_batch_size=1000,
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
    worker = PostgresIndexWorker(
        repository=PostgresFactRepository(worker_database),
        change_feed=PostgresChangeFeed(worker_database),
        index_state=PostgresIndexStateRepository(
            worker_database, backend="graphiti"
        ),
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
        assert (await worker.run_once())["succeeded"] >= 1

        search = await services.tool_search("PostgreSQL runtime roundtrip")
        assert [hit["fact_id"] for hit in search["hits"]] == [added["fact_id"]]

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
        assert (await worker.run_once())["succeeded"] >= 1
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
        assert (await worker.run_once())["succeeded"] >= 1
        search = await services.tool_search("PostgreSQL runtime roundtrip")
        assert search["hits"] == []
    finally:
        current_actor.reset(token)
        await services.close()
        await worker_database.close()
