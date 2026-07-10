"""Revision-pinned promotion approval workflow for PostgreSQL-primary PLK."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from plk_memory.domain import (
    ActorContext,
    FactPayload,
    PromotionDecisionResult,
    PromotionRequestRecord,
)
from plk_memory.ports import (
    FactMissing,
    IdempotencyConflict,
    PolicyViolation,
    RevisionConflict,
)
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.repository import (
    PostgresFactRepository,
    _canonical_hash,
    _revision_values,
)
from plk_memory.postgres.schema import (
    approval_decisions,
    approval_requests,
    idempotency_records,
    knowledge_fact_revisions,
    knowledge_facts,
)


class PostgresApprovalRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    async def propose(
        self,
        actor: ActorContext,
        fact_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> PromotionRequestRecord:
        if len(reason.strip()) < 5:
            raise ValueError("promotion reason must be at least 5 characters")
        request_hash = _canonical_hash(
            {
                "operation": "promotion.propose",
                "actor_id": actor.actor_id,
                "fact_id": fact_id,
                "reason": reason,
            }
        )
        async with self.database.transaction(actor.organization_id) as session:
            replay = await self._begin_idempotent(
                session,
                actor.organization_id,
                idempotency_key,
                request_hash,
                "promotion.propose",
            )
            if replay is not None:
                return PromotionRequestRecord.model_validate(replay["request"])

            head = (
                await session.execute(
                    select(knowledge_facts)
                    .where(
                        knowledge_facts.c.organization_id == actor.organization_id,
                        knowledge_facts.c.fact_id == fact_id,
                    )
                    .with_for_update()
                )
            ).mappings().one_or_none()
            if head is None:
                raise FactMissing(fact_id)
            if head["status"] != "active":
                raise PolicyViolation("only active facts can be promoted")
            if not str(head["namespace"]).startswith("plk.domain."):
                raise PolicyViolation("only plk.domain.* facts can be promoted")
            pending = await session.scalar(
                select(approval_requests.c.request_id).where(
                    approval_requests.c.organization_id == actor.organization_id,
                    approval_requests.c.fact_id == fact_id,
                    approval_requests.c.status == "pending",
                )
            )
            if pending is not None:
                raise PolicyViolation(f"pending promotion already exists: {pending}")

            now = datetime.now(UTC)
            request = PromotionRequestRecord(
                request_id=uuid4(),
                organization_id=actor.organization_id,
                fact_id=fact_id,
                source_revision=head["current_version"],
                status="pending",
                requested_by=actor.actor_id,
                reason=reason,
                created_at=now,
                updated_at=now,
            )
            await session.execute(
                insert(approval_requests).values(
                    organization_id=request.organization_id,
                    request_id=request.request_id,
                    fact_id=request.fact_id,
                    source_version=request.source_revision,
                    status=request.status,
                    requested_by=request.requested_by,
                    request_reason=request.reason,
                    created_at=now,
                    updated_at=now,
                )
            )
            await PostgresFactRepository._audit(
                session, actor, "promotion.proposed", fact_id, now
            )
            await self._finish_idempotent(
                session,
                actor.organization_id,
                idempotency_key,
                request.request_id,
                {"request": request.model_dump(mode="json")},
            )
            return request

    async def decide(
        self,
        actor: ActorContext,
        request_id: str,
        *,
        decision: str,
        rationale: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> PromotionDecisionResult:
        if not actor.roles.intersection({"reviewer", "admin"}):
            raise PolicyViolation("promotion decision requires reviewer or admin role")
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        if len(rationale.strip()) < 5:
            raise ValueError("rationale must be at least 5 characters")
        request_uuid = UUID(request_id)
        request_hash = _canonical_hash(
            {
                "operation": "promotion.decide",
                "actor_id": actor.actor_id,
                "request_id": request_id,
                "decision": decision,
                "rationale": rationale,
                "expected_revision": expected_revision,
            }
        )
        async with self.database.transaction(actor.organization_id) as session:
            replay = await self._begin_idempotent(
                session,
                actor.organization_id,
                idempotency_key,
                request_hash,
                "promotion.decide",
            )
            if replay is not None:
                return PromotionDecisionResult.model_validate(replay).model_copy(
                    update={"replayed": True}
                )

            request_row = (
                await session.execute(
                    select(approval_requests)
                    .where(
                        approval_requests.c.organization_id == actor.organization_id,
                        approval_requests.c.request_id == request_uuid,
                    )
                    .with_for_update()
                )
            ).mappings().one_or_none()
            if request_row is None:
                raise FactMissing(request_id)
            if request_row["status"] != "pending":
                raise PolicyViolation(
                    f"promotion request is already {request_row['status']}"
                )
            fact_id = request_row["fact_id"]
            head = (
                await session.execute(
                    select(knowledge_facts)
                    .where(
                        knowledge_facts.c.organization_id == actor.organization_id,
                        knowledge_facts.c.fact_id == fact_id,
                    )
                    .with_for_update()
                )
            ).mappings().one()
            now = datetime.now(UTC)
            source_revision = request_row["source_version"]
            if source_revision != expected_revision:
                raise RevisionConflict(fact_id, expected_revision, source_revision)
            if head["current_version"] != source_revision:
                await session.execute(
                    update(approval_requests)
                    .where(
                        approval_requests.c.organization_id == actor.organization_id,
                        approval_requests.c.request_id == request_uuid,
                    )
                    .values(status="stale", updated_at=now)
                )
                stale = self._request(request_row, status="stale", updated_at=now)
                result = PromotionDecisionResult(request=stale)
                await self._finish_idempotent(
                    session,
                    actor.organization_id,
                    idempotency_key,
                    request_uuid,
                    result.model_dump(mode="json"),
                )
                return result

            await session.execute(
                insert(approval_decisions).values(
                    organization_id=actor.organization_id,
                    decision_id=uuid4(),
                    request_id=request_uuid,
                    decision=decision,
                    rationale=rationale,
                    actor_id=actor.actor_id,
                    actor_type=actor.actor_type,
                    created_at=now,
                )
            )
            event_id = None
            new_version = None
            if decision == "approved":
                revision = (
                    await session.execute(
                        select(knowledge_fact_revisions).where(
                            knowledge_fact_revisions.c.organization_id
                            == actor.organization_id,
                            knowledge_fact_revisions.c.revision_id
                            == head["current_revision_id"],
                        )
                    )
                ).mappings().one()
                payload = FactPayload(
                    kind=revision["kind"],
                    statement=revision["statement"],
                    why=revision["why"],
                    how_to_apply=revision["how_to_apply"],
                    source=revision["sources"][0],
                    source_type=revision["source_type"],
                    namespace="plk.shared",
                    tags=tuple(revision["tags"]),
                    body=revision["body"],
                )
                new_version = head["current_version"] + 1
                revision_id = uuid4()
                event_id = uuid4()
                await session.execute(
                    insert(knowledge_fact_revisions).values(
                        **_revision_values(
                            organization_id=actor.organization_id,
                            revision_id=revision_id,
                            fact_id=fact_id,
                            version=new_version,
                            payload=payload,
                            status="active",
                            invalidation_reason=None,
                            change_reason=f"promotion approved: {rationale}",
                            actor=actor,
                            created_at=now,
                        )
                    )
                )
                await session.execute(
                    update(knowledge_facts)
                    .where(
                        knowledge_facts.c.organization_id == actor.organization_id,
                        knowledge_facts.c.fact_id == fact_id,
                        knowledge_facts.c.current_version == expected_revision,
                    )
                    .values(
                        namespace="plk.shared",
                        current_version=new_version,
                        current_revision_id=revision_id,
                        updated_by=actor.actor_id,
                        updated_at=now,
                    )
                )
                await PostgresFactRepository._emit(
                    session,
                    actor.organization_id,
                    event_id,
                    fact_id,
                    new_version,
                    "promoted",
                    now,
                )
            final_status = decision
            await session.execute(
                update(approval_requests)
                .where(
                    approval_requests.c.organization_id == actor.organization_id,
                    approval_requests.c.request_id == request_uuid,
                )
                .values(status=final_status, updated_at=now)
            )
            await PostgresFactRepository._audit(
                session, actor, f"promotion.{decision}", fact_id, now
            )
            decided = self._request(
                request_row, status=final_status, updated_at=now
            )
            result = PromotionDecisionResult(
                request=decided,
                fact_revision=new_version,
                event_id=event_id,
            )
            await self._finish_idempotent(
                session,
                actor.organization_id,
                idempotency_key,
                request_uuid,
                result.model_dump(mode="json"),
            )
            return result

    @staticmethod
    def _request(row, *, status: str | None = None, updated_at=None):
        return PromotionRequestRecord.model_validate(
            {
                "request_id": row["request_id"],
                "organization_id": row["organization_id"],
                "fact_id": row["fact_id"],
                "source_revision": row["source_version"],
                "status": status or row["status"],
                "requested_by": row["requested_by"],
                "reason": row["request_reason"],
                "created_at": row["created_at"],
                "updated_at": updated_at or row["updated_at"],
            }
        )

    @staticmethod
    async def _begin_idempotent(
        session: AsyncSession,
        organization_id: UUID,
        key: str,
        request_hash: str,
        operation: str,
    ) -> dict[str, Any] | None:
        inserted = await session.execute(
            pg_insert(idempotency_records)
            .values(
                organization_id=organization_id,
                idempotency_key=key,
                request_hash=request_hash,
                operation=operation,
                resource_type="promotion_request",
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
        return row["response_body"]

    @staticmethod
    async def _finish_idempotent(
        session: AsyncSession,
        organization_id: UUID,
        key: str,
        resource_id: UUID,
        response: dict[str, Any],
    ) -> None:
        await session.execute(
            update(idempotency_records)
            .where(
                idempotency_records.c.organization_id == organization_id,
                idempotency_records.c.idempotency_key == key,
            )
            .values(resource_id=str(resource_id), response_body=response)
        )
