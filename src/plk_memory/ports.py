"""Ports for PLK persistence, change delivery, and derived search indexes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from plk_memory.domain import (
    ActorContext,
    CreateFact,
    FactFilters,
    FactHistory,
    FactRecord,
    IndexCandidate,
    IndexEntry,
    InvalidateFact,
    KnowledgeChanged,
    QueryScope,
    SearchQuery,
    WriteResult,
)


class PersistenceError(RuntimeError):
    """Base class for storage-neutral write failures."""


class FactMissing(PersistenceError):
    def __init__(self, fact_id: str):
        super().__init__(f"fact does not exist: {fact_id}")
        self.fact_id = fact_id


class FactAlreadyExists(PersistenceError):
    def __init__(self, fact_id: str):
        super().__init__(f"fact already exists: {fact_id}")
        self.fact_id = fact_id


class RevisionConflict(PersistenceError):
    def __init__(self, fact_id: str, expected: int, actual: int):
        super().__init__(
            f"revision conflict for {fact_id}: expected {expected}, actual {actual}"
        )
        self.fact_id = fact_id
        self.expected = expected
        self.actual = actual


class IdempotencyConflict(PersistenceError):
    """The same key was reused for a semantically different request."""


class FactRepository(Protocol):
    async def list(
        self, scope: QueryScope, filters: FactFilters
    ) -> Sequence[FactRecord]: ...

    async def get(self, scope: QueryScope, fact_id: str) -> FactRecord: ...

    async def get_many(
        self, scope: QueryScope, fact_ids: Sequence[str]
    ) -> Sequence[FactRecord]: ...

    async def create(
        self,
        actor: ActorContext,
        command: CreateFact,
        *,
        expected_superseded_revisions: dict[str, int],
        idempotency_key: str,
    ) -> WriteResult: ...

    async def invalidate(
        self,
        actor: ActorContext,
        command: InvalidateFact,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> WriteResult: ...

    async def history(self, scope: QueryScope, fact_id: str) -> FactHistory: ...


class ChangeFeed(Protocol):
    async def claim(
        self,
        *,
        consumer: str,
        limit: int,
        lease_until: datetime,
    ) -> Sequence[KnowledgeChanged]: ...

    async def ack(self, event_ids: Sequence[str]) -> None: ...

    async def fail(
        self, event_id: str, *, error: str, retry_at: datetime
    ) -> None: ...


class IndexStateRepository(Protocol):
    async def get(self, organization_id: str, fact_id: str) -> IndexEntry | None: ...

    async def put_if_newer(self, entry: IndexEntry) -> bool: ...

    async def mark_failed(self, event_id: str, error: str) -> None: ...


class SearchIndex(Protocol):
    @property
    def ready(self) -> bool: ...

    async def start(self) -> None: ...

    async def upsert(self, fact: FactRecord) -> IndexEntry: ...

    async def delete(
        self,
        organization_id: str,
        fact_id: str,
        old: IndexEntry | None,
    ) -> None: ...

    async def search(self, query: SearchQuery) -> Sequence[IndexCandidate]: ...

    async def clear(self, organization_id: str) -> None: ...
