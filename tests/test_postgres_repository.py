"""PostgreSQL contract tests; opt in with ``-m postgres``."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from plk_memory.domain import (
    ActorContext,
    CreateFact,
    FactPayload,
    IndexEntry,
    InvalidateFact,
    QueryScope,
)
from plk_memory.ports import FactMissing, RevisionConflict
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.outbox import PostgresChangeFeed, PostgresIndexStateRepository
from plk_memory.postgres.repository import PostgresFactRepository
from plk_memory.postgres.schema import outbox_events

pytestmark = pytest.mark.postgres


@pytest.fixture
async def database():
    url = os.environ.get("PLK_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PLK_TEST_DATABASE_URL is not configured")
    database = PostgresDatabase(url, pool_size=8, application_name="plk-tests")
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def actor() -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        actor_id="service:test-writer",
        actor_type="service",
        roles=frozenset({"writer"}),
    )


def command(fact_id: str, *, supersedes: tuple[str, ...] = ()) -> CreateFact:
    return CreateFact(
        fact_id=fact_id,
        payload=FactPayload(
            kind="knowhow",
            statement=f"statement for {fact_id}",
            why="multi-writer contract test",
            how_to_apply="apply atomically",
            source="tests/test_postgres_repository.py",
            source_type="agent",
            namespace="plk.domain.dev",
            tags=("postgres",),
        ),
        change_reason="contract test",
        supersedes=supersedes,
    )


async def test_create_replays_and_writes_one_outbox_event(database, actor):
    repository = PostgresFactRepository(database)
    create = command(f"01TEST{uuid4().hex[:12].upper()}")

    first, replay = await asyncio.gather(
        repository.create(
            actor,
            create,
            expected_superseded_revisions={},
            idempotency_key="same-request",
        ),
        repository.create(
            actor,
            create,
            expected_superseded_revisions={},
            idempotency_key="same-request",
        ),
    )

    assert {first.replayed, replay.replayed} == {False, True}
    assert first.fact_id == replay.fact_id
    assert first.event_id == replay.event_id
    scope = QueryScope(organization_id=actor.organization_id, actor_id=actor.actor_id)
    assert (await repository.get(scope, create.fact_id)).revision == 1
    async with database.transaction(actor.organization_id) as session:
        count = await session.scalar(
            select(func.count()).select_from(outbox_events).where(
                outbox_events.c.aggregate_id == create.fact_id
            )
        )
    assert count == 1


async def test_concurrent_invalidate_uses_expected_revision(database, actor):
    repository = PostgresFactRepository(database)
    fact_id = f"01TEST{uuid4().hex[:12].upper()}"
    await repository.create(
        actor,
        command(fact_id),
        expected_superseded_revisions={},
        idempotency_key="create",
    )

    results = await asyncio.gather(
        repository.invalidate(
            actor,
            InvalidateFact(fact_id=fact_id, reason="first"),
            expected_revision=1,
            idempotency_key="invalidate-1",
        ),
        repository.invalidate(
            actor,
            InvalidateFact(fact_id=fact_id, reason="second"),
            expected_revision=1,
            idempotency_key="invalidate-2",
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, RevisionConflict) for result in results) == 1, results
    scope = QueryScope(organization_id=actor.organization_id, actor_id=actor.actor_id)
    current = await repository.get(scope, fact_id)
    assert current.status == "invalidated"
    assert current.revision == 2
    assert len((await repository.history(scope, fact_id)).revisions) == 2


async def test_supersede_is_atomic_and_organization_scoped(database, actor):
    repository = PostgresFactRepository(database)
    old_id = f"01TEST{uuid4().hex[:12].upper()}"
    new_id = f"01TEST{uuid4().hex[:12].upper()}"
    await repository.create(
        actor,
        command(old_id),
        expected_superseded_revisions={},
        idempotency_key="old",
    )
    await repository.create(
        actor,
        command(new_id, supersedes=(old_id,)),
        expected_superseded_revisions={old_id: 1},
        idempotency_key="new",
    )

    own_scope = QueryScope(
        organization_id=actor.organization_id, actor_id=actor.actor_id
    )
    assert (await repository.get(own_scope, old_id)).status == "invalidated"
    history = await repository.history(own_scope, new_id)
    assert history.supersedes == (old_id,)

    other_scope = QueryScope(organization_id=uuid4(), actor_id="other")
    with pytest.raises(FactMissing, match="fact does not exist"):
        await repository.get(other_scope, new_id)


async def test_outbox_lease_ack_and_projection_version_guard(database, actor):
    repository = PostgresFactRepository(database)
    fact_id = f"01TEST{uuid4().hex[:12].upper()}"
    created = await repository.create(
        actor,
        command(fact_id),
        expected_superseded_revisions={},
        idempotency_key="outbox-create",
    )
    feed = PostgresChangeFeed(database)
    events = await feed.claim(
        consumer="worker-1",
        limit=1000,
        lease_until=datetime.now(UTC) + timedelta(minutes=1),
    )
    own_event = next(event for event in events if event.event_id == created.event_id)
    assert own_event.revision == 1
    await feed.ack([str(own_event.event_id)])

    projection = PostgresIndexStateRepository(database, backend="test-index")
    now = datetime.now(UTC)
    first = IndexEntry(
        organization_id=actor.organization_id,
        fact_id=fact_id,
        indexed_revision=1,
        content_hash="a" * 64,
        last_event_id=created.event_id,
        indexed_at=now,
    )
    stale = first.model_copy(
        update={"content_hash": "b" * 64, "indexed_at": now - timedelta(seconds=1)}
    )
    assert await projection.put_if_newer(first) is True
    assert await projection.put_if_newer(stale) is False
    assert (await projection.get(str(actor.organization_id), fact_id)) == first


async def test_rls_hides_and_rejects_cross_organization_rows(database, actor):
    repository = PostgresFactRepository(database)
    other = actor.model_copy(update={"organization_id": uuid4()})
    shared_id = f"01TEST{uuid4().hex[:12].upper()}"
    await repository.create(
        actor,
        command(shared_id),
        expected_superseded_revisions={},
        idempotency_key="rls-own",
    )
    await repository.create(
        other,
        command(shared_id),
        expected_superseded_revisions={},
        idempotency_key="rls-other",
    )

    role = f"plk_test_{uuid4().hex}"
    async with database.engine.begin() as connection:
        await connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOBYPASSRLS'))
        await connection.execute(text(f'GRANT USAGE ON SCHEMA plk_memory TO "{role}"'))
        await connection.execute(
            text(f'GRANT SELECT ON plk_memory.knowledge_facts TO "{role}"')
        )
        await connection.execute(
            text(f'GRANT INSERT ON plk_memory.idempotency_records TO "{role}"')
        )
    try:
        async with database.engine.begin() as connection:
            await connection.execute(text(f'SET LOCAL ROLE "{role}"'))
            await connection.execute(
                text("SELECT set_config('app.current_organization_id', :org, true)"),
                {"org": str(actor.organization_id)},
            )
            visible = (
                await connection.execute(
                    text(
                        "SELECT organization_id FROM plk_memory.knowledge_facts "
                        "WHERE fact_id = :fact_id"
                    ),
                    {"fact_id": shared_id},
                )
            ).scalars().all()
            assert visible == [actor.organization_id]

        with pytest.raises(DBAPIError):
            async with database.engine.begin() as connection:
                await connection.execute(text(f'SET LOCAL ROLE "{role}"'))
                await connection.execute(
                    text("SELECT set_config('app.current_organization_id', :org, true)"),
                    {"org": str(actor.organization_id)},
                )
                await connection.execute(
                    text(
                        "INSERT INTO plk_memory.idempotency_records "
                        "(organization_id, idempotency_key, request_hash, operation, resource_type) "
                        "VALUES (:other_org, 'cross-org', :hash, 'test', 'fact')"
                    ),
                    {"other_org": str(other.organization_id), "hash": "0" * 64},
                )
    finally:
        async with database.engine.begin() as connection:
            await connection.execute(text(f'DROP OWNED BY "{role}"'))
            await connection.execute(text(f'DROP ROLE "{role}"'))
