"""Shared write-path helpers for PostgreSQL fact storage.

Idempotency bookkeeping, transactional-outbox emission, and audit logging
used by both the fact repository and the promotion approval workflow.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from plk_memory.domain import ActorContext, WriteResult
from plk_memory.ports import IdempotencyConflict
from plk_memory.postgres.schema import (
    audit_events,
    idempotency_records,
    outbox_events,
)


async def begin_idempotent(
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
        (
            await session.execute(
                select(idempotency_records).where(
                    idempotency_records.c.organization_id == organization_id,
                    idempotency_records.c.idempotency_key == key,
                )
            )
        )
        .mappings()
        .one()
    )
    if row["request_hash"] != request_hash:
        raise IdempotencyConflict(f"idempotency key reused: {key}")
    if row["response_body"] is None:
        raise RuntimeError("idempotency record committed without a response")
    return WriteResult.model_validate(row["response_body"])


async def finish_idempotent(
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


async def emit_event(
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


async def record_audit(
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
