"""Transactional outbox and search projection state adapters."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult

from plk_memory.domain import ClaimedChange, IndexEntry, KnowledgeChanged
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.schema import outbox_events, search_projection_state


class PostgresChangeFeed:
    """At-least-once outbox consumer using short committed leases."""

    def __init__(self, database: PostgresDatabase, *, max_attempts: int = 10) -> None:
        self.database = database
        self.max_attempts = max_attempts

    async def claim(
        self,
        *,
        consumer: str,
        limit: int,
        lease_until: datetime,
    ) -> Sequence[ClaimedChange]:
        now = datetime.now(UTC)
        if limit < 1:
            raise ValueError("limit must be positive")
        if lease_until <= now:
            raise ValueError("lease_until must be in the future")
        async with self.database.worker_transaction() as session:
            older = outbox_events.alias("older_outbox_event")
            rows = (
                (
                    await session.execute(
                        select(outbox_events)
                        .where(
                        outbox_events.c.processed_at.is_(None),
                        outbox_events.c.dead_lettered_at.is_(None),
                            outbox_events.c.available_at <= now,
                            or_(
                                outbox_events.c.lease_until.is_(None),
                                outbox_events.c.lease_until < now,
                            ),
                            ~select(older.c.event_id)
                            .where(
                                older.c.organization_id
                                == outbox_events.c.organization_id,
                                older.c.aggregate_type
                                == outbox_events.c.aggregate_type,
                                older.c.aggregate_id == outbox_events.c.aggregate_id,
                                older.c.processed_at.is_(None),
                                older.c.dead_lettered_at.is_(None),
                                or_(
                                    older.c.aggregate_version
                                    < outbox_events.c.aggregate_version,
                                    and_(
                                        older.c.aggregate_version
                                        == outbox_events.c.aggregate_version,
                                        or_(
                                            older.c.occurred_at
                                            < outbox_events.c.occurred_at,
                                            and_(
                                                older.c.occurred_at
                                                == outbox_events.c.occurred_at,
                                                older.c.event_id
                                                < outbox_events.c.event_id,
                                            ),
                                        ),
                                    ),
                                ),
                            )
                            .exists(),
                        )
                        .order_by(outbox_events.c.occurred_at, outbox_events.c.event_id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                .mappings()
                .all()
            )
            if not rows:
                return ()
            lease_token = uuid4()
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
                    lease_token=lease_token,
                    lease_until=lease_until,
                    attempts=outbox_events.c.attempts + 1,
                )
            )
            return tuple(
                ClaimedChange(
                    change=KnowledgeChanged.model_validate(row["payload"]),
                    consumer=consumer,
                    lease_token=lease_token,
                    attempts=row["attempts"] + 1,
                )
                for row in rows
            )

    async def ack(self, claims: Sequence[ClaimedChange]) -> None:
        if not claims:
            return
        predicates = [
            and_(
                outbox_events.c.organization_id == claim.change.organization_id,
                outbox_events.c.event_id == claim.change.event_id,
                outbox_events.c.lease_owner == claim.consumer,
                outbox_events.c.lease_token == claim.lease_token,
            )
            for claim in claims
        ]
        async with self.database.worker_transaction() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(outbox_events)
                    .where(or_(*predicates))
                    .values(
                        processed_at=datetime.now(UTC),
                        lease_owner=None,
                        lease_token=None,
                        lease_until=None,
                        last_error=None,
                    )
                ),
            )
            if result.rowcount != len(claims):
                raise RuntimeError("one or more outbox leases are no longer owned")

    async def renew(self, claim: ClaimedChange, *, lease_until: datetime) -> None:
        if lease_until <= datetime.now(UTC):
            raise ValueError("lease_until must be in the future")
        async with self.database.worker_transaction() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(outbox_events)
                    .where(
                        outbox_events.c.organization_id
                        == claim.change.organization_id,
                        outbox_events.c.event_id == claim.change.event_id,
                        outbox_events.c.lease_owner == claim.consumer,
                        outbox_events.c.lease_token == claim.lease_token,
                        outbox_events.c.processed_at.is_(None),
                        outbox_events.c.dead_lettered_at.is_(None),
                    )
                    .values(lease_until=lease_until)
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("outbox lease is no longer owned")

    async def fail(
        self, claim: ClaimedChange, *, error: str, retry_at: datetime
    ) -> None:
        async with self.database.worker_transaction() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(outbox_events)
                    .where(
                        outbox_events.c.organization_id == claim.change.organization_id,
                        outbox_events.c.event_id == claim.change.event_id,
                        outbox_events.c.lease_owner == claim.consumer,
                        outbox_events.c.lease_token == claim.lease_token,
                    )
                    .values(
                        available_at=retry_at,
                        lease_owner=None,
                        lease_token=None,
                        lease_until=None,
                        last_error=error[:4000],
                        dead_lettered_at=case(
                            (
                                outbox_events.c.attempts >= self.max_attempts,
                                datetime.now(UTC),
                            ),
                            else_=None,
                        ),
                    )
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("outbox lease is no longer owned")


class PostgresIndexStateRepository:
    """Shared projection checkpoints with compare-by-revision semantics."""

    def __init__(self, database: PostgresDatabase, *, backend: str) -> None:
        self.database = database
        self.backend = backend

    async def get(self, organization_id: str, fact_id: str) -> IndexEntry | None:
        organization_uuid = UUID(organization_id)
        async with self.database.worker_transaction() as session:
            row = (
                (
                    await session.execute(
                        select(search_projection_state).where(
                            search_projection_state.c.organization_id
                            == organization_uuid,
                            search_projection_state.c.backend == self.backend,
                            search_projection_state.c.fact_id == fact_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return IndexEntry(
            organization_id=row["organization_id"],
            fact_id=row["fact_id"],
            indexed_revision=row["indexed_version"],
            content_hash=row["content_hash"],
            backend_refs=tuple(row["backend_refs"]),
            partition=row["partition"],
            last_event_id=row["last_event_id"],
            indexed_at=row["indexed_at"],
        )

    async def put_if_newer(self, entry: IndexEntry) -> bool:
        if entry.last_event_id is None:
            raise ValueError(
                "last_event_id is required for PostgreSQL projection state"
            )
        statement = pg_insert(search_projection_state).values(
            organization_id=entry.organization_id,
            backend=self.backend,
            fact_id=entry.fact_id,
            indexed_version=entry.indexed_revision,
            content_hash=entry.content_hash,
            backend_refs=list(entry.backend_refs),
            partition=entry.partition,
            last_event_id=entry.last_event_id,
            indexed_at=entry.indexed_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["organization_id", "backend", "fact_id"],
            set_={
                "indexed_version": statement.excluded.indexed_version,
                "content_hash": statement.excluded.content_hash,
                "backend_refs": statement.excluded.backend_refs,
                "partition": statement.excluded.partition,
                "last_event_id": statement.excluded.last_event_id,
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
