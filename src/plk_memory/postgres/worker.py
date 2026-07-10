"""Level-triggered PostgreSQL outbox worker for derived search indexes."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from random import random
from typing import Any, Protocol

from sqlalchemy import func, or_, select

from plk_memory.domain import (
    ClaimedChange,
    FactRecord,
    IndexEntry,
    QueryScope,
)
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.schema import (
    knowledge_facts,
    outbox_events,
    search_projection_state,
)
from plk_memory.settings import Settings


class FactReader(Protocol):
    async def get(self, scope: QueryScope, fact_id: str) -> FactRecord: ...


class WorkerChangeFeed(Protocol):
    async def claim(
        self,
        *,
        consumer: str,
        limit: int,
        lease_until: datetime,
    ) -> Sequence[ClaimedChange]: ...

    async def ack(self, claims: Sequence[ClaimedChange]) -> None: ...

    async def renew(self, claim: ClaimedChange, *, lease_until: datetime) -> None: ...

    async def fail(
        self, claim: ClaimedChange, *, error: str, retry_at: datetime
    ) -> None: ...


class ProjectionState(Protocol):
    async def get(self, organization_id: str, fact_id: str) -> IndexEntry | None: ...

    async def put_if_newer(self, entry: IndexEntry) -> bool: ...


class ProjectionIndex(Protocol):
    async def upsert(
        self, fact: FactRecord, old: IndexEntry | None = None
    ) -> IndexEntry: ...


class PostgresIndexWorker:
    """Project current DB heads; outbox revisions are only wake-up signals."""

    def __init__(
        self,
        *,
        repository: FactReader,
        change_feed: WorkerChangeFeed,
        index_state: ProjectionState,
        search_index: ProjectionIndex,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.change_feed = change_feed
        self.index_state = index_state
        self.search_index = search_index
        self.settings = settings

    async def run_once(self) -> dict[str, int]:
        now = datetime.now(UTC)
        claims = await self.change_feed.claim(
            consumer=self.settings.worker_consumer_name,
            limit=self.settings.outbox_batch_size,
            lease_until=now + timedelta(seconds=self.settings.outbox_lease_seconds),
        )
        succeeded = 0
        failed = 0
        for claim in claims:
            try:
                await self._project_with_lease_heartbeat(claim)
                await self.change_feed.ack([claim])
                succeeded += 1
            except Exception as error:  # noqa: BLE001 - retry/dead-letter boundary
                delay = min(
                    self.settings.outbox_retry_max_seconds,
                    self.settings.outbox_retry_base_seconds
                    * (2 ** max(claim.attempts - 1, 0)),
                )
                jittered = delay * (0.75 + random() * 0.5)
                try:
                    await self.change_feed.fail(
                        claim,
                        error=str(error),
                        retry_at=datetime.now(UTC) + timedelta(seconds=jittered),
                    )
                except Exception:  # noqa: BLE001 - stale lease must not kill worker
                    pass
                failed += 1
        return {"claimed": len(claims), "succeeded": succeeded, "failed": failed}

    async def _project_with_lease_heartbeat(self, claim: ClaimedChange) -> None:
        projection = asyncio.create_task(self._project(claim))
        heartbeat = asyncio.create_task(self._heartbeat(claim))
        done, _ = await asyncio.wait(
            {projection, heartbeat}, return_when=asyncio.FIRST_COMPLETED
        )
        if heartbeat in done:
            error = heartbeat.exception()
            if error is not None:
                projection.cancel()
                with suppress(asyncio.CancelledError):
                    await projection
                raise error
        try:
            await projection
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat(self, claim: ClaimedChange) -> None:
        lease_seconds = self.settings.outbox_lease_seconds
        interval = max(lease_seconds / 3, 0.1)
        while True:
            await asyncio.sleep(interval)
            await self.change_feed.renew(
                claim,
                lease_until=datetime.now(UTC) + timedelta(seconds=lease_seconds),
            )

    async def _project(self, claim: ClaimedChange) -> None:
        change = claim.change
        scope = QueryScope(
            organization_id=change.organization_id,
            actor_id=self.settings.worker_consumer_name,
            roles=frozenset({"worker"}),
        )
        fact = await self.repository.get(scope, change.fact_id)
        old = await self.index_state.get(str(change.organization_id), change.fact_id)
        if old is not None and old.indexed_revision >= fact.revision:
            return
        entry = await self.search_index.upsert(fact, old)
        entry = entry.model_copy(
            update={
                "indexed_revision": fact.revision,
                "last_event_id": change.event_id,
            }
        )
        await self.index_state.put_if_newer(entry)

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        while not stop.is_set():
            result = await self.run_once()
            if result["claimed"] == 0:
                try:
                    await asyncio.wait_for(
                        stop.wait(), timeout=self.settings.outbox_poll_interval_seconds
                    )
                except TimeoutError:
                    pass


class PostgresProjectionStatus:
    """Read-only lag/status metrics for the MCP status endpoint."""

    def __init__(self, database: PostgresDatabase, *, backend: str = "graphiti"):
        self.database = database
        self.backend = backend

    async def snapshot(self, organization_id) -> dict[str, Any]:
        now = datetime.now(UTC)
        async with self.database.transaction(organization_id) as session:
            outbox = (
                await session.execute(
                    select(
                        func.count().filter(
                            outbox_events.c.processed_at.is_(None),
                            outbox_events.c.dead_lettered_at.is_(None),
                        ).label("pending"),
                        func.count().filter(
                            outbox_events.c.dead_lettered_at.is_not(None)
                        ).label("dead_letters"),
                        func.min(outbox_events.c.occurred_at)
                        .filter(
                            outbox_events.c.processed_at.is_(None),
                            outbox_events.c.dead_lettered_at.is_(None),
                        )
                        .label("oldest"),
                    )
                )
            ).mappings().one()
            lag = await session.scalar(
                select(func.count())
                .select_from(
                    knowledge_facts.outerjoin(
                        search_projection_state,
                        (search_projection_state.c.organization_id
                         == knowledge_facts.c.organization_id)
                        & (search_projection_state.c.fact_id == knowledge_facts.c.fact_id)
                        & (search_projection_state.c.backend == self.backend),
                    )
                )
                .where(
                    or_(
                        search_projection_state.c.indexed_version.is_(None),
                        search_projection_state.c.indexed_version
                        < knowledge_facts.c.current_version,
                    )
                )
            )
        oldest = outbox["oldest"]
        return {
            "pending_events": outbox["pending"],
            "dead_letters": outbox["dead_letters"],
            "oldest_pending_seconds": (
                max((now - oldest).total_seconds(), 0) if oldest else None
            ),
            "projection_lag_facts": lag or 0,
        }
