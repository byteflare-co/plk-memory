"""Tenant-partitioned GraphIndex adapter for the PostgreSQL runtime."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

import frontmatter
from sqlalchemy import delete, select

from plk_memory.domain import (
    FactRecord,
    IndexCandidate,
    IndexEntry,
    SearchQuery,
)
from plk_memory.graphindex import SearchHit
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.schema import search_projection_state
from plk_memory.settings import Settings
from plk_memory.state import FactIndexEntry


class GraphIndexLike(Protocol):
    @property
    def ready(self) -> bool: ...

    async def start(self) -> None: ...

    async def upsert_fact(
        self,
        post: frontmatter.Post,
        old: FactIndexEntry | None,
        *,
        group_id_override: str | None = None,
        identity_seed: str | None = None,
    ) -> FactIndexEntry: ...

    async def delete_fact(self, old: FactIndexEntry) -> None: ...

    async def search(
        self,
        query: str,
        group_ids: list[str],
        uuid_to_fact: dict[str, str],
        limit: int = 10,
    ) -> Sequence[SearchHit]: ...

    async def clear(self, group_ids: list[str]) -> None: ...


def record_to_post(fact: FactRecord) -> frontmatter.Post:
    """Convert the storage-neutral current row at the legacy graph boundary."""

    return frontmatter.Post(
        fact.payload.body,
        id=fact.id,
        kind=fact.payload.kind,
        statement=fact.payload.statement,
        why=fact.payload.why,
        how_to_apply=fact.payload.how_to_apply,
        source=fact.payload.source,
        source_type=fact.payload.source_type,
        namespace=fact.payload.namespace,
        status=fact.status,
        invalidation_reason=fact.invalidation_reason,
        written_by=fact.updated_by,
        created_at=fact.created_at,
        invalidated_at=fact.updated_at if fact.status == "invalidated" else None,
        superseded_by=None,
        tags=list(fact.payload.tags),
    )


class PostgresGraphSearchIndex:
    """Use Graphiti for candidates while PostgreSQL owns visibility and freshness."""

    def __init__(
        self,
        *,
        graph: GraphIndexLike,
        api_database: PostgresDatabase,
        worker_database: PostgresDatabase | None,
        settings: Settings,
        backend: str = "graphiti",
    ) -> None:
        self.graph = graph
        self.api_database = api_database
        self.worker_database = worker_database
        self.settings = settings
        self.backend = backend

    @property
    def ready(self) -> bool:
        return self.graph.ready

    async def start(self) -> None:
        await self.graph.start()

    def partition_for(self, organization_id, namespace: str) -> str:
        base = self.settings.group_for(namespace)
        return f"org-{organization_id.hex}-{base}"

    async def upsert(
        self, fact: FactRecord, old: IndexEntry | None = None
    ) -> IndexEntry:
        old_graph = None
        if old is not None:
            old_graph = FactIndexEntry(
                episode_uuids=list(old.backend_refs),
                content_hash=old.content_hash,
                group_id=old.partition or self.settings.main_group,
            )
        partition = self.partition_for(
            fact.organization_id, fact.payload.namespace
        )
        result = await self.graph.upsert_fact(
            record_to_post(fact),
            old_graph,
            group_id_override=partition,
            identity_seed=f"{fact.organization_id}:{fact.id}:{fact.revision}",
        )
        return IndexEntry(
            organization_id=fact.organization_id,
            fact_id=fact.id,
            indexed_revision=fact.revision,
            content_hash=result.content_hash or "",
            backend_refs=tuple(result.episode_uuids),
            partition=result.group_id or partition,
            indexed_at=datetime.now(UTC),
        )

    async def delete(
        self,
        organization_id: str,
        fact_id: str,
        old: IndexEntry | None,
    ) -> None:
        del organization_id, fact_id
        if old is None:
            return
        await self.graph.delete_fact(
            FactIndexEntry(
                episode_uuids=list(old.backend_refs),
                content_hash=old.content_hash,
                group_id=old.partition or self.settings.main_group,
            )
        )

    async def search(self, query: SearchQuery) -> Sequence[IndexCandidate]:
        organization_id = query.scope.organization_id
        async with self.api_database.transaction(organization_id) as session:
            rows = (
                await session.execute(
                    select(search_projection_state).where(
                        search_projection_state.c.organization_id == organization_id,
                        search_projection_state.c.backend == self.backend,
                    )
                )
            ).mappings().all()
        uuid_to_fact: dict[str, str] = {}
        indexed_revision: dict[str, int] = {}
        for row in rows:
            indexed_revision[row["fact_id"]] = row["indexed_version"]
            for backend_ref in row["backend_refs"]:
                uuid_to_fact[str(backend_ref)] = row["fact_id"]

        namespaces = query.filters.namespaces
        if namespaces:
            groups = [
                self.partition_for(organization_id, namespace)
                for namespace in namespaces
            ]
        else:
            groups = [
                self.partition_for(organization_id, f"plk.domain.{domain}")
                for domain in self.settings.domains
            ] + [self.partition_for(organization_id, "plk.shared")]
        hits = await self.graph.search(
            query.query,
            sorted(set(groups)),
            uuid_to_fact,
            limit=query.filters.limit,
        )
        return tuple(
            IndexCandidate(
                fact_id=hit.fact_id,
                indexed_revision=indexed_revision[hit.fact_id],
                score=hit.score,
            )
            for hit in hits
            if hit.fact_id in indexed_revision
        )

    async def clear(self, organization_id: str) -> None:
        from uuid import UUID

        organization_uuid = UUID(organization_id)
        groups = [
            self.partition_for(organization_uuid, namespace)
            for namespace in (
                [f"plk.domain.{domain}" for domain in self.settings.domains]
                + ["plk.shared", "plk.quarantine"]
            )
        ]
        await self.graph.clear(groups)
        if self.worker_database is None:
            raise RuntimeError("clear requires a worker database")
        async with self.worker_database.worker_transaction() as session:
            await session.execute(
                delete(search_projection_state).where(
                    search_projection_state.c.organization_id == organization_uuid,
                    search_projection_state.c.backend == self.backend,
                )
            )
