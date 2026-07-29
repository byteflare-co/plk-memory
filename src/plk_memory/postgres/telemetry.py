"""Tenant-scoped PostgreSQL search and decision telemetry."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.schema import (
    decision_events,
    decision_search_links,
    search_events,
)
from plk_memory.telemetry import (
    DecisionCommand,
    FactReference,
    TelemetryConflict,
    TelemetryError,
)

logger = logging.getLogger(__name__)


class PostgresTelemetryStore:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        organization_provider,
        raw_query_retention_days: int,
        maintenance_database: PostgresDatabase | None = None,
    ) -> None:
        self.database = database
        self.maintenance_database = maintenance_database
        self._organization_provider = organization_provider
        self.raw_query_retention_days = raw_query_retention_days
        self._redaction_task: asyncio.Task[None] | None = None
        self._redaction_wakeup = asyncio.Event()
        self._start_lock = asyncio.Lock()
        self._maintenance_ready = False

    def _organization_id(self) -> UUID:
        return self._organization_provider()

    async def record_search(
        self,
        *,
        client: str,
        search_id: str,
        query: str,
        hits: int,
        latency_ms: int,
        reason: str | None,
        fact_refs: list[FactReference],
        outcome: str,
    ) -> None:
        organization_id = self._organization_id()
        if (
            self.maintenance_database is not None
            and self.raw_query_retention_days > 0
            and (self._redaction_task is None or self._redaction_task.done())
        ):
            await self.start()
        async with self.database.transaction(organization_id) as session:
            await session.execute(
                insert(search_events).values(
                    organization_id=organization_id,
                    search_id=search_id,
                    client=client,
                    query_preview=(
                        query[:200] or None
                        if self.raw_query_retention_days > 0
                        and self._maintenance_ready
                        else None
                    ),
                    query_hash=hashlib.sha256(query.encode()).hexdigest(),
                    reason=reason[:64] if reason else None,
                    outcome=outcome,
                    hits=hits,
                    latency_ms=latency_ms,
                    fact_refs=[
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in fact_refs
                    ],
                )
            )
        if self._maintenance_ready:
            self._redaction_wakeup.set()

    async def record_decision(
        self,
        *,
        client: str,
        command: DecisionCommand,
    ) -> dict:
        organization_id = self._organization_id()
        request_hash = command.request_hash()
        try:
            async with self.database.transaction(organization_id) as session:
                existing = (
                    await session.execute(
                        select(
                            decision_events.c.request_hash,
                            decision_events.c.client,
                        ).where(
                            decision_events.c.organization_id == organization_id,
                            decision_events.c.decision_id == command.decision_id,
                        )
                    )
                ).one_or_none()
                if existing is not None:
                    if existing.request_hash != request_hash or existing.client != client:
                        raise TelemetryConflict(
                            "decision_id is already used for a different decision"
                        )
                    return {
                        "recorded": True,
                        "replayed": True,
                        "decision_id": command.decision_id,
                    }

                search_rows = (
                    await session.execute(
                        select(
                            search_events.c.search_id,
                            search_events.c.client,
                            search_events.c.hits,
                            search_events.c.outcome,
                            search_events.c.fact_refs,
                        ).where(
                            search_events.c.organization_id == organization_id,
                            search_events.c.search_id.in_(command.search_ids),
                        )
                    )
                ).all()
                searches = {row.search_id: row for row in search_rows}
                missing = [item for item in command.search_ids if item not in searches]
                if missing:
                    raise TelemetryError(f"unknown search_ids: {', '.join(missing)}")
                foreign = [
                    item
                    for item in command.search_ids
                    if searches[item].client != client
                ]
                if foreign:
                    raise TelemetryError(
                        f"search_ids belong to another client: {', '.join(foreign)}"
                    )
                no_hits = [
                    item
                    for item in command.search_ids
                    if searches[item].outcome != "ok" or searches[item].hits <= 0
                ]
                if no_hits:
                    raise TelemetryError(
                        "search_ids did not return facts: " + ", ".join(no_hits)
                    )
                already_resolved = (
                    await session.execute(
                        select(decision_search_links.c.search_id).where(
                            decision_search_links.c.organization_id == organization_id,
                            decision_search_links.c.search_id.in_(command.search_ids),
                        )
                    )
                ).scalars().all()
                if already_resolved:
                    raise TelemetryConflict(
                        "search_ids are already resolved: "
                        + ", ".join(already_resolved)
                    )
                refs_by_id = {
                    ref["fact_id"]: ref
                    for row in search_rows
                    for ref in row.fact_refs
                    if isinstance(ref, dict) and isinstance(ref.get("fact_id"), str)
                }
                invalid = [
                    item for item in command.used_fact_ids if item not in refs_by_id
                ]
                if invalid:
                    raise TelemetryError(
                        "used_fact_ids were not returned by these searches: "
                        + ", ".join(invalid)
                    )
                await session.execute(
                    insert(decision_events).values(
                        organization_id=organization_id,
                        decision_id=command.decision_id,
                        client=client,
                        effect=command.effect,
                        no_use_reason=command.no_use_reason,
                        search_ids=list(command.search_ids),
                        used_fact_refs=[
                            refs_by_id[fact_id] for fact_id in command.used_fact_ids
                        ],
                        request_hash=request_hash,
                    )
                )
                await session.execute(
                    insert(decision_search_links),
                    [
                        {
                            "organization_id": organization_id,
                            "search_id": search_id,
                            "decision_id": command.decision_id,
                        }
                        for search_id in command.search_ids
                    ],
                )
        except IntegrityError as error:
            raise TelemetryConflict(
                "decision or search was resolved concurrently"
            ) from error
        return {
            "recorded": True,
            "replayed": False,
            "decision_id": command.decision_id,
        }

    async def list_usage(self) -> list[dict]:
        organization_id = self._organization_id()
        async with self.database.transaction(organization_id) as session:
            await self._redact_expired(session)
            searches = (
                await session.execute(
                    select(search_events).order_by(search_events.c.created_at)
                )
            ).mappings().all()
            decisions = (
                await session.execute(
                    select(decision_events).order_by(decision_events.c.created_at)
                )
            ).mappings().all()
        records = [
            {
                "ts": row["created_at"].isoformat(),
                "client": row["client"],
                "tool": "plk_search",
                "query": row["query_preview"],
                "query_hash": row["query_hash"],
                "hits": row["hits"],
                "latency_ms": row["latency_ms"],
                "reason": row["reason"],
                "fact_ids": [ref["fact_id"] for ref in row["fact_refs"]],
                "fact_refs": row["fact_refs"],
                "search_id": row["search_id"],
                "outcome": row["outcome"],
            }
            for row in searches
        ]
        records.extend(
            {
                "ts": row["created_at"].isoformat(),
                "client": row["client"],
                "tool": "plk_record_decision",
                "decision_id": row["decision_id"],
                "search_ids": row["search_ids"],
                "used_fact_ids": [
                    ref["fact_id"] for ref in row["used_fact_refs"]
                ],
                "used_fact_refs": row["used_fact_refs"],
                "effect": row["effect"],
                "no_use_reason": row["no_use_reason"],
                "request_hash": row["request_hash"],
                "outcome": "recorded",
            }
            for row in decisions
        )
        records.sort(key=lambda item: item["ts"])
        return records

    async def start(self) -> None:
        if (
            self.maintenance_database is None
            or self.raw_query_retention_days <= 0
        ):
            return
        async with self._start_lock:
            if self._redaction_task is not None and not self._redaction_task.done():
                return
            retry = False
            try:
                next_redaction = await self._redact_all_expired()
                self._maintenance_ready = True
            except Exception:  # noqa: BLE001 - hash-only fallback preserves search
                logger.exception("PostgreSQL telemetry preview maintenance unavailable")
                next_redaction = None
                retry = True
                self._maintenance_ready = False
            self._redaction_task = asyncio.create_task(
                self._redact_queries_when_due(next_redaction, retry=retry)
            )

    async def close(self) -> None:
        task = self._redaction_task
        self._redaction_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._maintenance_ready = False
        if self.maintenance_database is not None:
            await self.maintenance_database.close()

    async def _redact_queries_when_due(
        self,
        next_redaction: datetime | None,
        *,
        retry: bool,
    ) -> None:
        while True:
            try:
                if retry:
                    await asyncio.sleep(60)
                else:
                    self._redaction_wakeup.clear()
                    if next_redaction is None:
                        await self._redaction_wakeup.wait()
                    else:
                        delay = max(
                            (
                                next_redaction - datetime.now(timezone.utc)
                            ).total_seconds(),
                            0.05,
                        )
                        try:
                            await asyncio.wait_for(
                                self._redaction_wakeup.wait(),
                                timeout=delay,
                            )
                        except TimeoutError:
                            pass
                next_redaction = await self._redact_all_expired()
                self._maintenance_ready = True
                retry = False
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - retry without blocking search
                if not retry:
                    logger.exception(
                        "PostgreSQL telemetry preview maintenance interrupted"
                    )
                self._maintenance_ready = False
                retry = True

    async def _redact_all_expired(self) -> datetime | None:
        if self.maintenance_database is None:
            return None
        async with self.maintenance_database.worker_transaction() as session:
            await self._redact_expired(session)
            oldest = await session.scalar(
                select(func.min(search_events.c.created_at)).where(
                    search_events.c.query_preview.is_not(None)
                )
            )
        if oldest is None:
            return None
        return oldest + timedelta(days=self.raw_query_retention_days)

    async def _redact_expired(self, session) -> None:
        await session.execute(
            update(search_events)
            .where(
                search_events.c.query_preview.is_not(None),
                search_events.c.created_at
                < datetime.now(timezone.utc)
                - timedelta(days=self.raw_query_retention_days),
            )
            .values(query_preview=None)
        )
