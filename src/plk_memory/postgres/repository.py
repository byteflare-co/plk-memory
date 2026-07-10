"""PostgreSQL implementation of the storage-neutral fact repository."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from plk_memory.domain import (
    ActorContext,
    CreateFact,
    FactFilters,
    FactHistory,
    FactPayload,
    FactRecord,
    FactRevision,
    InvalidateFact,
    QueryScope,
    WriteResult,
)
from plk_memory.ports import (
    FactAlreadyExists,
    FactMissing,
    IdempotencyConflict,
    RevisionConflict,
)
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.schema import (
    audit_events,
    idempotency_records,
    knowledge_fact_revisions,
    knowledge_facts,
    knowledge_relations,
    outbox_events,
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _payload_hash(payload: FactPayload) -> str:
    return _canonical_hash(payload.model_dump(mode="json"))


def _revision_values(
    *,
    organization_id: UUID,
    revision_id: UUID,
    fact_id: str,
    version: int,
    payload: FactPayload,
    status: str,
    invalidation_reason: str | None,
    change_reason: str,
    actor: ActorContext,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "organization_id": organization_id,
        "revision_id": revision_id,
        "fact_id": fact_id,
        "version": version,
        "kind": payload.kind,
        "statement": payload.statement,
        "why": payload.why,
        "how_to_apply": payload.how_to_apply,
        "sources": [payload.source],
        "source_type": payload.source_type,
        "namespace": payload.namespace,
        "tags": list(payload.tags),
        "body": payload.body,
        "status": status,
        "invalidation_reason": invalidation_reason,
        "change_reason": change_reason,
        "actor_id": actor.actor_id,
        "actor_type": actor.actor_type,
        "content_hash": _payload_hash(payload),
        "created_at": created_at,
    }


class PostgresFactRepository:
    """Atomic multi-writer fact storage with revisions and transactional outbox."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    async def list(
        self, scope: QueryScope, filters: FactFilters
    ) -> Sequence[FactRecord]:
        async with self.database.transaction(scope.organization_id) as session:
            query = self._current_query(scope.organization_id)
            if filters.namespaces:
                query = query.where(knowledge_facts.c.namespace.in_(filters.namespaces))
            if filters.kind:
                query = query.where(knowledge_facts.c.kind == filters.kind)
            if filters.status:
                query = query.where(knowledge_facts.c.status == filters.status)
            query = query.order_by(knowledge_facts.c.updated_at.desc()).limit(filters.limit)
            rows = (await session.execute(query)).mappings()
            return tuple(self._record(row) for row in rows)

    async def get(self, scope: QueryScope, fact_id: str) -> FactRecord:
        async with self.database.transaction(scope.organization_id) as session:
            return await self._get(session, scope.organization_id, fact_id)

    async def get_many(
        self, scope: QueryScope, fact_ids: Sequence[str]
    ) -> Sequence[FactRecord]:
        if not fact_ids:
            return ()
        async with self.database.transaction(scope.organization_id) as session:
            query = self._current_query(scope.organization_id).where(
                knowledge_facts.c.fact_id.in_(fact_ids)
            )
            records = {
                cast(str, row["fact_id"]): self._record(row)
                for row in (await session.execute(query)).mappings()
            }
            return tuple(records[fact_id] for fact_id in fact_ids if fact_id in records)

    async def create(
        self,
        actor: ActorContext,
        command: CreateFact,
        *,
        expected_superseded_revisions: dict[str, int],
        idempotency_key: str,
    ) -> WriteResult:
        request_hash = _canonical_hash(
            {
                "actor_id": actor.actor_id,
                "command": command.model_dump(mode="json"),
                "expected": expected_superseded_revisions,
                "operation": "create",
            }
        )
        async with self.database.transaction(actor.organization_id) as session:
            replay = await self._begin_idempotent(
                session,
                actor.organization_id,
                idempotency_key,
                request_hash,
                "create",
            )
            if replay is not None:
                return replay.model_copy(update={"replayed": True})

            if set(command.supersedes) != set(expected_superseded_revisions):
                raise ValueError("every superseded fact requires an expected revision")

            existing = await session.scalar(
                select(knowledge_facts.c.fact_id).where(
                    knowledge_facts.c.organization_id == actor.organization_id,
                    knowledge_facts.c.fact_id == command.fact_id,
                )
            )
            if existing is not None:
                raise FactAlreadyExists(command.fact_id)

            superseded = await self._lock_heads(
                session, actor.organization_id, command.supersedes
            )
            for fact_id in command.supersedes:
                head = superseded.get(fact_id)
                if head is None:
                    raise FactMissing(fact_id)
                expected = expected_superseded_revisions[fact_id]
                if head["current_version"] != expected:
                    raise RevisionConflict(fact_id, expected, head["current_version"])
                if head["status"] != "active":
                    raise RevisionConflict(fact_id, expected, head["current_version"])

            now = datetime.now(UTC)
            revision_id = uuid4()
            event_id = uuid4()
            await session.execute(
                insert(knowledge_facts).values(
                    organization_id=actor.organization_id,
                    fact_id=command.fact_id,
                    kind=command.payload.kind,
                    namespace=command.payload.namespace,
                    status="active",
                    current_version=1,
                    current_revision_id=revision_id,
                    created_by=actor.actor_id,
                    created_at=now,
                    updated_by=actor.actor_id,
                    updated_at=now,
                )
            )
            await session.execute(
                insert(knowledge_fact_revisions).values(
                    **_revision_values(
                        organization_id=actor.organization_id,
                        revision_id=revision_id,
                        fact_id=command.fact_id,
                        version=1,
                        payload=command.payload,
                        status="active",
                        invalidation_reason=None,
                        change_reason=command.change_reason,
                        actor=actor,
                        created_at=now,
                    )
                )
            )
            await self._emit(
                session, actor.organization_id, event_id, command.fact_id, 1, "created", now
            )

            for fact_id in command.supersedes:
                await self._invalidate_locked(
                    session,
                    actor,
                    superseded[fact_id],
                    reason=f"superseded by {command.fact_id}",
                    now=now,
                )
                await session.execute(
                    insert(knowledge_relations).values(
                        organization_id=actor.organization_id,
                        relation_id=uuid4(),
                        relation_type="supersedes",
                        from_fact_id=command.fact_id,
                        to_fact_id=fact_id,
                        created_revision_id=revision_id,
                        is_active=True,
                        created_at=now,
                    )
                )

            result = WriteResult(
                fact_id=command.fact_id, revision=1, replayed=False, event_id=event_id
            )
            await self._audit(session, actor, "fact.created", command.fact_id, now)
            await self._finish_idempotent(
                session, actor.organization_id, idempotency_key, result
            )
            return result

    async def invalidate(
        self,
        actor: ActorContext,
        command: InvalidateFact,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> WriteResult:
        request_hash = _canonical_hash(
            {
                "actor_id": actor.actor_id,
                "command": command.model_dump(mode="json"),
                "expected": expected_revision,
                "operation": "invalidate",
            }
        )
        async with self.database.transaction(actor.organization_id) as session:
            replay = await self._begin_idempotent(
                session,
                actor.organization_id,
                idempotency_key,
                request_hash,
                "invalidate",
            )
            if replay is not None:
                return replay.model_copy(update={"replayed": True})
            heads = await self._lock_heads(
                session, actor.organization_id, (command.fact_id,)
            )
            head = heads.get(command.fact_id)
            if head is None:
                raise FactMissing(command.fact_id)
            if head["current_version"] != expected_revision or head["status"] != "active":
                raise RevisionConflict(
                    command.fact_id, expected_revision, head["current_version"]
                )
            now = datetime.now(UTC)
            result = await self._invalidate_locked(
                session, actor, head, reason=command.reason, now=now
            )
            await self._audit(session, actor, "fact.invalidated", command.fact_id, now)
            await self._finish_idempotent(
                session, actor.organization_id, idempotency_key, result
            )
            return result

    async def history(self, scope: QueryScope, fact_id: str) -> FactHistory:
        async with self.database.transaction(scope.organization_id) as session:
            head = await session.execute(
                select(knowledge_facts.c.current_version).where(
                    knowledge_facts.c.organization_id == scope.organization_id,
                    knowledge_facts.c.fact_id == fact_id,
                )
            )
            current = head.scalar_one_or_none()
            if current is None:
                raise FactMissing(fact_id)
            revisions = (
                await session.execute(
                    select(knowledge_fact_revisions)
                    .where(
                        knowledge_fact_revisions.c.organization_id
                        == scope.organization_id,
                        knowledge_fact_revisions.c.fact_id == fact_id,
                    )
                    .order_by(knowledge_fact_revisions.c.version)
                )
            ).mappings()
            supersedes = await session.scalars(
                select(knowledge_relations.c.to_fact_id).where(
                    knowledge_relations.c.organization_id == scope.organization_id,
                    knowledge_relations.c.from_fact_id == fact_id,
                    knowledge_relations.c.relation_type == "supersedes",
                )
            )
            superseded_by = await session.scalars(
                select(knowledge_relations.c.from_fact_id).where(
                    knowledge_relations.c.organization_id == scope.organization_id,
                    knowledge_relations.c.to_fact_id == fact_id,
                    knowledge_relations.c.relation_type == "supersedes",
                )
            )
            return FactHistory(
                fact_id=fact_id,
                current_revision=current,
                revisions=tuple(self._revision(row) for row in revisions),
                supersedes=tuple(supersedes),
                superseded_by=tuple(superseded_by),
            )

    @staticmethod
    def _current_query(organization_id: UUID):
        return (
            select(knowledge_facts, knowledge_fact_revisions)
            .join(
                knowledge_fact_revisions,
                and_(
                    knowledge_fact_revisions.c.organization_id
                    == knowledge_facts.c.organization_id,
                    knowledge_fact_revisions.c.revision_id
                    == knowledge_facts.c.current_revision_id,
                ),
            )
            .where(knowledge_facts.c.organization_id == organization_id)
        )

    async def _get(
        self, session: AsyncSession, organization_id: UUID, fact_id: str
    ) -> FactRecord:
        row = (
            await session.execute(
                self._current_query(organization_id).where(
                    knowledge_facts.c.fact_id == fact_id
                )
            )
        ).mappings().one_or_none()
        if row is None:
            raise FactMissing(fact_id)
        return self._record(row)

    async def _lock_heads(
        self,
        session: AsyncSession,
        organization_id: UUID,
        fact_ids: Sequence[str],
    ) -> dict[str, RowMapping]:
        if not fact_ids:
            return {}
        rows = (
            await session.execute(
                self._current_query(organization_id)
                .where(knowledge_facts.c.fact_id.in_(sorted(fact_ids)))
                .order_by(knowledge_facts.c.fact_id)
                .with_for_update(of=knowledge_facts)
            )
        ).mappings()
        return {cast(str, row["fact_id"]): row for row in rows}

    async def _invalidate_locked(
        self,
        session: AsyncSession,
        actor: ActorContext,
        head: Mapping[Any, Any],
        *,
        reason: str,
        now: datetime,
    ) -> WriteResult:
        fact_id = head["fact_id"]
        version = head["current_version"] + 1
        revision_id = uuid4()
        event_id = uuid4()
        payload = self._payload(head)
        await session.execute(
            insert(knowledge_fact_revisions).values(
                **_revision_values(
                    organization_id=actor.organization_id,
                    revision_id=revision_id,
                    fact_id=fact_id,
                    version=version,
                    payload=payload,
                    status="invalidated",
                    invalidation_reason=reason,
                    change_reason=reason,
                    actor=actor,
                    created_at=now,
                )
            )
        )
        changed = cast(
            CursorResult[Any],
            await session.execute(
                update(knowledge_facts)
                .where(
                    knowledge_facts.c.organization_id == actor.organization_id,
                    knowledge_facts.c.fact_id == fact_id,
                    knowledge_facts.c.current_version == head["current_version"],
                )
                .values(
                    status="invalidated",
                    current_version=version,
                    current_revision_id=revision_id,
                    updated_by=actor.actor_id,
                    updated_at=now,
                )
            ),
        )
        if changed.rowcount != 1:
            raise RevisionConflict(fact_id, head["current_version"], version)
        await self._emit(
            session,
            actor.organization_id,
            event_id,
            fact_id,
            version,
            "invalidated",
            now,
        )
        return WriteResult(
            fact_id=fact_id, revision=version, replayed=False, event_id=event_id
        )

    async def _begin_idempotent(
        self,
        session: AsyncSession,
        organization_id: UUID,
        key: str,
        request_hash: str,
        operation: str,
    ) -> WriteResult | None:
        inserted = await session.execute(
            pg_insert(idempotency_records)
            .values(
                organization_id=organization_id,
                idempotency_key=key,
                request_hash=request_hash,
                operation=operation,
                resource_type="fact",
            )
            .on_conflict_do_nothing()
            .returning(idempotency_records.c.idempotency_key)
        )
        if inserted.scalar_one_or_none() is not None:
            return None
        row = (
            await session.execute(
                select(idempotency_records).where(
                    idempotency_records.c.organization_id == organization_id,
                    idempotency_records.c.idempotency_key == key,
                )
            )
        ).mappings().one()
        if row["request_hash"] != request_hash:
            raise IdempotencyConflict(f"idempotency key reused: {key}")
        if row["response_body"] is None:
            raise RuntimeError("idempotency record committed without a response")
        return WriteResult.model_validate(row["response_body"])

    @staticmethod
    async def _finish_idempotent(
        session: AsyncSession,
        organization_id: UUID,
        key: str,
        result: WriteResult,
    ) -> None:
        await session.execute(
            update(idempotency_records)
            .where(
                idempotency_records.c.organization_id == organization_id,
                idempotency_records.c.idempotency_key == key,
            )
            .values(
                resource_id=result.fact_id,
                event_id=result.event_id,
                response_body=result.model_dump(mode="json"),
            )
        )

    @staticmethod
    async def _emit(
        session: AsyncSession,
        organization_id: UUID,
        event_id: UUID,
        fact_id: str,
        version: int,
        operation: str,
        now: datetime,
    ) -> None:
        await session.execute(
            insert(outbox_events).values(
                organization_id=organization_id,
                event_id=event_id,
                aggregate_type="fact",
                aggregate_id=fact_id,
                aggregate_version=version,
                event_type=f"knowledge.{operation}",
                payload={
                    "event_id": str(event_id),
                    "organization_id": str(organization_id),
                    "fact_id": fact_id,
                    "revision": version,
                    "operation": operation,
                    "occurred_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )

    @staticmethod
    async def _audit(
        session: AsyncSession,
        actor: ActorContext,
        action: str,
        fact_id: str,
        now: datetime,
    ) -> None:
        await session.execute(
            insert(audit_events).values(
                organization_id=actor.organization_id,
                audit_id=uuid4(),
                action=action,
                resource_type="fact",
                resource_id=fact_id,
                actor_id=actor.actor_id,
                actor_type=actor.actor_type,
                details={},
                created_at=now,
            )
        )

    @classmethod
    def _record(cls, row: Mapping[Any, Any]) -> FactRecord:
        return FactRecord(
            id=row["fact_id"],
            organization_id=row["organization_id"],
            revision=row["current_version"],
            payload=cls._payload(row),
            status=row["status"],
            invalidation_reason=row["invalidation_reason"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_by=row["updated_by"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _payload(row: Mapping[Any, Any]) -> FactPayload:
        sources = row["sources"]
        return FactPayload(
            kind=row["kind"],
            statement=row["statement"],
            why=row["why"],
            how_to_apply=row["how_to_apply"],
            source=sources[0] if sources else "",
            source_type=row["source_type"],
            namespace=row["namespace"],
            tags=tuple(row["tags"]),
            body=row["body"],
        )

    @classmethod
    def _revision(cls, row: Mapping[Any, Any]) -> FactRevision:
        return FactRevision(
            fact_id=row["fact_id"],
            organization_id=row["organization_id"],
            revision=row["version"],
            payload=cls._payload(row),
            status=row["status"],
            invalidation_reason=row["invalidation_reason"],
            change_reason=row["change_reason"],
            actor_id=row["actor_id"],
            actor_type=row["actor_type"],
            created_at=row["created_at"],
        )
