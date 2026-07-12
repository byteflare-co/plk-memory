"""Row-to-domain mapping and hashing helpers shared by the PostgreSQL write layer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from plk_memory.domain import (
    ActorContext,
    FactPayload,
    FactRecord,
    FactRevision,
)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def payload_hash(payload: FactPayload) -> str:
    return canonical_hash(payload.model_dump(mode="json"))


def revision_values(
    *,
    organization_id: UUID,
    revision_id: UUID,
    fact_id: str,
    version: int,
    payload: FactPayload,
    status: str,
    invalidation_reason: str | None,
    change_reason: str,
    actor: ActorContext,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "organization_id": organization_id,
        "revision_id": revision_id,
        "fact_id": fact_id,
        "version": version,
        "kind": payload.kind,
        "statement": payload.statement,
        "why": payload.why,
        "how_to_apply": payload.how_to_apply,
        "sources": [payload.source],
        "source_type": payload.source_type,
        "namespace": payload.namespace,
        "tags": list(payload.tags),
        "body": payload.body,
        "status": status,
        "invalidation_reason": invalidation_reason,
        "change_reason": change_reason,
        "actor_id": actor.actor_id,
        "actor_type": actor.actor_type,
        "content_hash": payload_hash(payload),
        "created_at": created_at,
    }


def record_from_row(row: Mapping[Any, Any]) -> FactRecord:
    return FactRecord(
        id=row["fact_id"],
        organization_id=row["organization_id"],
        revision=row["current_version"],
        payload=payload_from_row(row),
        status=row["status"],
        invalidation_reason=row["invalidation_reason"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_by=row["updated_by"],
        updated_at=row["updated_at"],
    )


def payload_from_row(row: Mapping[Any, Any]) -> FactPayload:
    sources = row["sources"]
    return FactPayload(
        kind=row["kind"],
        statement=row["statement"],
        why=row["why"],
        how_to_apply=row["how_to_apply"],
        source=sources[0] if sources else "",
        source_type=row["source_type"],
        namespace=row["namespace"],
        tags=tuple(row["tags"]),
        body=row["body"],
    )


def revision_from_row(row: Mapping[Any, Any]) -> FactRevision:
    return FactRevision(
        fact_id=row["fact_id"],
        organization_id=row["organization_id"],
        revision=row["version"],
        payload=payload_from_row(row),
        status=row["status"],
        invalidation_reason=row["invalidation_reason"],
        change_reason=row["change_reason"],
        actor_id=row["actor_id"],
        actor_type=row["actor_type"],
        created_at=row["created_at"],
    )
