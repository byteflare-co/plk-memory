"""Transactional outbox and search projection state adapters."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult

from plk_memory.domain import IndexEntry, KnowledgeChanged
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.schema import outbox_events, search_projection_state


class PostgresChangeFeed:
    """At-least-once outbox consumer using short committed leases."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    async def claim(
        self,
        *,
        consumer: str,
        limit: int,
        lease_until: datetime,
    ) -> Sequence[KnowledgeChanged]:
        now = datetime.now(UTC)
        async with self.database.worker_transaction() as session:
            rows = (
                await session.execute(
                    select(outbox_events)
                    .where(
                        outbox_events.c.processed_at.is_(None),
                        outbox_events.c.available_at <= now,
                        or_(
                            outbox_events.c.lease_until.is_(None),
                            outbox_events.c.lease_until < now,
                        ),
                    )
                    .order_by(outbox_events.c.occurred_at, outbox_events.c.event_id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).mappings().all()
            if not rows:
                return ()
            identities = [
                and_(
                    outbox_events.c.organization_id == row["organization_id"],
                    outbox_events.c.event_id == row["event_id"],
                )
                for row in rows
            ]
            await session.execute(
                update(outbox_events)
                .where(or_(*identities))
                .values(
                    lease_owner=consumer,
                    lease_until=lease_until,
                    attempts=outbox_events.c.attempts + 1,
                )
            )
            return tuple(KnowledgeChanged.model_validate(row["payload"]) for row in rows)

    async def ack(self, event_ids: Sequence[str]) -> None:
        if not event_ids:
            return
        async with self.database.worker_transaction() as session:
            await session.execute(
                update(outbox_events)
                .where(outbox_events.c.event_id.in_([UUID(value) for value in event_ids]))
                .values(
                    processed_at=datetime.now(UTC),
                    lease_owner=None,
                    lease_until=None,
                    last_error=None,
                )
            )

    async def fail(
        self, event_id: str, *, error: str, retry_at: datetime
    ) -> None:
        async with self.database.worker_transaction() as session:
            await session.execute(
                update(outbox_events)
                .where(outbox_events.c.event_id == UUID(event_id))
                .values(
                    available_at=retry_at,
                    lease_owner=None,
                    lease_until=None,
                    last_error=error[:4000],
                )
            )


class PostgresIndexStateRepository:
    """Shared projection checkpoints with compare-by-revision semantics."""

    def __init__(self, database: PostgresDatabase, *, backend: str) -> None:
        self.database = database
        self.backend = backend

    async def get(self, organization_id: str, fact_id: str) -> IndexEntry | None:
        organization_uuid = UUID(organization_id)
        async with self.database.worker_transaction() as session:
            row = (
                await session.execute(
                    select(search_projection_state).where(
                        search_projection_state.c.organization_id == organization_uuid,
                        search_projection_state.c.backend == self.backend,
                        search_projection_state.c.fact_id == fact_id,
                    )
                )
            ).mappings().one_or_none()
        if row is None:
            return None
        return IndexEntry(
            organization_id=row["organization_id"],
            fact_id=row["fact_id"],
            indexed_revision=row["indexed_version"],
            content_hash=row["content_hash"],
            backend_refs=tuple(row["backend_refs"]),
            last_event_id=row["last_event_id"],
            indexed_at=row["indexed_at"],
        )

    async def put_if_newer(self, entry: IndexEntry) -> bool:
        statement = pg_insert(search_projection_state).values(
            organization_id=entry.organization_id,
            backend=self.backend,
            fact_id=entry.fact_id,
            indexed_version=entry.indexed_revision,
            content_hash=entry.content_hash,
            backend_refs=list(entry.backend_refs),
            last_event_id=entry.last_event_id or UUID(int=0),
            indexed_at=entry.indexed_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["organization_id", "backend", "fact_id"],
            set_={
                "indexed_version": statement.excluded.indexed_version,
                "content_hash": statement.excluded.content_hash,
                "backend_refs": statement.excluded.backend_refs,
                "indexed_at": statement.excluded.indexed_at,
                "updated_at": datetime.now(UTC),
            },
            where=(
                statement.excluded.indexed_version
                > search_projection_state.c.indexed_version
            ),
        )
        async with self.database.worker_transaction() as session:
            result = cast(CursorResult[Any], await session.execute(statement))
            return result.rowcount == 1

    async def mark_failed(self, event_id: str, error: str) -> None:
        async with self.database.worker_transaction() as session:
            await session.execute(
                update(outbox_events)
                .where(outbox_events.c.event_id == UUID(event_id))
                .values(last_error=error[:4000])
            )
