"""Tenant-scoped PostgreSQL search and decision telemetry."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.schema import (
    action_events,
    decision_events,
    decision_search_links,
    intent_events,
    search_events,
)
from plk_memory.telemetry import (
    ActionCommand,
    DecisionCommand,
    FactReference,
    IntentCommand,
    TelemetryConflict,
    TelemetryError,
)


class PostgresTelemetryStore:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        organization_provider,
    ) -> None:
        self.database = database
        self._organization_provider = organization_provider

    def _organization_id(self) -> UUID:
        return self._organization_provider()

    async def _replay_if_matching(
        self,
        session,
        *,
        table,
        id_column,
        organization_id: UUID,
        identifier: str,
        client: str,
        request_hash: str,
        response_id: str,
        conflict_message: str,
    ) -> dict | None:
        existing = (
            await session.execute(
                select(table.c.request_hash, table.c.client).where(
                    table.c.organization_id == organization_id,
                    id_column == identifier,
                )
            )
        ).one_or_none()
        if existing is None:
            return None
        if existing.request_hash != request_hash or existing.client != client:
            raise TelemetryConflict(conflict_message)
        return {"recorded": True, "replayed": True, response_id: identifier}

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
        trace_id: str | None = None,
    ) -> None:
        organization_id = self._organization_id()
        async with self.database.transaction(organization_id) as session:
            if trace_id is not None:
                intent = (
                    await session.execute(
                        select(
                            intent_events.c.trace_id,
                            intent_events.c.side_effect,
                        ).where(
                            intent_events.c.organization_id == organization_id,
                            intent_events.c.trace_id == trace_id,
                            intent_events.c.client == client,
                        )
                    )
                ).one_or_none()
                if intent is None:
                    raise TelemetryError("unknown trace_id for this client")
            await session.execute(
                insert(search_events).values(
                    organization_id=organization_id,
                    search_id=search_id,
                    client=client,
                    trace_id=trace_id,
                    query_preview=None,
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

    async def record_intent(self, *, client: str, command: IntentCommand) -> dict:
        organization_id = self._organization_id()
        request_hash = command.request_hash()
        try:
            async with self.database.transaction(organization_id) as session:
                replay = await self._replay_if_matching(
                    session,
                    table=intent_events,
                    id_column=intent_events.c.trace_id,
                    organization_id=organization_id,
                    identifier=command.trace_id,
                    client=client,
                    request_hash=request_hash,
                    response_id="trace_id",
                    conflict_message="trace_id is already used for a different intent",
                )
                if replay is not None:
                    return replay
                await session.execute(
                    insert(intent_events).values(
                        organization_id=organization_id,
                        trace_id=command.trace_id,
                        client=client,
                        operation_type=command.operation_type,
                        intent_hash=hashlib.sha256(command.intent.encode()).hexdigest(),
                        target_hash=hashlib.sha256(command.target.encode()).hexdigest()
                        if command.target
                        else None,
                        side_effect=command.side_effect,
                        plk_requirement=command.plk_requirement,
                        no_search_reason=command.no_search_reason,
                        request_hash=request_hash,
                    )
                )
        except IntegrityError as error:
            async with self.database.transaction(organization_id) as session:
                replay = await self._replay_if_matching(
                    session,
                    table=intent_events,
                    id_column=intent_events.c.trace_id,
                    organization_id=organization_id,
                    identifier=command.trace_id,
                    client=client,
                    request_hash=request_hash,
                    response_id="trace_id",
                    conflict_message=(
                        "trace_id was created concurrently with different intent"
                    ),
                )
            if replay is not None:
                return replay
            raise TelemetryConflict(
                "trace_id was created concurrently with different intent"
            ) from error
        return {"recorded": True, "replayed": False, "trace_id": command.trace_id}

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
                replay = await self._replay_if_matching(
                    session,
                    table=decision_events,
                    id_column=decision_events.c.decision_id,
                    organization_id=organization_id,
                    identifier=command.decision_id,
                    client=client,
                    request_hash=request_hash,
                    response_id="decision_id",
                    conflict_message=(
                        "decision_id is already used for a different decision"
                    ),
                )
                if replay is not None:
                    return replay

                search_rows = (
                    await session.execute(
                        select(
                            search_events.c.search_id,
                            search_events.c.client,
                            search_events.c.trace_id,
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
                traced_searches = {
                    item: searches[item].trace_id
                    for item in command.search_ids
                    if isinstance(searches[item].trace_id, str)
                }
                if traced_searches and command.trace_id is None:
                    raise TelemetryError(
                        "trace-linked searches require decision trace_id"
                    )
                if command.trace_id is not None:
                    intent = (
                        await session.execute(
                            select(intent_events.c.trace_id).where(
                                intent_events.c.organization_id == organization_id,
                                intent_events.c.trace_id == command.trace_id,
                                intent_events.c.client == client,
                            )
                        )
                    ).one_or_none()
                    if intent is None:
                        raise TelemetryError("unknown trace_id for this client")
                    mismatched = [
                        item
                        for item in command.search_ids
                        if searches[item].trace_id != command.trace_id
                    ]
                    if mismatched:
                        raise TelemetryError(
                            "search_ids do not belong to trace_id: "
                            + ", ".join(mismatched)
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
                    (
                        await session.execute(
                            select(decision_search_links.c.search_id).where(
                                decision_search_links.c.organization_id
                                == organization_id,
                                decision_search_links.c.search_id.in_(
                                    command.search_ids
                                ),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
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
                        trace_id=command.trace_id,
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
            async with self.database.transaction(organization_id) as session:
                replay = await self._replay_if_matching(
                    session,
                    table=decision_events,
                    id_column=decision_events.c.decision_id,
                    organization_id=organization_id,
                    identifier=command.decision_id,
                    client=client,
                    request_hash=request_hash,
                    response_id="decision_id",
                    conflict_message=("decision or search was resolved concurrently"),
                )
            if replay is not None:
                return replay
            raise TelemetryConflict(
                "decision or search was resolved concurrently"
            ) from error
        return {
            "recorded": True,
            "replayed": False,
            "decision_id": command.decision_id,
        }

    async def record_action(self, *, client: str, command: ActionCommand) -> dict:
        organization_id = self._organization_id()
        request_hash = command.request_hash()
        try:
            async with self.database.transaction(organization_id) as session:
                replay = await self._replay_if_matching(
                    session,
                    table=action_events,
                    id_column=action_events.c.event_id,
                    organization_id=organization_id,
                    identifier=command.event_id,
                    client=client,
                    request_hash=request_hash,
                    response_id="event_id",
                    conflict_message=(
                        "event_id is already used for a different action event"
                    ),
                )
                if replay is not None:
                    return replay
                intent = (
                    await session.execute(
                        select(
                            intent_events.c.trace_id,
                            intent_events.c.side_effect,
                        ).where(
                            intent_events.c.organization_id == organization_id,
                            intent_events.c.trace_id == command.trace_id,
                            intent_events.c.client == client,
                        )
                    )
                ).one_or_none()
                if intent is None:
                    raise TelemetryError("unknown trace_id for this client")
                if intent.side_effect != command.side_effect:
                    raise TelemetryError(
                        "action side_effect must match intent side_effect"
                    )
                if command.decision_id is not None:
                    decision = (
                        await session.execute(
                            select(decision_events.c.decision_id).where(
                                decision_events.c.organization_id == organization_id,
                                decision_events.c.decision_id == command.decision_id,
                                decision_events.c.trace_id == command.trace_id,
                                decision_events.c.client == client,
                            )
                        )
                    ).one_or_none()
                    if decision is None:
                        raise TelemetryError("decision_id does not belong to trace_id")
                if command.phase == "completed":
                    attempted = (
                        await session.execute(
                            select(action_events.c.event_id)
                            .where(
                                action_events.c.organization_id == organization_id,
                                action_events.c.action_id == command.action_id,
                                action_events.c.trace_id == command.trace_id,
                                action_events.c.phase == "attempted",
                            )
                            .limit(1)
                        )
                    ).one_or_none()
                    if attempted is None:
                        raise TelemetryError(
                            "completed action requires an attempted event"
                        )
                await session.execute(
                    insert(action_events).values(
                        organization_id=organization_id,
                        event_id=command.event_id,
                        action_id=command.action_id,
                        trace_id=command.trace_id,
                        client=client,
                        phase=command.phase,
                        action_type=command.action_type,
                        tool_name=command.tool_name,
                        target_hash=hashlib.sha256(command.target.encode()).hexdigest()
                        if command.target
                        else None,
                        side_effect=command.side_effect,
                        outcome=command.outcome,
                        decision_id=command.decision_id,
                        error_category=command.error_category,
                        request_hash=request_hash,
                    )
                )
        except IntegrityError as error:
            async with self.database.transaction(organization_id) as session:
                replay = await self._replay_if_matching(
                    session,
                    table=action_events,
                    id_column=action_events.c.event_id,
                    organization_id=organization_id,
                    identifier=command.event_id,
                    client=client,
                    request_hash=request_hash,
                    response_id="event_id",
                    conflict_message=(
                        "event_id was created concurrently with different action"
                    ),
                )
            if replay is not None:
                return replay
            raise TelemetryConflict(
                "event_id was created concurrently with different action"
            ) from error
        return {"recorded": True, "replayed": False, "event_id": command.event_id}

    async def list_usage(self) -> list[dict]:
        organization_id = self._organization_id()
        async with self.database.transaction(organization_id) as session:
            searches = (
                (
                    await session.execute(
                        select(search_events).order_by(search_events.c.created_at)
                    )
                )
                .mappings()
                .all()
            )
            decisions = (
                (
                    await session.execute(
                        select(decision_events).order_by(decision_events.c.created_at)
                    )
                )
                .mappings()
                .all()
            )
            intents = (
                (
                    await session.execute(
                        select(intent_events).order_by(intent_events.c.created_at)
                    )
                )
                .mappings()
                .all()
            )
            actions = (
                (
                    await session.execute(
                        select(action_events).order_by(action_events.c.created_at)
                    )
                )
                .mappings()
                .all()
            )
        records = [
            {
                "ts": row["created_at"].isoformat(),
                "client": row["client"],
                "trace_id": row["trace_id"],
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
                "trace_id": row["trace_id"],
                "tool": "plk_record_decision",
                "decision_id": row["decision_id"],
                "search_ids": row["search_ids"],
                "used_fact_ids": [ref["fact_id"] for ref in row["used_fact_refs"]],
                "used_fact_refs": row["used_fact_refs"],
                "effect": row["effect"],
                "no_use_reason": row["no_use_reason"],
                "request_hash": row["request_hash"],
                "outcome": "recorded",
            }
            for row in decisions
        )
        records.extend(
            {
                "ts": row["created_at"].isoformat(),
                "client": row["client"],
                "tool": "plk_record_intent",
                "trace_id": row["trace_id"],
                "operation_type": row["operation_type"],
                "intent_hash": row["intent_hash"],
                "target_hash": row["target_hash"],
                "side_effect": row["side_effect"],
                "plk_requirement": row["plk_requirement"],
                "no_search_reason": row["no_search_reason"],
                "request_hash": row["request_hash"],
                "outcome": "recorded",
            }
            for row in intents
        )
        records.extend(
            {
                "ts": row["created_at"].isoformat(),
                "client": row["client"],
                "tool": "plk_record_action",
                "event_id": row["event_id"],
                "action_id": row["action_id"],
                "trace_id": row["trace_id"],
                "phase": row["phase"],
                "action_type": row["action_type"],
                "tool_name": row["tool_name"],
                "target_hash": row["target_hash"],
                "side_effect": row["side_effect"],
                "outcome": row["outcome"],
                "decision_id": row["decision_id"],
                "error_category": row["error_category"],
                "request_hash": row["request_hash"],
            }
            for row in actions
        )
        records.sort(key=lambda item: item["ts"])
        return records
