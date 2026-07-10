"""Storage-neutral PLK domain models.

These models intentionally do not depend on Markdown, Git, SQLAlchemy, or
Graphiti.  They are the contract shared by the personal Git adapter and the
multi-writer PostgreSQL reference architecture.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

FactKind = Literal["philosophy", "logic", "knowhow"]
FactStatus = Literal["active", "invalidated"]
ActorType = Literal["human", "agent", "service"]
ChangeOperation = Literal["created", "updated", "invalidated", "promoted"]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ActorContext(FrozenModel):
    """Authenticated principal and tenant boundary for one operation."""

    organization_id: UUID
    actor_id: str = Field(min_length=1, max_length=255)
    actor_type: ActorType
    roles: frozenset[str] = frozenset()


class QueryScope(FrozenModel):
    organization_id: UUID
    actor_id: str = Field(min_length=1, max_length=255)
    roles: frozenset[str] = frozenset()


class FactPayload(FrozenModel):
    kind: FactKind
    statement: str
    why: str
    how_to_apply: str
    source: str
    source_type: Literal["user", "agent", "external-untrusted"]
    namespace: str
    tags: tuple[str, ...] = ()
    body: str = ""


class FactRecord(FrozenModel):
    id: str
    organization_id: UUID
    revision: int = Field(ge=1)
    payload: FactPayload
    status: FactStatus
    invalidation_reason: str | None = None
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class FactRevision(FrozenModel):
    fact_id: str
    organization_id: UUID
    revision: int = Field(ge=1)
    payload: FactPayload
    status: FactStatus
    invalidation_reason: str | None = None
    change_reason: str
    actor_id: str
    actor_type: ActorType
    created_at: datetime


class FactFilters(FrozenModel):
    namespaces: tuple[str, ...] = ()
    kind: FactKind | None = None
    status: FactStatus | None = "active"
    limit: int = Field(default=100, ge=1, le=1000)


class CreateFact(FrozenModel):
    fact_id: str
    payload: FactPayload
    change_reason: str
    supersedes: tuple[str, ...] = ()


class InvalidateFact(FrozenModel):
    fact_id: str
    reason: str


class WriteResult(FrozenModel):
    fact_id: str
    revision: int = Field(ge=1)
    replayed: bool
    event_id: UUID


class FactHistory(FrozenModel):
    fact_id: str
    current_revision: int = Field(ge=1)
    revisions: tuple[FactRevision, ...]
    supersedes: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()


class KnowledgeChanged(FrozenModel):
    event_id: UUID
    organization_id: UUID
    fact_id: str
    revision: int = Field(ge=1)
    operation: ChangeOperation
    occurred_at: datetime


class IndexEntry(FrozenModel):
    organization_id: UUID
    fact_id: str
    indexed_revision: int = Field(ge=1)
    content_hash: str
    backend_refs: tuple[str, ...] = ()
    last_event_id: UUID | None = None
    indexed_at: datetime


class SearchQuery(FrozenModel):
    scope: QueryScope
    query: str = Field(min_length=1)
    filters: FactFilters = FactFilters()


class IndexCandidate(FrozenModel):
    fact_id: str
    indexed_revision: int = Field(ge=1)
    score: float | None = None
