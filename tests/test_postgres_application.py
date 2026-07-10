from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from ulid import ULID

from plk_memory.domain import (
    ActorContext,
    FactHistory,
    FactRecord,
    FactRevision,
    IndexCandidate,
    IndexEntry,
    QueryScope,
    SearchQuery,
    WriteResult,
)
from plk_memory.ports import FactMissing, RevisionConflict
from plk_memory.postgres.application import PostgresAppServices
from plk_memory.settings import Settings


ORG = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 7, 10, tzinfo=UTC)


def record(
    fact_id: str,
    *,
    statement: str = "current database statement",
    namespace: str = "plk.domain.dev",
    status: str = "active",
    revision: int = 2,
) -> FactRecord:
    return FactRecord.model_validate(
        {
            "id": fact_id,
            "organization_id": ORG,
            "revision": revision,
            "payload": {
                "kind": "knowhow",
                "statement": statement,
                "why": "database is canonical",
                "how_to_apply": "rehydrate every candidate",
                "source": "session 00000000-0000-0000-0000-000000000001",
                "source_type": "agent",
                "namespace": namespace,
            },
            "status": status,
            "created_by": "service:test",
            "created_at": NOW,
            "updated_by": "service:test",
            "updated_at": NOW,
        }
    )


class FakeRepository:
    def __init__(self, records: list[FactRecord] | None = None) -> None:
        self.records = {item.id: item for item in records or []}
        self.create_calls = []
        self.invalidate_calls = []

    async def list(self, scope, filters):
        return tuple(self.records.values())

    async def get(self, scope, fact_id):
        if fact_id not in self.records:
            raise FactMissing(fact_id)
        return self.records[fact_id]

    async def get_many(self, scope, fact_ids):
        return tuple(self.records[item] for item in fact_ids if item in self.records)

    async def create(
        self, actor, command, *, expected_superseded_revisions, idempotency_key
    ):
        self.create_calls.append(
            (actor, command, expected_superseded_revisions, idempotency_key)
        )
        return WriteResult(
            fact_id=command.fact_id,
            revision=1,
            replayed=False,
            event_id=uuid4(),
        )

    async def invalidate(
        self, actor, command, *, expected_revision, idempotency_key
    ):
        self.invalidate_calls.append(
            (actor, command, expected_revision, idempotency_key)
        )
        return WriteResult(
            fact_id=command.fact_id,
            revision=expected_revision + 1,
            replayed=False,
            event_id=uuid4(),
        )

    async def history(self, scope, fact_id):
        current = await self.get(scope, fact_id)
        revision = FactRevision(
            fact_id=fact_id,
            organization_id=ORG,
            revision=current.revision,
            payload=current.payload,
            status=current.status,
            change_reason="database revision",
            actor_id="service:test",
            actor_type="service",
            created_at=NOW,
        )
        return FactHistory(
            fact_id=fact_id,
            current_revision=current.revision,
            revisions=(revision,),
            supersedes=("OLD",),
        )


class FakeIndex:
    def __init__(self, candidates: list[IndexCandidate], *, ready: bool = True) -> None:
        self.candidates = candidates
        self._ready = ready
        self.last_query: SearchQuery | None = None

    @property
    def ready(self):
        return self._ready

    async def start(self):
        return None

    async def upsert(self, fact, old=None):
        return IndexEntry.model_construct()

    async def delete(self, organization_id, fact_id, old):
        return None

    async def search(self, query):
        self.last_query = query
        return tuple(self.candidates)

    async def clear(self, organization_id):
        return None


def services(repository: FakeRepository, index: FakeIndex) -> PostgresAppServices:
    actor = ActorContext(
        organization_id=ORG,
        actor_id="service:test",
        actor_type="service",
        roles=frozenset({"writer"}),
    )
    scope = QueryScope(organization_id=ORG, actor_id=actor.actor_id)
    return PostgresAppServices(
        repository=repository,
        search_index=index,
        actor_provider=lambda: actor,
        scope_provider=lambda: scope,
        settings=Settings.model_construct(),
    )


async def test_search_rehydrates_current_database_revision_and_order():
    fresh = record("FRESH", statement="new statement", revision=3)
    quarantined = record("Q", namespace="plk.quarantine")
    repository = FakeRepository([fresh, quarantined])
    index = FakeIndex(
        [
            IndexCandidate(fact_id="MISSING", indexed_revision=1, score=0.9),
            IndexCandidate(fact_id="Q", indexed_revision=1, score=0.8),
            IndexCandidate(fact_id="FRESH", indexed_revision=1, score=0.7),
        ]
    )

    result = await services(repository, index).tool_search("stale index text")

    assert result["degraded"] is False
    assert result["hits"] == [
        {
            "fact_id": "FRESH",
            "statement": "new statement",
            "namespace": "plk.domain.dev",
            "kind": "knowhow",
            "status": "active",
            "path": None,
            "fact_text": "new statement",
            "created_at": NOW.isoformat(),
            "revision": 3,
            "score": 0.7,
        }
    ]
    assert index.last_query is not None
    assert index.last_query.filters.limit == 50


async def test_add_passes_idempotency_and_expected_superseded_revision():
    old = record("OLD", revision=4)
    repository = FakeRepository([old])
    app = services(repository, FakeIndex([]))

    result = await app.tool_add(
        namespace="plk.domain.dev",
        kind="knowhow",
        statement="PostgreSQL is the source of truth",
        why="multiple writers need transactions",
        how_to_apply="write through the repository",
        source="session 00000000-0000-0000-0000-000000000001",
        supersedes=["OLD"],
        expected_revision=4,
        idempotency_key="request-1",
    )

    assert "fact_id" in result and len(result["fact_id"]) == len(str(ULID()))
    assert result["idempotency_key"] == "request-1"
    _, command, expected, key = repository.create_calls[0]
    assert command.supersedes == ("OLD",)
    assert expected == {"OLD": 4}
    assert key == "request-1"

    await app.tool_add(
        namespace="plk.domain.dev",
        kind="knowhow",
        statement="PostgreSQL is the source of truth",
        why="multiple writers need transactions",
        how_to_apply="write through the repository",
        source="session 00000000-0000-0000-0000-000000000001",
        supersedes=["OLD"],
        expected_revision=4,
        idempotency_key="request-1",
    )
    assert repository.create_calls[1][1].fact_id == command.fact_id


async def test_invalidate_uses_explicit_expected_revision():
    current = record("F1", revision=8)
    repository = FakeRepository([current])
    result = await services(repository, FakeIndex([])).tool_invalidate(
        "F1",
        "superseded by an official procedure",
        expected_revision=7,
        idempotency_key="invalidate-1",
    )

    assert result["revision"] == 8
    assert repository.invalidate_calls[0][2:] == (7, "invalidate-1")


async def test_revision_conflict_is_retryable_and_structured():
    class ConflictRepository(FakeRepository):
        async def invalidate(
            self, actor, command, *, expected_revision, idempotency_key
        ):
            raise RevisionConflict(command.fact_id, expected_revision, 9)

    result = await services(
        ConflictRepository([record("F1")]), FakeIndex([])
    ).tool_invalidate(
        "F1", "obsolete after migration", expected_revision=2
    )

    assert result["conflict"] is True
    assert result["retry"] is True
    assert result["actual_revision"] == 9


async def test_history_status_and_git_operations_are_explicit():
    repository = FakeRepository([record("F1")])
    app = services(repository, FakeIndex([], ready=False))

    history = await app.tool_history("F1")
    status = await app.tool_status()

    assert history["current_revision"] == 2
    assert history["supersedes"] == ["OLD"]
    assert status["storage_backend"] == "postgres"
    assert status["degraded"] is True
    assert "unavailable" in (await app.tool_propose_promotion("F1"))["error"]
    assert "未対応" in (await app.admin_sync())["error"]
    assert "未対応" in (await app.admin_reindex())["error"]


async def test_expected_revision_flag_only_applies_to_mutating_existing_fact():
    repository = FakeRepository()
    actor = ActorContext(
        organization_id=ORG,
        actor_id="service:test",
        actor_type="service",
        roles=frozenset({"writer"}),
    )
    scope = QueryScope(organization_id=ORG, actor_id=actor.actor_id)
    app = PostgresAppServices(
        repository=repository,
        search_index=FakeIndex([]),
        actor_provider=lambda: actor,
        scope_provider=lambda: scope,
        settings=Settings.model_construct(
            require_idempotency_key=True, require_expected_revision=True
        ),
    )

    created = await app.tool_add(
        namespace="plk.domain.dev",
        kind="knowhow",
        statement="A new fact does not require an expected revision",
        why="there is no existing mutable row to compare during creation",
        how_to_apply="require revisions only for invalidate and supersedes",
        source="session 00000000-0000-0000-0000-000000000001",
        idempotency_key="new-fact",
    )
    rejected = await app.tool_invalidate(
        "F1", "obsolete after review", idempotency_key="invalidate"
    )

    assert "fact_id" in created
    assert rejected["error"] == "expected_revision is required"
