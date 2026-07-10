"""PostgreSQL contract tests; opt in with ``-m postgres``."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from ulid import ULID

from plk_memory.domain import (
    ActorContext,
    CreateFact,
    FactPayload,
    IndexEntry,
    InvalidateFact,
    QueryScope,
)
from plk_memory.ports import FactMissing, PolicyViolation, RevisionConflict
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.approvals import PostgresApprovalRepository
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
async def worker_database(database):
    role = f"plk_worker_{uuid4().hex}"
    password = uuid4().hex
    async with database.engine.begin() as connection:
        await connection.execute(
            text(f'CREATE ROLE "{role}" LOGIN BYPASSRLS PASSWORD \'{password}\'')
        )
        await connection.execute(text(f'GRANT USAGE ON SCHEMA plk_memory TO "{role}"'))
        await connection.execute(
            text(
                f'GRANT SELECT, INSERT, UPDATE ON plk_memory.outbox_events, '
                f'plk_memory.search_projection_state TO "{role}"'
            )
        )
    admin_url = make_url(os.environ["PLK_TEST_DATABASE_URL"])
    worker_url = admin_url.set(username=role, password=password).render_as_string(
        hide_password=False
    )
    worker = PostgresDatabase(
        worker_url,
        pool_size=4,
        application_name="plk-worker-tests",
        allow_cross_organization=True,
    )
    try:
        yield worker
    finally:
        await worker.close()
        async with database.engine.begin() as connection:
            await connection.execute(text(f'DROP OWNED BY "{role}"'))
            await connection.execute(text(f'DROP ROLE "{role}"'))


@pytest.fixture
def actor() -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        actor_id="service:test-writer",
        actor_type="service",
        roles=frozenset({"writer"}),
    )


async def test_api_database_rejects_worker_transaction(database):
    with pytest.raises(RuntimeError, match="requires a worker database"):
        async with database.worker_transaction():
            pass


def command(fact_id: str, *, supersedes: tuple[str, ...] = ()) -> CreateFact:
    return CreateFact(
        fact_id=fact_id,
        payload=FactPayload(
            kind="knowhow",
            statement=f"statement for {fact_id}",
            why="multi-writer contract test",
            how_to_apply="apply atomically",
            source="session 00000000-0000-0000-0000-000000000001",
            source_type="agent",
            namespace="plk.domain.dev",
            tags=("postgres",),
        ),
        change_reason="contract test",
        supersedes=supersedes,
    )


async def test_create_replays_and_writes_one_outbox_event(database, actor):
    repository = PostgresFactRepository(database)
    create = command(str(ULID()))

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
            select(func.count())
            .select_from(outbox_events)
            .where(outbox_events.c.aggregate_id == create.fact_id)
        )
    assert count == 1


async def test_database_path_enforces_write_policy(database, actor):
    repository = PostgresFactRepository(database)
    create = command(str(ULID())).model_copy(
        update={
            "payload": command(str(ULID())).payload.model_copy(
                update={"kind": "philosophy"}
            )
        }
    )

    with pytest.raises(PolicyViolation, match="philosophy:write"):
        await repository.create(
            actor,
            create,
            expected_superseded_revisions={},
            idempotency_key="policy-rejected",
        )

    secret = command(str(ULID()))
    secret = secret.model_copy(
        update={
            "payload": secret.payload.model_copy(
                update={"body": "AKIA" + "IOSFODNN7EXAMPLE"}
            )
        }
    )
    with pytest.raises(PolicyViolation, match="secret detected"):
        await repository.create(
            actor,
            secret,
            expected_superseded_revisions={},
            idempotency_key="secret-rejected",
        )

    reader = actor.model_copy(update={"roles": frozenset({"reader"})})
    with pytest.raises(PolicyViolation, match="writer role"):
        await repository.create(
            reader,
            command(str(ULID())),
            expected_superseded_revisions={},
            idempotency_key="reader-create-rejected",
        )
    with pytest.raises(PolicyViolation, match="writer role"):
        await repository.invalidate(
            reader,
            InvalidateFact(fact_id=create.fact_id, reason="reader cannot invalidate"),
            expected_revision=1,
            idempotency_key="reader-invalidate-rejected",
        )


async def test_concurrent_invalidate_uses_expected_revision(database, actor):
    repository = PostgresFactRepository(database)
    fact_id = str(ULID())
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
    old_id = str(ULID())
    new_id = str(ULID())
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


async def test_outbox_lease_ack_and_projection_version_guard(
    database, worker_database, actor
):
    repository = PostgresFactRepository(database)
    fact_id = str(ULID())
    created = await repository.create(
        actor,
        command(fact_id),
        expected_superseded_revisions={},
        idempotency_key="outbox-create",
    )
    feed = PostgresChangeFeed(worker_database)
    events = await feed.claim(
        consumer="worker-1",
        limit=1000,
        lease_until=datetime.now(UTC) + timedelta(minutes=1),
    )
    own_claim = next(
        claim for claim in events if claim.change.event_id == created.event_id
    )
    assert own_claim.change.revision == 1
    await feed.ack([own_claim])

    projection = PostgresIndexStateRepository(worker_database, backend="test-index")
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
    newer = first.model_copy(
        update={
            "indexed_revision": 2,
            "content_hash": "c" * 64,
            "last_event_id": uuid4(),
            "indexed_at": now + timedelta(seconds=1),
        }
    )
    assert await projection.put_if_newer(first) is True
    assert await projection.put_if_newer(newer) is True
    assert await projection.put_if_newer(stale) is False
    assert (await projection.get(str(actor.organization_id), fact_id)) == newer


async def test_expired_worker_cannot_ack_reclaimed_event(
    database, worker_database, actor
):
    repository = PostgresFactRepository(database)
    created = await repository.create(
        actor,
        command(str(ULID())),
        expected_superseded_revisions={},
        idempotency_key="lease-fencing",
    )
    feed = PostgresChangeFeed(worker_database)
    first_batch = await feed.claim(
        consumer="same-worker-name",
        limit=1000,
        lease_until=datetime.now(UTC) + timedelta(minutes=1),
    )
    stale_claim = next(
        claim for claim in first_batch if claim.change.event_id == created.event_id
    )
    async with worker_database.worker_transaction() as session:
        await session.execute(
            update(outbox_events)
            .where(outbox_events.c.event_id == created.event_id)
            .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
    second_batch = await feed.claim(
        consumer="same-worker-name",
        limit=1000,
        lease_until=datetime.now(UTC) + timedelta(minutes=1),
    )
    current_claim = next(
        claim for claim in second_batch if claim.change.event_id == created.event_id
    )
    assert stale_claim.lease_token != current_claim.lease_token
    with pytest.raises(RuntimeError, match="no longer owned"):
        await feed.ack([stale_claim])
    await feed.ack([current_claim])


async def test_outbox_claims_one_revision_per_fact_in_order(
    database, worker_database, actor
):
    repository = PostgresFactRepository(database)
    fact_id = str(ULID())
    created = await repository.create(
        actor,
        command(fact_id),
        expected_superseded_revisions={},
        idempotency_key="ordered-create",
    )
    invalidated = await repository.invalidate(
        actor,
        InvalidateFact(fact_id=fact_id, reason="superseded by ordered test"),
        expected_revision=1,
        idempotency_key="ordered-invalidate",
    )
    feed = PostgresChangeFeed(worker_database)

    first = await feed.claim(
        consumer="ordered-worker",
        limit=1000,
        lease_until=datetime.now(UTC) + timedelta(minutes=1),
    )
    own_first = [claim for claim in first if claim.change.fact_id == fact_id]
    assert [claim.change.event_id for claim in own_first] == [created.event_id]
    await feed.ack(own_first)

    second = await feed.claim(
        consumer="ordered-worker",
        limit=1000,
        lease_until=datetime.now(UTC) + timedelta(minutes=1),
    )
    own_second = [claim for claim in second if claim.change.fact_id == fact_id]
    assert [claim.change.event_id for claim in own_second] == [invalidated.event_id]
    await feed.ack(own_second)


async def test_outbox_moves_terminal_failure_to_dead_letter(
    database, worker_database, actor
):
    repository = PostgresFactRepository(database)
    created = await repository.create(
        actor,
        command(str(ULID())),
        expected_superseded_revisions={},
        idempotency_key="dead-letter-create",
    )
    feed = PostgresChangeFeed(worker_database, max_attempts=1)
    claims = await feed.claim(
        consumer="dead-letter-worker",
        limit=1000,
        lease_until=datetime.now(UTC) + timedelta(minutes=1),
    )
    own = next(claim for claim in claims if claim.change.event_id == created.event_id)
    await feed.fail(
        own,
        error="permanent graph failure",
        retry_at=datetime.now(UTC),
    )

    async with worker_database.worker_transaction() as session:
        dead_lettered_at = await session.scalar(
            select(outbox_events.c.dead_lettered_at).where(
                outbox_events.c.event_id == created.event_id
            )
        )
    assert dead_lettered_at is not None


async def test_rls_hides_and_rejects_cross_organization_rows(database, actor):
    admin_repository = PostgresFactRepository(database)
    other = actor.model_copy(update={"organization_id": uuid4()})
    shared_id = str(ULID())
    await admin_repository.create(
        other,
        command(shared_id),
        expected_superseded_revisions={},
        idempotency_key="rls-other",
    )

    role = f"plk_test_{uuid4().hex}"
    password = uuid4().hex
    async with database.engine.begin() as connection:
        await connection.execute(
            text(f'CREATE ROLE "{role}" LOGIN NOBYPASSRLS PASSWORD \'{password}\'')
        )
        await connection.execute(text(f'GRANT USAGE ON SCHEMA plk_memory TO "{role}"'))
        await connection.execute(
            text(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES '
                f'IN SCHEMA plk_memory TO "{role}"'
            )
        )
    admin_url = make_url(os.environ["PLK_TEST_DATABASE_URL"])
    app_url = admin_url.set(username=role, password=password).render_as_string(
        hide_password=False
    )
    app_database = PostgresDatabase(app_url, pool_size=2, application_name="plk-rls-test")
    try:
        app_repository = PostgresFactRepository(app_database)
        await app_repository.create(
            actor,
            command(shared_id),
            expected_superseded_revisions={},
            idempotency_key="rls-own",
        )
        own_scope = QueryScope(
            organization_id=actor.organization_id, actor_id=actor.actor_id
        )
        visible = await app_repository.get(own_scope, shared_id)
        assert visible.organization_id == actor.organization_id

        with pytest.raises(DBAPIError):
            async with app_database.transaction(actor.organization_id) as session:
                await session.execute(
                    text(
                        "INSERT INTO plk_memory.idempotency_records "
                        "(organization_id, idempotency_key, request_hash, operation, resource_type) "
                        "VALUES (:other_org, 'cross-org', :hash, 'test', 'fact')"
                    ),
                    {"other_org": str(other.organization_id), "hash": "0" * 64},
                )
    finally:
        await app_database.close()
        async with database.engine.begin() as connection:
            await connection.execute(text(f'DROP OWNED BY "{role}"'))
            await connection.execute(text(f'DROP ROLE "{role}"'))


async def test_revision_pinned_promotion_approval_is_atomic(database, actor):
    facts = PostgresFactRepository(database)
    approvals = PostgresApprovalRepository(database)
    fact_id = str(ULID())
    await facts.create(
        actor,
        command(fact_id),
        expected_superseded_revisions={},
        idempotency_key="promotion-fact",
    )
    proposed = await approvals.propose(
        actor,
        fact_id,
        reason="this rule is useful across all domains",
        idempotency_key="promotion-propose",
    )
    replay = await approvals.propose(
        actor,
        fact_id,
        reason="this rule is useful across all domains",
        idempotency_key="promotion-propose",
    )
    assert replay.request_id == proposed.request_id

    reviewer = actor.model_copy(update={"roles": frozenset({"reviewer"})})
    result = await approvals.decide(
        reviewer,
        str(proposed.request_id),
        decision="approved",
        rationale="reviewed and confirmed as shared knowledge",
        expected_revision=1,
        idempotency_key="promotion-approve",
    )
    assert result.request.status == "approved"
    assert result.fact_revision == 2
    assert result.event_id is not None
    scope = QueryScope(organization_id=actor.organization_id, actor_id=actor.actor_id)
    promoted = await facts.get(scope, fact_id)
    assert promoted.payload.namespace == "plk.shared"
    assert promoted.revision == 2


async def test_changed_fact_marks_pending_promotion_stale(database, actor):
    facts = PostgresFactRepository(database)
    approvals = PostgresApprovalRepository(database)
    fact_id = str(ULID())
    await facts.create(
        actor,
        command(fact_id),
        expected_superseded_revisions={},
        idempotency_key="stale-promotion-fact",
    )
    proposed = await approvals.propose(
        actor,
        fact_id,
        reason="candidate for shared knowledge review",
        idempotency_key="stale-promotion-propose",
    )
    await facts.invalidate(
        actor,
        InvalidateFact(fact_id=fact_id, reason="changed before human review"),
        expected_revision=1,
        idempotency_key="stale-promotion-change",
    )
    reviewer = actor.model_copy(update={"roles": frozenset({"reviewer"})})
    result = await approvals.decide(
        reviewer,
        str(proposed.request_id),
        decision="approved",
        rationale="attempt approval of the original revision",
        expected_revision=1,
        idempotency_key="stale-promotion-decision",
    )
    assert result.request.status == "stale"
    assert result.fact_revision is None
