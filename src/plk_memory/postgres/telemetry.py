"""Tenant-scoped PostgreSQL search and decision telemetry."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import insert, select, update
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


class PostgresTelemetryStore:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        organization_provider,
        raw_query_retention_days: int,
    ) -> None:
        self.database = database
        self._organization_provider = organization_provider
        self.raw_query_retention_days = raw_query_retention_days

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
        async with self.database.transaction(organization_id) as session:
            await self._redact_expired(session)
            await session.execute(
                insert(search_events).values(
                    organization_id=organization_id,
                    search_id=search_id,
                    client=client,
                    query_preview=query[:200] or None,
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
