"""storage_backend に応じたバックエンド合成（composition root）。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from plk_memory.admission import CodexAdmissionRunner
from plk_memory.auth import current_actor
from plk_memory.domain import ActorContext, QueryScope
from plk_memory.facts import FactService
from plk_memory.feedback import CodexFeedbackRunner, FeedbackCoordinator, FeedbackStore
from plk_memory.git_services import AppServices
from plk_memory.gitstore import GitStore
from plk_memory.graphindex import GraphIndex
from plk_memory.promotions import PromotionStore
from plk_memory.settings import Settings
from plk_memory.state import StateStore
from plk_memory.sync import SyncEngine
from plk_memory.usage_log import UsageLog

if TYPE_CHECKING:
    from plk_memory.postgres.application import PostgresAppServices


def build_services(settings: Settings, graph, promotion_backend=None,
                    enable_github_promotion: bool = False) -> "AppServices | PostgresAppServices":
    """Select a backend facade at the dynamic composition boundary."""
    if settings.storage_backend == "postgres":
        return build_postgres_services(settings, graph)
    store = GitStore(settings)
    facts = FactService(store, settings)
    if graph is None:
        graph = GraphIndex(settings)
    state_store = StateStore(settings.state_path)
    sync = SyncEngine(store, facts, graph, state_store, settings)
    usage = UsageLog(settings.usage_log_path)
    promotion_store = PromotionStore(settings.state_path.with_name("promotions.json"))
    feedback = FeedbackCoordinator(
        FeedbackStore(settings.feedback_path),
        CodexFeedbackRunner(
            working_dir=settings.data_repo_path,
            codex_bin=settings.codex_bin,
            timeout_seconds=settings.codex_feedback_timeout_seconds,
        ),
    )
    admission = CodexAdmissionRunner(
        codex_bin=settings.codex_bin,
        timeout_seconds=settings.codex_admission_timeout_seconds,
    )
    if promotion_backend is None and enable_github_promotion:
        from plk_memory.github_promotion import GitHubPromotionBackend
        promotion_backend = GitHubPromotionBackend(store, settings)
    return AppServices(
        settings=settings, store=store, facts=facts, graph=graph,
        sync=sync, state_store=state_store, usage=usage,
        promotion_store=promotion_store, promotion_backend=promotion_backend,
        feedback=feedback, admission=admission,
    )


def build_postgres_services(settings: Settings, graph=None):
    if not settings.database_url:
        raise RuntimeError("PLK_DATABASE_URL is required for postgres storage")
    from plk_memory.postgres.application import PostgresAppServices
    from plk_memory.postgres.approvals import PostgresApprovalRepository
    from plk_memory.postgres.database import PostgresDatabase
    from plk_memory.postgres.graph_adapter import PostgresGraphSearchIndex
    from plk_memory.postgres.repository import PostgresFactRepository
    from plk_memory.postgres.worker import PostgresProjectionStatus

    database = PostgresDatabase(
        settings.database_url,
        pool_size=settings.database_pool_size,
        application_name="plk-memory-api",
    )
    graph = graph or GraphIndex(settings)
    search_index = PostgresGraphSearchIndex(
        graph=graph,
        api_database=database,
        worker_database=None,
        settings=settings,
    )
    repository = PostgresFactRepository(database)

    def actor_provider() -> ActorContext:
        actor = current_actor.get()
        if actor is not None:
            return actor
        if settings.ui_organization_id:
            return ActorContext(
                organization_id=UUID(settings.ui_organization_id),
                actor_id="plk-web-ui",
                actor_type="human",
                roles=frozenset({"reader"}),
            )
        raise PermissionError("認証済みのactorまたはPLK_UI_ORGANIZATION_IDが必要")

    def scope_provider() -> QueryScope:
        actor = actor_provider()
        return QueryScope(
            organization_id=actor.organization_id,
            actor_id=actor.actor_id,
            roles=actor.roles,
        )

    projection_status = PostgresProjectionStatus(database)

    async def status_provider() -> dict:
        return await projection_status.snapshot(scope_provider().organization_id)

    return PostgresAppServices(
        repository=repository,
        search_index=search_index,
        actor_provider=actor_provider,
        scope_provider=scope_provider,
        settings=settings,
        status_provider=status_provider,
        close_callback=database.close,
        health_callback=database.ping,
        approval_repository=PostgresApprovalRepository(database),
        admission=CodexAdmissionRunner(
            codex_bin=settings.codex_bin,
            timeout_seconds=settings.codex_admission_timeout_seconds,
        ),
    )
