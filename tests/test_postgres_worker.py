"""fake（in-memory）実装ベースのため実 DB 不要。

``-m postgres`` marker の付く実 DB 統合テストは test_postgres_repository.py /
test_postgres_runtime.py を参照。
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from plk_memory.domain import (
    ClaimedChange,
    FactRecord,
    IndexEntry,
    KnowledgeChanged,
)
from plk_memory.postgres.worker import PostgresIndexWorker
from plk_memory.settings import Settings

ORG = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 7, 11, tzinfo=UTC)


def fact(*, revision=2, status="active"):
    return FactRecord.model_validate(
        {
            "id": "01JZC2V7E8B3F4G5H6J7K8M9N0",
            "organization_id": ORG,
            "revision": revision,
            "payload": {
                "kind": "knowhow",
                "statement": "PostgreSQL current head is canonical",
                "why": "outbox events are level-triggered wake-up signals",
                "how_to_apply": "always rehydrate before projecting",
                "source": "session 00000000-0000-0000-0000-000000000001",
                "source_type": "agent",
                "namespace": "plk.domain.dev",
            },
            "status": status,
            "invalidation_reason": "obsolete" if status == "invalidated" else None,
            "created_by": "service:test",
            "created_at": NOW,
            "updated_by": "service:test",
            "updated_at": NOW,
        }
    )


def claim(*, revision=1, attempts=1):
    event_id = uuid4()
    return ClaimedChange(
        change=KnowledgeChanged(
            event_id=event_id,
            organization_id=ORG,
            fact_id=fact().id,
            revision=revision,
            operation="created",
            occurred_at=NOW,
        ),
        consumer="test-worker",
        lease_token=uuid4(),
        attempts=attempts,
    )


class Repository:
    def __init__(self, current):
        self.current = current

    async def get(self, scope, fact_id):
        return self.current


class Feed:
    def __init__(self, claims, *, fail_raises=False):
        self.claims = tuple(claims)
        self.fail_raises = fail_raises
        self.acked = []
        self.failed = []
        self.renewed = []

    async def claim(self, **kwargs):
        return self.claims

    async def ack(self, claims):
        self.acked.extend(claims)

    async def renew(self, claim, **kwargs):
        self.renewed.append((claim, kwargs))

    async def fail(self, claim, **kwargs):
        if self.fail_raises:
            raise RuntimeError("lease already reclaimed")
        self.failed.append((claim, kwargs))


class State:
    def __init__(self, old=None):
        self.old = old
        self.put = []

    async def get(self, organization_id, fact_id):
        return self.old

    async def put_if_newer(self, entry):
        self.put.append(entry)
        self.old = entry
        return True


class Index:
    ready = True

    def __init__(self, *, fail=False):
        self.fail = fail
        self.upserts = []

    async def upsert(self, fact, old=None):
        if self.fail:
            raise RuntimeError("index unavailable")
        self.upserts.append((fact, old))
        return IndexEntry(
            organization_id=fact.organization_id,
            fact_id=fact.id,
            indexed_revision=fact.revision,
            content_hash="a" * 64,
            indexed_at=NOW,
        )


def worker(current, claims, *, old=None, fail=False, fail_raises=False):
    feed = Feed(claims, fail_raises=fail_raises)
    state = State(old)
    index = Index(fail=fail)
    settings = Settings.model_construct(
        worker_consumer_name="test-worker",
        outbox_batch_size=1,
        outbox_lease_seconds=60,
        outbox_retry_base_seconds=0.01,
        outbox_retry_max_seconds=1.0,
    )
    service = PostgresIndexWorker(
        repository=Repository(current),
        change_feed=feed,
        index_state=state,
        search_index=index,
        settings=settings,
    )
    return service, feed, state, index


async def test_old_event_projects_current_head_and_acks():
    current = fact(revision=2)
    wakeup = claim(revision=1)
    service, feed, state, index = worker(current, [wakeup])

    result = await service.run_once()

    assert result == {"claimed": 1, "succeeded": 1, "failed": 0}
    assert index.upserts[0][0].revision == 2
    assert state.put[0].indexed_revision == 2
    assert state.put[0].last_event_id == wakeup.change.event_id
    assert feed.acked == [wakeup]


async def test_projection_at_current_revision_skips_external_index():
    current = fact(revision=2)
    old = IndexEntry(
        organization_id=ORG,
        fact_id=current.id,
        indexed_revision=2,
        content_hash="a" * 64,
        indexed_at=NOW,
    )
    service, feed, state, index = worker(current, [claim(revision=1)], old=old)

    await service.run_once()

    assert index.upserts == []
    assert state.put == []
    assert len(feed.acked) == 1


async def test_index_failure_releases_claim_for_retry():
    wakeup = claim(attempts=3)
    service, feed, state, index = worker(fact(), [wakeup], fail=True)

    result = await service.run_once()

    assert result["failed"] == 1
    assert feed.acked == []
    assert feed.failed[0][0] == wakeup
    assert "index unavailable" in feed.failed[0][1]["error"]


async def test_stale_lease_during_failure_does_not_kill_worker():
    service, feed, state, index = worker(
        fact(), [claim()], fail=True, fail_raises=True
    )

    result = await service.run_once()

    assert result == {"claimed": 1, "succeeded": 0, "failed": 1}


async def test_long_projection_renews_lease():
    service, feed, _state, _index = worker(fact(), [claim()])
    service.settings = service.settings.model_copy(
        update={"outbox_lease_seconds": 0.1}
    )
    heartbeat = asyncio.create_task(service._heartbeat(feed.claims[0]))
    await asyncio.sleep(0.12)
    heartbeat.cancel()
    with pytest.raises(asyncio.CancelledError):
        await heartbeat
    assert len(feed.renewed) == 1
