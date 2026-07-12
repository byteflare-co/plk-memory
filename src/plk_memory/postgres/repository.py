"""PostgreSQL implementation of the storage-neutral fact repository."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, insert, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from plk_validator.schema import Fact

from plk_memory.domain import (
    ActorContext,
    CreateFact,
    FactFilters,
    FactHistory,
    FactRecord,
    InvalidateFact,
    QueryScope,
    WriteResult,
)
from plk_memory.ports import (
    FactAlreadyExists,
    FactMissing,
    PolicyViolation,
    RevisionConflict,
)
from plk_memory.policy import scan_text
from plk_memory.postgres import mappers, write_ops
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.schema import (
    knowledge_fact_revisions,
    knowledge_facts,
    knowledge_relations,
)


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
            query = query.order_by(knowledge_facts.c.updated_at.desc()).limit(
                filters.limit
            )
            rows = (await session.execute(query)).mappings()
            return tuple(mappers.record_from_row(row) for row in rows)

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
                cast(str, row["fact_id"]): mappers.record_from_row(row)
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
        self._validate_create(actor, command)
        request_hash = mappers.canonical_hash(
            {
                "actor_id": actor.actor_id,
                "command": command.model_dump(mode="json"),
                "operation": "create",
            }
        )
        async with self.database.transaction(actor.organization_id) as session:
            replay = await write_ops.begin_idempotent(
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
                    **mappers.revision_values(
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
            await write_ops.emit_event(
                session,
                actor.organization_id,
                event_id,
                command.fact_id,
                1,
                "created",
                now,
            )

            for fact_id in command.supersedes:
                await self._invalidate_locked(
                    session,
                    actor,
                    superseded[fact_id],
                    reason=f"後継ファクト {command.fact_id} により置換",
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
            await write_ops.record_audit(
                session, actor, "fact.created", command.fact_id, now
            )
            await write_ops.finish_idempotent(
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
        if "writer" not in actor.roles:
            raise PolicyViolation("fact invalidation requires writer role")
        request_hash = mappers.canonical_hash(
            {
                "actor_id": actor.actor_id,
                "command": command.model_dump(mode="json"),
                "operation": "invalidate",
            }
        )
        async with self.database.transaction(actor.organization_id) as session:
            replay = await write_ops.begin_idempotent(
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
            if (
                head["current_version"] != expected_revision
                or head["status"] != "active"
            ):
                raise RevisionConflict(
                    command.fact_id, expected_revision, head["current_version"]
                )
            now = datetime.now(UTC)
            result = await self._invalidate_locked(
                session, actor, head, reason=command.reason, now=now
            )
            await write_ops.record_audit(
                session, actor, "fact.invalidated", command.fact_id, now
            )
            await write_ops.finish_idempotent(
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
                select(knowledge_relations.c.to_fact_id)
                .where(
                    knowledge_relations.c.organization_id == scope.organization_id,
                    knowledge_relations.c.from_fact_id == fact_id,
                    knowledge_relations.c.relation_type == "supersedes",
                )
                .order_by(knowledge_relations.c.to_fact_id)
            )
            superseded_by = await session.scalars(
                select(knowledge_relations.c.from_fact_id)
                .where(
                    knowledge_relations.c.organization_id == scope.organization_id,
                    knowledge_relations.c.to_fact_id == fact_id,
                    knowledge_relations.c.relation_type == "supersedes",
                )
                .order_by(knowledge_relations.c.from_fact_id)
            )
            return FactHistory(
                fact_id=fact_id,
                current_revision=current,
                revisions=tuple(mappers.revision_from_row(row) for row in revisions),
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
            (
                await session.execute(
                    self._current_query(organization_id).where(
                        knowledge_facts.c.fact_id == fact_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise FactMissing(fact_id)
        return mappers.record_from_row(row)

    async def _lock_heads(
        self,
        session: AsyncSession,
        organization_id: UUID,
        fact_ids: Sequence[str],
    ) -> dict[str, Mapping[Any, Any]]:
        if not fact_ids:
            return {}
        # Lock only the mutable heads first. Joining the revision in this same
        # statement can produce a stale-snapshot no-row result after waiting
        # for a concurrent head update under READ COMMITTED.
        heads = (
            (
                await session.execute(
                    select(knowledge_facts)
                    .where(
                        knowledge_facts.c.organization_id == organization_id,
                        knowledge_facts.c.fact_id.in_(sorted(fact_ids)),
                    )
                    .order_by(knowledge_facts.c.fact_id)
                    .with_for_update(of=knowledge_facts)
                )
            )
            .mappings()
            .all()
        )
        if not heads:
            return {}
        revisions = (
            await session.execute(
                select(knowledge_fact_revisions).where(
                    knowledge_fact_revisions.c.organization_id == organization_id,
                    knowledge_fact_revisions.c.revision_id.in_(
                        [head["current_revision_id"] for head in heads]
                    ),
                )
            )
        ).mappings()
        revision_by_id = {row["revision_id"]: row for row in revisions}
        result: dict[str, Mapping[Any, Any]] = {}
        for head in heads:
            merged = dict(head)
            merged.update(revision_by_id[head["current_revision_id"]])
            result[cast(str, head["fact_id"])] = merged
        return result

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
        payload = mappers.payload_from_row(head)
        await session.execute(
            insert(knowledge_fact_revisions).values(
                **mappers.revision_values(
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
        await write_ops.emit_event(
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

    @staticmethod
    def _validate_create(actor: ActorContext, command: CreateFact) -> None:
        """Apply the same structural/content policy used by Git CI."""

        payload = command.payload
        if "writer" not in actor.roles:
            raise PolicyViolation("fact creation requires writer role")
        if payload.kind == "philosophy" and "philosophy:write" not in actor.roles:
            raise PolicyViolation("philosophy requires philosophy:write")
        if payload.source_type == "user" and "human-authored:write" not in actor.roles:
            raise PolicyViolation("source_type=user requires human-authored:write")
        if payload.namespace == "plk.shared" and "shared:write" not in actor.roles:
            raise PolicyViolation("plk.shared requires shared:write")
        if (
            payload.source_type == "external-untrusted"
            and payload.namespace != "plk.quarantine"
        ):
            raise PolicyViolation("external-untrusted facts must use plk.quarantine")

        Fact(
            id=command.fact_id,
            kind=payload.kind,
            statement=payload.statement,
            why=payload.why,
            how_to_apply=payload.how_to_apply,
            source=payload.source,
            source_type=payload.source_type,
            namespace=payload.namespace,
            status="active",
            invalidation_reason=None,
            written_by=actor.actor_id,
            created_at=datetime.now(UTC),
            invalidated_at=None,
            superseded_by=None,
            tags=list(payload.tags),
        )
        if len(payload.body) > 2000:
            raise ValueError("body must not exceed 2,000 characters")
        findings = set(scan_text(payload.model_dump_json()))
        # Long opaque IDs are valid in source URLs (Notion/Google Drive), so
        # entropy checks target authored content while known token formats are
        # still checked across the complete serialized payload above.
        for authored_text in (
            payload.statement,
            payload.why,
            payload.how_to_apply,
            payload.body,
            *payload.tags,
        ):
            findings.update(scan_text(authored_text, entropy=True))
        if findings:
            raise PolicyViolation(f"secret detected: {sorted(findings)}")
