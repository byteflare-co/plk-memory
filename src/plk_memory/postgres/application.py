"""PostgreSQL-primary application service for REST and MCP callers.

The search index is deliberately only a candidate generator.  Every result is
rehydrated from the tenant-scoped repository before it is returned, so stale or
cross-tenant index documents can never become the response source of truth.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from ulid import ULID

from plk_memory.domain import (
    ActorContext,
    CreateFact,
    FactFilters,
    FactPayload,
    FactRecord,
    InvalidateFact,
    QueryScope,
    SearchQuery,
)
from plk_memory.ports import (
    ApprovalRepository,
    FactAlreadyExists,
    FactMissing,
    FactRepository,
    IdempotencyConflict,
    PersistenceError,
    RevisionConflict,
    SearchIndex,
)
from plk_memory.settings import Settings
from plk_memory.admission import CodexAdmissionRunner

ActorProvider = Callable[[], ActorContext]
ScopeProvider = Callable[[], QueryScope]
StatusProvider = Callable[[], Awaitable[dict[str, Any]]]


class PostgresAppServices:
    """Storage-neutral tool behavior backed by PostgreSQL and a derived index."""

    def __init__(
        self,
        *,
        repository: FactRepository,
        search_index: SearchIndex,
        actor_provider: ActorProvider,
        scope_provider: ScopeProvider,
        settings: Settings,
        status_provider: StatusProvider | None = None,
        close_callback: Callable[[], Awaitable[None]] | None = None,
        health_callback: Callable[[], Awaitable[None]] | None = None,
        approval_repository: ApprovalRepository | None = None,
        admission: CodexAdmissionRunner | None = None,
    ) -> None:
        self.repository = repository
        self.search_index = search_index
        self._actor_provider = actor_provider
        self._scope_provider = scope_provider
        self.settings = settings
        self._status_provider = status_provider
        self._close_callback = close_callback
        self._health_callback = health_callback
        self.approval_repository = approval_repository
        self.admission = admission or CodexAdmissionRunner(
            codex_bin=settings.codex_bin,
            timeout_seconds=settings.codex_admission_timeout_seconds,
        )

    async def start(self) -> None:
        await self.search_index.start()

    async def check_database(self) -> None:
        if self._health_callback is None:
            raise RuntimeError("database health callback is unavailable")
        await self._health_callback()

    async def close(self) -> None:
        graph = getattr(self.search_index, "graph", None)
        if graph is not None and hasattr(graph, "close"):
            await graph.close()
        if self._close_callback is not None:
            await self._close_callback()

    def _actor(self) -> ActorContext:
        actor = self._actor_provider()
        if not isinstance(actor, ActorContext):
            raise PermissionError("認証済みの actor context が必要")
        return actor

    def _scope(self) -> QueryScope:
        scope = self._scope_provider()
        if not isinstance(scope, QueryScope):
            raise PermissionError("認証済みの query scope が必要")
        return scope

    async def tool_search(
        self,
        query: str,
        namespaces: list[str] | None = None,
        kind: str | None = None,
        status: str = "active",
        limit: int = 10,
        reason: str | None = None,
        log_usage: bool = True,
    ) -> dict[str, Any]:
        # Usage/audit logging belongs at the HTTP/MCP request boundary.
        del reason, log_usage
        start = time.monotonic()
        scope = self._scope()
        allow_quarantine = bool(namespaces and "plk.quarantine" in namespaces)

        if not self.search_index.ready:
            return {
                "degraded": True,
                "message": "search index が未接続（degraded モード）",
                "hits": [],
            }

        try:
            # Fetch extra candidates because DB rehydration can discard stale,
            # deleted, invalidated, quarantined, or otherwise filtered entries.
            pool = min(max(limit * 5, 50), 1000)
            filters = FactFilters.model_validate(
                {
                    "namespaces": tuple(namespaces or ()),
                    "kind": kind,
                    "status": status,
                    "limit": pool,
                }
            )
            candidates = await self.search_index.search(
                SearchQuery(scope=scope, query=query, filters=filters)
            )
            candidate_ids = list(dict.fromkeys(item.fact_id for item in candidates))
            records = await self.repository.get_many(scope, candidate_ids)
        except (ValidationError, ValueError) as error:
            return {"error": f"検索条件が不正: {error}", "hits": []}
        except Exception as error:  # noqa: BLE001 - index failure is a degraded read
            return {
                "degraded": True,
                "message": f"search 失敗: {error}",
                "hits": [],
            }

        by_id = {record.id: record for record in records}
        results: list[dict[str, Any]] = []
        for candidate in candidates:
            record = by_id.get(candidate.fact_id)
            if record is None or not self._visible(
                record,
                namespaces=namespaces,
                kind=kind,
                status=status,
                allow_quarantine=allow_quarantine,
            ):
                continue
            results.append(self._search_hit(record, candidate.score))
            if len(results) >= limit:
                break

        return {
            "hits": results,
            "degraded": False,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }

    async def tool_add(
        self,
        *,
        namespace: str,
        kind: str,
        statement: str,
        why: str,
        how_to_apply: str,
        source: str,
        tags: list[str] | None = None,
        body: str = "",
        slug: str | None = None,
        source_type: str = "agent",
        supersedes: list[str] | None = None,
        idempotency_key: str | None = None,
        expected_revision: int | None = None,
        expected_superseded_revisions: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        del slug  # Filesystem naming is intentionally absent from the DB model.
        if self.settings.require_idempotency_key and not idempotency_key:
            return {"error": "idempotency_key is required"}
        if (
            self.settings.require_expected_revision
            and supersedes
            and expected_revision is None
            and expected_superseded_revisions is None
        ):
            return {"error": "expected revision is required for supersedes"}
        actor = self._actor()
        key = idempotency_key or f"generated:{uuid4()}"
        old_ids = tuple(dict.fromkeys(supersedes or ()))
        try:
            payload = FactPayload.model_validate(
                {
                    "namespace": namespace,
                    "kind": kind,
                    "statement": statement,
                    "why": why,
                    "how_to_apply": how_to_apply,
                    "source": source,
                    "tags": tuple(tags or ()),
                    "body": body,
                    "source_type": source_type,
                }
            )
            expected = await self._expected_superseded_revisions(
                actor,
                old_ids,
                expected_revision=expected_revision,
                explicit=expected_superseded_revisions,
            )
            result = await self.repository.create(
                actor,
                CreateFact(
                    fact_id=self._fact_id(actor, key),
                    payload=payload,
                    change_reason="MCP/APIからfactを追加",
                    supersedes=old_ids,
                ),
                expected_superseded_revisions=expected,
                idempotency_key=key,
            )
        except RevisionConflict as error:
            return self._revision_error(error)
        except (ValidationError, FactMissing, FactAlreadyExists, IdempotencyConflict,
                PersistenceError, ValueError) as error:
            return {"error": str(error)}

        return {
            "fact_id": result.fact_id,
            "revision": result.revision,
            "replayed": result.replayed,
            "event_id": str(result.event_id),
            "idempotency_key": key,
            "note": "索引はtransactional outboxから非同期で更新される",
        }

    async def tool_invalidate(
        self,
        fact_id: str,
        reason: str,
        *,
        idempotency_key: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        if self.settings.require_idempotency_key and not idempotency_key:
            return {"error": "idempotency_key is required"}
        if self.settings.require_expected_revision and expected_revision is None:
            return {"error": "expected_revision is required"}
        actor = self._actor()
        key = idempotency_key or f"generated:{uuid4()}"
        scope = QueryScope(
            organization_id=actor.organization_id,
            actor_id=actor.actor_id,
            roles=actor.roles,
        )
        try:
            revision = expected_revision
            if revision is None:
                revision = (await self.repository.get(scope, fact_id)).revision
            result = await self.repository.invalidate(
                actor,
                InvalidateFact(fact_id=fact_id, reason=reason),
                expected_revision=revision,
                idempotency_key=key,
            )
        except RevisionConflict as error:
            return self._revision_error(error)
        except (ValidationError, FactMissing, IdempotencyConflict, PersistenceError,
                ValueError) as error:
            return {"error": str(error)}

        return {
            "fact_id": result.fact_id,
            "revision": result.revision,
            "replayed": result.replayed,
            "event_id": str(result.event_id),
            "idempotency_key": key,
            "note": "索引はtransactional outboxから非同期で更新される",
        }

    async def tool_history(self, fact_id: str) -> dict[str, Any]:
        scope = self._scope()
        try:
            history = await self.repository.history(scope, fact_id)
            current = await self.repository.get(scope, fact_id)
        except FactMissing:
            return {"error": f"fact が存在しない: {fact_id}"}
        return {
            "id": fact_id,
            "path": None,
            "status": current.status,
            "current_revision": history.current_revision,
            "superseded_by": history.superseded_by[0]
            if history.superseded_by
            else None,
            "supersedes_chain": list(history.supersedes),
            "supersedes": list(history.supersedes),
            "superseded_by_chain": list(history.superseded_by),
            "revisions": [item.model_dump(mode="json") for item in history.revisions],
            "commits": [],
        }

    async def tool_status(self) -> dict[str, Any]:
        ready = self.search_index.ready
        status = {
            "storage_backend": "postgres",
            "search_index_ready": ready,
            "degraded": not ready,
            "maintenance": False,
            "head": None,
            "last_ingested_commit": None,
            "indexed_facts": None,
            "dead_letters": None,
            "unpushed_commits": 0,
            "pending_promotions": [],
            "message": "PostgreSQLが正本。索引更新はoutbox workerが担当",
        }
        if self._status_provider is not None:
            status.update(await self._status_provider())
        return status

    async def tool_propose_promotion(
        self,
        fact_id: str,
        reason: str | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if self.approval_repository is None:
            return {"error": "promotion/approval repository is unavailable"}
        if self.settings.require_idempotency_key and not idempotency_key:
            return {"error": "idempotency_key is required"}
        actor = self._actor()
        key = idempotency_key or f"generated:{uuid4()}"
        try:
            request = await self.approval_repository.propose(
                actor,
                fact_id,
                reason=reason or "shared knowledge promotion requested",
                idempotency_key=key,
            )
        except (PersistenceError, ValueError) as error:
            return {"error": str(error)}
        return {
            "promotion_id": str(request.request_id),
            "fact_id": request.fact_id,
            "source_revision": request.source_revision,
            "state": request.status,
            "idempotency_key": key,
        }

    async def tool_decide_promotion(
        self,
        request_id: str,
        decision: str,
        rationale: str,
        expected_revision: int,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if self.approval_repository is None:
            return {"error": "promotion/approval repository is unavailable"}
        if self.settings.require_idempotency_key and not idempotency_key:
            return {"error": "idempotency_key is required"}
        actor = self._actor()
        key = idempotency_key or f"generated:{uuid4()}"
        try:
            result = await self.approval_repository.decide(
                actor,
                request_id,
                decision=decision,
                rationale=rationale,
                expected_revision=expected_revision,
                idempotency_key=key,
            )
        except (PersistenceError, ValueError) as error:
            return {"error": str(error)}
        return {
            "promotion_id": str(result.request.request_id),
            "fact_id": result.request.fact_id,
            "state": result.request.status,
            "fact_revision": result.fact_revision,
            "event_id": str(result.event_id) if result.event_id else None,
            "replayed": result.replayed,
            "idempotency_key": key,
        }

    async def ui_list_facts(
        self,
        *,
        namespace: str | None,
        kind: str | None,
        status: str,
    ) -> list[dict[str, Any]]:
        scope = self._scope()
        records = await self.repository.list(
            scope,
            FactFilters.model_validate(
                {
                    "namespaces": (namespace,) if namespace else (),
                    "kind": kind,
                    "status": status,
                    "limit": 1000,
                }
            ),
        )
        return [self._search_hit(record, None) for record in records]

    async def ui_metrics_posts(self) -> tuple[list[dict], int]:
        """Corpus metrics are not available until PostgreSQL usage is recorded."""
        return [], 0

    async def ui_fact_detail(self, fact_id: str) -> dict[str, Any] | None:
        scope = self._scope()
        try:
            record = await self.repository.get(scope, fact_id)
            history = await self.repository.history(scope, fact_id)
        except FactMissing:
            return None
        return {
            "fact_id": fact_id,
            "path": None,
            "meta": {
                "id": record.id,
                "revision": record.revision,
                "status": record.status,
                "invalidation_reason": record.invalidation_reason,
                **record.payload.model_dump(mode="json"),
            },
            "body": record.payload.body,
            "history": history.model_dump(mode="json"),
        }

    # The first AI-feedback slice intentionally targets the live Git backend.
    # These explicit facade methods keep routing storage-neutral and fail closed.
    async def ui_submit_feedback(self, fact_id: str, feedback: str) -> dict[str, Any]:
        del fact_id, feedback
        return {"error": "AI feedback is not implemented for PostgreSQL backend"}

    async def ui_feedback_requests(self, fact_id: str) -> list[dict[str, Any]]:
        del fact_id
        return []

    async def ui_apply_feedback(self, request_id: str) -> dict[str, Any]:
        del request_id
        return {"error": "AI feedback is not implemented for PostgreSQL backend"}

    async def ui_reject_feedback(self, request_id: str) -> dict[str, Any]:
        del request_id
        return {"error": "AI feedback is not implemented for PostgreSQL backend"}

    async def ui_invalidate_fact(
        self, fact_id: str, reason: str, expected_hash: str
    ) -> dict[str, Any]:
        del fact_id, reason, expected_hash
        return {"error": "UI writes are not implemented for PostgreSQL backend"}

    async def admin_sync(self) -> dict[str, Any]:
        return {
            "error": "PostgreSQL-primaryでは手動Git syncは未対応。outbox workerを使用する"
        }

    async def admin_reindex(self) -> dict[str, Any]:
        return {
            "error": "PostgreSQL-primaryの管理reindex endpointは未対応"
        }

    async def _expected_superseded_revisions(
        self,
        actor: ActorContext,
        fact_ids: Sequence[str],
        *,
        expected_revision: int | None,
        explicit: dict[str, int] | None,
    ) -> dict[str, int]:
        if explicit is not None:
            if set(explicit) != set(fact_ids):
                raise ValueError(
                    "expected_superseded_revisionsは全supersedes対象を指定する必要がある"
                )
            return explicit
        if expected_revision is not None:
            if len(fact_ids) != 1:
                raise ValueError(
                    "expected_revisionはsupersedesが1件の場合のみ指定できる"
                )
            return {fact_ids[0]: expected_revision}
        if not fact_ids:
            return {}

        scope = QueryScope(
            organization_id=actor.organization_id,
            actor_id=actor.actor_id,
            roles=actor.roles,
        )
        records = await self.repository.get_many(scope, fact_ids)
        revisions = {record.id: record.revision for record in records}
        missing = [fact_id for fact_id in fact_ids if fact_id not in revisions]
        if missing:
            raise FactMissing(missing[0])
        return revisions

    @staticmethod
    def _visible(
        record: FactRecord,
        *,
        namespaces: list[str] | None,
        kind: str | None,
        status: str | None,
        allow_quarantine: bool,
    ) -> bool:
        payload = record.payload
        if payload.namespace == "plk.quarantine" and not allow_quarantine:
            return False
        if namespaces and payload.namespace not in namespaces:
            return False
        if kind is not None and payload.kind != kind:
            return False
        return status is None or record.status == status

    @staticmethod
    def _search_hit(record: FactRecord, score: float | None) -> dict[str, Any]:
        payload = record.payload
        return {
            "fact_id": record.id,
            "statement": payload.statement,
            "namespace": payload.namespace,
            "kind": payload.kind,
            "status": record.status,
            "path": None,
            # Never return text from the possibly stale derived index.
            "fact_text": payload.statement,
            "created_at": record.created_at.isoformat(),
            "revision": record.revision,
            "score": score,
        }

    @staticmethod
    def _revision_error(error: RevisionConflict) -> dict[str, Any]:
        return {
            "error": str(error),
            "retry": True,
            "conflict": True,
            "fact_id": error.fact_id,
            "expected_revision": error.expected,
            "actual_revision": error.actual,
        }

    @staticmethod
    def _fact_id(actor: ActorContext, idempotency_key: str) -> str:
        """Return the same resource id for every replay of one tenant request.

        The repository includes the generated resource id in its canonical
        request hash.  A fresh random ULID on retry would therefore turn a
        legitimate replay into an idempotency conflict.  Ordering comes from
        database timestamps, so a deterministic ULID is safe here.
        """

        digest = hashlib.sha256(
            f"{actor.organization_id}:{idempotency_key}".encode()
        ).digest()
        return str(ULID.from_bytes(digest[:16]))
