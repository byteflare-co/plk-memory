"""FastAPI + FastMCP 結線（設計書 §8, Task 9 brief）。

ルート登録順は REST → `app.mount("/mcp", mcp_app)`（Mount が全パスを食う問題への対処）。
lifespan は `combine_lifespans` で FastAPI 側の初期化（ensure_repo → graph.start →
初回 sync → 周期 sync）と FastMCP 側の lifespan を束ねる。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

from plk_memory.auth import BearerAuthMiddleware, current_actor, current_client
from plk_memory.domain import ActorContext, QueryScope
from plk_memory.facts import FactError, FactNotFound, FactService
from plk_memory.gitstore import GitStore, WriteConflict
from plk_memory.graphindex import GraphIndex
from plk_memory.mcp_tools import build_mcp
from plk_memory.promotions import PromotionState, PromotionStore, new_promotion, transition
from plk_memory.settings import Settings
from plk_memory.state import StateStore
from plk_memory.sync import SyncEngine
from plk_memory.usage_log import UsageLog
from plk_memory.webui import build_ui_router

try:
    from fastmcp.utilities.lifespan import combine_lifespans
except ImportError:  # pragma: no cover - フォールバック（API 変更時のみ到達）
    from contextlib import AsyncExitStack

    def combine_lifespans(*lifespans):
        @asynccontextmanager
        async def combined(app):
            async with AsyncExitStack() as stack:
                for ls in lifespans:
                    await stack.enter_async_context(ls(app))
                yield

        return combined


class AppServices:
    """REST/MCP 双方から呼ばれる実体関数のコンテナ（テスト容易性のため薄いラッパから分離）。"""

    def __init__(
        self,
        *,
        settings: Settings,
        store: GitStore,
        facts: FactService,
        graph,
        sync: SyncEngine,
        state_store: StateStore,
        usage: UsageLog,
        promotion_store: PromotionStore,
        promotion_backend=None,
    ):
        self.settings = settings
        self.store = store
        self.facts = facts
        self.graph = graph
        self.sync = sync
        self.state_store = state_store
        self.usage = usage
        self.promotion_store = promotion_store
        self.promotion_backend = promotion_backend
        self._bg_tasks: set[asyncio.Task] = set()

    # --- 内部ヘルパー ---

    def _require_client(self) -> str:
        client = current_client.get()
        if client is None:
            raise PermissionError(
                "認証されていない呼び出し（current_client 未設定 — 認証レイヤ外からの直接呼び出しは不可）"
            )
        return client

    def _spawn_sync(self) -> None:
        task = asyncio.create_task(self.sync.sync())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _group_ids_for(self, namespaces: list[str] | None) -> list[str]:
        quarantine = self.settings.quarantine_group
        if namespaces:
            include_quarantine = "plk.quarantine" in namespaces
            groups = {
                self.settings.group_for(ns)
                for ns in namespaces
                if ns != "plk.quarantine" or include_quarantine
            }
            if include_quarantine:
                groups.add(quarantine)
            return sorted(groups) if groups else [self.settings.main_group]
        return [g for g in self.settings.all_groups() if g != quarantine]

    # --- ツール実体 ---

    async def tool_search(
        self,
        query: str,
        namespaces: list[str] | None = None,
        kind: str | None = None,
        status: str = "active",
        limit: int = 10,
        reason: str | None = None,
    ) -> dict:
        client = current_client.get()
        start = time.monotonic()
        allow_quarantine = bool(namespaces and "plk.quarantine" in namespaces)

        if not self.graph.ready:
            self.usage.log(client, "plk_search", query=query, hits=0, reason=reason)
            return {"degraded": True, "message": "graph index が未接続（degraded モード）", "hits": []}

        group_ids = self._group_ids_for(namespaces)
        state = self.state_store.load()
        uuid_to_fact = {
            uuid: fact_id for fact_id, entry in state.facts.items() for uuid in entry.episode_uuids
        }

        pool = max(limit * 5, 50)
        try:
            raw_hits = await self.graph.search(query, group_ids, uuid_to_fact, limit=pool)
        except Exception as e:  # noqa: BLE001 - graph 障害は degraded として返す（設計書 §8）
            self.usage.log(client, "plk_search", query=query, hits=0, reason=reason)
            return {"degraded": True, "message": f"search 失敗: {e}", "hits": []}

        results = []
        for hit in raw_hits:
            try:
                post, rel = self.facts.get(hit.fact_id)
            except FactNotFound:
                continue
            ns = post.get("namespace")
            if ns == "plk.quarantine" and not allow_quarantine:
                continue
            if kind is not None and post.get("kind") != kind:
                continue
            if status is not None and post.get("status") != status:
                continue
            if namespaces and ns not in namespaces:
                continue
            results.append(
                {
                    "fact_id": hit.fact_id,
                    "statement": post.get("statement"),
                    "namespace": ns,
                    "kind": post.get("kind"),
                    "status": post.get("status"),
                    "path": rel,
                    "fact_text": hit.fact_text,
                    "created_at": post.get("created_at"),
                }
            )
            if len(results) >= limit:
                break

        latency_ms = int((time.monotonic() - start) * 1000)
        self.usage.log(
            client, "plk_search", query=query, hits=len(results),
            latency_ms=latency_ms, reason=reason,
            fact_ids=[r["fact_id"] for r in results],
        )
        return {"hits": results, "degraded": False}

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
    ) -> dict:
        del idempotency_key, expected_revision, expected_superseded_revisions
        client = self._require_client()
        if self.sync.maintenance:
            return {"error": "maintenance 中（reindex 実行中）", "retry": True}
        try:
            fact_id = await self.facts.add(
                client=client, namespace=namespace, kind=kind, statement=statement,
                why=why, how_to_apply=how_to_apply, source=source, tags=tags, body=body,
                slug=slug, source_type=source_type, supersedes=supersedes,
            )
        except FactError as e:
            return {"error": str(e)}
        except WriteConflict as e:
            return {"error": str(e), "retry": True}
        self._spawn_sync()
        return {"fact_id": fact_id, "note": "索引は非同期で更新される"}

    async def tool_invalidate(
        self,
        fact_id: str,
        reason: str,
        *,
        idempotency_key: str | None = None,
        expected_revision: int | None = None,
    ) -> dict:
        del idempotency_key, expected_revision
        client = self._require_client()
        if self.sync.maintenance:
            return {"error": "maintenance 中（reindex 実行中）", "retry": True}
        try:
            await self.facts.invalidate(fact_id, reason, client=client)
        except (FactError, FactNotFound) as e:
            return {"error": str(e)}
        except WriteConflict as e:
            return {"error": str(e), "retry": True}
        self._spawn_sync()
        return {"fact_id": fact_id, "note": "索引は非同期で更新される"}

    async def tool_history(self, fact_id: str) -> dict:
        try:
            return self.facts.history(fact_id)
        except FactNotFound:
            return {"error": f"fact が存在しない: {fact_id}"}

    async def tool_status(self) -> dict:
        status = self.sync.status()
        pending = self.promotion_store.by_state(PromotionState.proposed) + \
            self.promotion_store.by_state(PromotionState.approved)
        status["pending_promotions"] = [
            {"promotion_id": p.id, "fact_id": p.fact_id, "state": p.state.value, "pr_url": p.pr_url}
            for p in pending
        ]
        return status

    async def ui_list_facts(
        self,
        *,
        namespace: str | None,
        kind: str | None,
        status: str,
    ) -> list[dict]:
        facts = []
        for post, rel in self.facts.list_posts():
            if not post.get("id"):
                continue
            if namespace and post.get("namespace") != namespace:
                continue
            if kind and post.get("kind") != kind:
                continue
            if status and post.get("status") != status:
                continue
            facts.append(
                {
                    "fact_id": post.get("id"),
                    "statement": post.get("statement"),
                    "namespace": post.get("namespace"),
                    "kind": post.get("kind"),
                    "status": post.get("status"),
                    "path": rel,
                    "created_at": post.get("created_at"),
                }
            )
        return facts

    async def ui_fact_detail(self, fact_id: str) -> dict | None:
        try:
            post, rel = self.facts.get(fact_id)
        except FactNotFound:
            return None
        return {
            "fact_id": fact_id,
            "path": rel,
            "meta": dict(post.metadata),
            "body": post.content,
            "history": self.facts.history(fact_id),
        }

    async def tool_propose_promotion(self, fact_id: str, reason: str | None = None) -> dict:
        self._require_client()
        if self.promotion_backend is None:
            return {"error": "promotion backend が未設定（enable_github_promotion=True の常駐プロセスのみ有効）"}
        try:
            post, rel = self.facts.get(fact_id)
        except FactNotFound:
            return {"error": f"fact が存在しない: {fact_id}"}
        if post.get("status") != "active":
            return {"error": "active な fact のみ昇格できる"}
        ns = post.get("namespace")
        if not str(ns).startswith("plk.domain."):
            return {"error": f"昇格できるのは plk.domain.* のみ（現在: {ns}）"}
        # push 完了がプリコンディション（設計書 §5）。
        # ここで先に await（to_thread）を消化しておくことで、以降の
        # 「重複チェック → upsert」を event loop 上で await 無しの不可分区間にする
        # （同一 fact への並行 propose が重複レコードを作るレースの防止）。
        unpushed = (
            await asyncio.to_thread(self.store.git, "rev-list", "--count", "origin/main..HEAD")
        ).strip()
        if unpushed != "0":
            return {"error": f"未 push の commit が {unpushed} 件ある（push 完了後に再試行）"}
        # 既存の未処理昇格があれば再作成しない（ここから upsert まで await を挟まない）
        for existing in self.promotion_store.by_fact(fact_id):
            if existing.state in (PromotionState.proposed, PromotionState.approved):
                return {"error": "既に昇格リクエストが存在する", "promotion_id": existing.id}

        # domains/<d>/<file> -> shared/<file>（CI の check_promotion が要求する rename 形）
        import posixpath
        new_rel = f"{self.settings.knowledge_subdir}/shared/" + posixpath.basename(rel)
        pr = new_promotion(
            fact_id=fact_id, from_namespace=ns, old_path=rel, new_path=new_rel,
            branch=f"promote/{fact_id}", reason=reason,
        )
        self.promotion_store.upsert(pr)
        try:
            number, url = await self.promotion_backend.create_pr(pr)
        except Exception as e:  # noqa: BLE001
            # ロールバック: proposed のまま pr_number=None のレコードが残ると、
            # ①再 propose が重複チェックで永久拒否 ②poll が pr_number=None で永久スキップ、
            # の復旧不能状態になる。削除して再 propose で自己回復させる
            # （PR が作られていた場合も backend の already-exists 再利用で回収できる）。
            self.promotion_store.delete(pr.id)
            return {"error": f"PR 作成に失敗: {e}"}
        pr = pr.model_copy(update={"pr_number": number, "pr_url": url})
        self.promotion_store.upsert(pr)
        return {"promotion_id": pr.id, "pr_url": url, "state": pr.state.value}

    async def poll_promotions(self) -> dict:
        if self.promotion_backend is None:
            return {"applied": 0, "rejected": 0, "checked": 0}
        applied = rejected = checked = 0
        for pr in self.promotion_store.by_state(PromotionState.proposed) + \
                self.promotion_store.by_state(PromotionState.approved):
            if pr.pr_number is None:
                continue
            checked += 1
            try:
                state = await self.promotion_backend.merged_state(pr.pr_number)
            except Exception:  # noqa: BLE001 - 照会失敗は次回に回す
                continue
            # 冪等性: transition() は許可されない遷移で PromotionError を送出するため、
            # 既に applied/rejected な PromotionRequest を再取得した場合（同じ merge の
            # 二重検知）はここで静かにスキップする。
            current = self.promotion_store.get(pr.id)
            if current.state not in (PromotionState.proposed, PromotionState.approved):
                continue
            if state == "MERGED":
                self.promotion_store.upsert(transition(current, PromotionState.applied))
                await self.sync.sync()  # level-triggered が rename を拾い shared へ再 ingest
                applied += 1
            elif state == "APPROVED":
                # 承認と適用が分離するバックエンド（Slack 等）の中間状態。
                # 承認の記録のみ行い、sync はしない（適用は MERGED 検知時）。
                # GitHub backend は APPROVED を返さないため既存経路への影響はない。
                if current.state is PromotionState.proposed:
                    self.promotion_store.upsert(transition(current, PromotionState.approved))
            elif state == "CLOSED":
                self.promotion_store.upsert(transition(current, PromotionState.rejected))
                rejected += 1
        return {"applied": applied, "rejected": rejected, "checked": checked}


def _build_services(settings: Settings, graph, promotion_backend=None,
                    enable_github_promotion: bool = False):
    if settings.storage_backend == "postgres":
        return _build_postgres_services(settings, graph)
    store = GitStore(settings)
    facts = FactService(store, settings)
    if graph is None:
        graph = GraphIndex(settings)
    state_store = StateStore(settings.state_path)
    sync = SyncEngine(store, facts, graph, state_store, settings)
    usage = UsageLog(settings.usage_log_path)
    promotion_store = PromotionStore(settings.state_path.with_name("promotions.json"))
    if promotion_backend is None and enable_github_promotion:
        from plk_memory.github_promotion import GitHubPromotionBackend
        promotion_backend = GitHubPromotionBackend(store, settings)
    return AppServices(
        settings=settings, store=store, facts=facts, graph=graph,
        sync=sync, state_store=state_store, usage=usage,
        promotion_store=promotion_store, promotion_backend=promotion_backend,
    )


def _build_postgres_services(settings: Settings, graph=None):
    if not settings.database_url:
        raise RuntimeError("PLK_DATABASE_URL is required for postgres storage")
    from plk_memory.postgres.application import PostgresAppServices
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
    )


def create_app(settings: Settings | None = None, graph=None, promotion_backend=None,
                enable_github_promotion: bool = False) -> FastAPI:
    settings = settings or Settings()
    services = _build_services(
        settings, graph, promotion_backend=promotion_backend,
        enable_github_promotion=enable_github_promotion,
    )

    mcp = build_mcp(services)
    mcp_app = mcp.http_app(path="/")

    @asynccontextmanager
    async def app_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if settings.storage_backend == "postgres":
            try:
                await services.start()
            except Exception:  # noqa: BLE001 - DB remains canonical in degraded search mode
                pass
            try:
                yield
            finally:
                await services.close()
            return
        services.store.ensure_repo()
        try:
            await services.graph.start()
        except Exception as e:  # noqa: BLE001 - degraded 記録して起動は続行（brief 動作規則）
            services.sync.degraded = str(e)

        async def _periodic_sync() -> None:
            while True:
                try:
                    await services.sync.sync()
                except Exception:  # noqa: BLE001 - 周期同期の失敗でサーバーを落とさない
                    pass
                await asyncio.sleep(settings.sync_interval_seconds)

        task = asyncio.create_task(_periodic_sync())

        async def _periodic_poll() -> None:
            while True:
                await asyncio.sleep(settings.sync_interval_seconds)
                try:
                    await services.poll_promotions()
                except Exception:  # noqa: BLE001 - 周期ポーリングの失敗でサーバーを落とさない
                    pass

        poll_task = asyncio.create_task(_periodic_poll())
        try:
            yield
        finally:
            task.cancel()
            poll_task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
            for t in list(services._bg_tasks):
                t.cancel()
            if services._bg_tasks:
                await asyncio.gather(*services._bg_tasks, return_exceptions=True)

    app = FastAPI(lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan))
    app.state.services = services

    from starlette.middleware.trustedhost import TrustedHostMiddleware

    if settings.allowed_hosts and settings.allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    # jwt モードでは verifier を app 構築時に 1 個作って middleware に渡す
    # （拒否経路を middleware の 401 JSON に集約する — レビュー指摘対応）。
    verifier = None
    if settings.auth_mode == "jwt":
        from plk_memory.auth import build_jwt_verifier

        verifier = build_jwt_verifier(settings)
    app.add_middleware(BearerAuthMiddleware, settings=settings, verifier=verifier)

    # CSP: 本文 sanitize と併せて XSS を二重に防ぐ（設計書 §5）。UI 応答（/ と /ui 配下）にのみ付与。
    @app.middleware("http")
    async def _csp(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/ui"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; img-src 'self' data:"
            )
        return response

    @app.get("/.well-known/jwks.json")
    async def jwks() -> dict:
        # ローカル JWKS 配信（jwt モードの JWTVerifier(jwks_uri=...) が取得する）。
        # jwt_public_key(PEM) から JWK を組み立てて返す。未設定時は 404。
        # `/.well-known` は `/admin` でも `/mcp` でもないため BearerAuthMiddleware を
        # 素通りする＝認証不要で公開鍵を配れる（意図した挙動）。
        if not settings.jwt_public_key:
            raise HTTPException(status_code=404, detail="JWKS 未設定")
        from authlib.jose import JsonWebKey

        key = JsonWebKey.import_key(
            settings.jwt_public_key, {"kty": "RSA", "use": "sig", "alg": "RS256"}
        )
        return {"keys": [key.as_dict()]}

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    @app.post("/admin/sync")
    async def admin_sync() -> dict:
        if settings.storage_backend == "postgres":
            return await services.admin_sync()
        if services.sync.maintenance:
            raise HTTPException(status_code=503, detail="maintenance 中（reindex 実行中）")
        return await services.sync.sync()

    @app.post("/admin/reindex")
    async def admin_reindex(background_tasks: BackgroundTasks) -> dict:
        if settings.storage_backend == "postgres":
            return await services.admin_reindex()
        # フラグをルート側で先行セット（begin_reindex は await を挟まない atomic）。
        # 連打の 2 件目は背景タスク開始前にここで 409 になり、silent drop を防ぐ。
        if not services.sync.begin_reindex():
            raise HTTPException(status_code=409, detail="reindex は既に実行中")

        async def _guarded_reindex() -> None:
            try:
                await services.sync._do_reindex()
            except Exception:  # noqa: BLE001 - 背景ジョブの失敗でサーバーを落とさない
                pass
            finally:
                services.sync.end_reindex()

        background_tasks.add_task(_guarded_reindex)
        return {"status": "started"}

    # read 専用 Web UI（設計書 §5）: cookie 認証・CSP・本文 sanitize。/mcp mount の前に登録する。
    app.include_router(build_ui_router(services))

    _static_dir = Path(__file__).parent / "static"
    _index_html = (_static_dir / "index.html").read_text(encoding="utf-8")

    @app.get("/")
    async def ui_index() -> HTMLResponse:
        return HTMLResponse(_index_html)

    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    # ルート登録順: REST（UI 含む）→ MCP mount（Mount が全パスを食う問題への対処）
    app.mount("/mcp", mcp_app)

    return app


def create_prod_app() -> FastAPI:
    """本番エントリ（Mac 常駐・launchd 用, Task 9 brief）。

    `enable_github_promotion=True` の経路を使う。store は create_app 内で 1 個だけ
    生成され GitHubPromotionBackend に渡るため flock 単一インスタンスと両立する。
    uvicorn 起動: `uvicorn plk_memory.app:create_prod_app --factory`。
    `PLK_*` は pydantic-settings が WorkingDirectory 直下の `.env` から読む。
    """
    return create_app(settings=Settings(), enable_github_promotion=True)
