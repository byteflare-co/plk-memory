"""FastAPI + FastMCP の ASGI 結線のみを担う（設計書 §8, Task 9 brief）。

ルート登録順は REST → `app.mount("/mcp", mcp_app)`（Mount が全パスを食う問題への対処）。
lifespan は `combine_lifespans` で FastAPI 側の初期化（ensure_repo → graph.start →
初回 sync → 周期 sync）と FastMCP 側の lifespan を束ねる。
バックエンド合成（storage_backend の切り替え）は `composition.py`、Git backend の
実体関数（AppServices）は `git_services.py` に分離されている。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

from plk_memory.auth import BearerAuthMiddleware
from plk_memory.composition import build_services as _build_services
from plk_memory.git_services import AppServices as AppServices
from plk_memory.mcp_tools import build_mcp
from plk_memory.settings import Settings
from plk_memory.webui import build_ui_router

if TYPE_CHECKING:
    from plk_memory.postgres.application import PostgresAppServices

try:
    from fastmcp.utilities.lifespan import combine_lifespans as _combine_lifespans
except ImportError:  # pragma: no cover - フォールバック（API 変更時のみ到達）
    from contextlib import AsyncExitStack

    def _combine_lifespans(*lifespans: Any) -> Any:
        @asynccontextmanager
        async def combined(app):
            async with AsyncExitStack() as stack:
                for ls in lifespans:
                    await stack.enter_async_context(ls(app))
                yield

        return combined


def create_app(settings: Settings | None = None, graph=None, promotion_backend=None,
                enable_github_promotion: bool = False) -> FastAPI:
    settings = settings or Settings()
    services = _build_services(
        settings, graph, promotion_backend=promotion_backend,
        enable_github_promotion=enable_github_promotion,
    )
    git_services = cast(AppServices, services)
    postgres_services = cast("PostgresAppServices", services)

    mcp = build_mcp(services)
    mcp_app = mcp.http_app(path="/")

    @asynccontextmanager
    async def app_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if settings.storage_backend == "postgres":
            await postgres_services.check_database()
            try:
                await postgres_services.start()
            except Exception:  # noqa: BLE001 - DB remains canonical in degraded search mode
                pass
            try:
                yield
            finally:
                await postgres_services.close()
            return
        git_services.store.ensure_repo()
        try:
            await git_services.graph.start()
        except Exception as e:  # noqa: BLE001 - degraded 記録して起動は続行（brief 動作規則）
            git_services.sync.degraded = str(e)

        async def _periodic_sync() -> None:
            while True:
                try:
                    await git_services.sync.sync()
                except Exception:  # noqa: BLE001 - 周期同期の失敗でサーバーを落とさない
                    pass
                await asyncio.sleep(settings.sync_interval_seconds)

        task = asyncio.create_task(_periodic_sync())

        async def _periodic_poll() -> None:
            while True:
                await asyncio.sleep(settings.sync_interval_seconds)
                try:
                    await git_services.poll_promotions()
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
            for t in list(git_services._bg_tasks):
                t.cancel()
            if git_services._bg_tasks:
                await asyncio.gather(*git_services._bg_tasks, return_exceptions=True)

    app = FastAPI(lifespan=_combine_lifespans(app_lifespan, mcp_app.lifespan))
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
        if settings.storage_backend == "postgres":
            try:
                await postgres_services.check_database()
            except Exception as error:  # noqa: BLE001 - readiness must fail closed
                raise HTTPException(
                    status_code=503, detail=f"database unavailable: {error}"
                ) from error
        return {"ok": True}

    @app.post("/admin/sync")
    async def admin_sync() -> dict:
        if settings.storage_backend == "postgres":
            return await postgres_services.admin_sync()
        if git_services.sync.maintenance:
            raise HTTPException(status_code=503, detail="maintenance 中（reindex 実行中）")
        return await git_services.sync.sync()

    @app.post("/admin/reindex")
    async def admin_reindex(background_tasks: BackgroundTasks) -> dict:
        if settings.storage_backend == "postgres":
            return await postgres_services.admin_reindex()
        # フラグをルート側で先行セット（begin_reindex は await を挟まない atomic）。
        # 連打の 2 件目は背景タスク開始前にここで 409 になり、silent drop を防ぐ。
        if not git_services.sync.begin_reindex():
            raise HTTPException(status_code=409, detail="reindex は既に実行中")

        async def _guarded_reindex() -> None:
            try:
                await git_services.sync._do_reindex()
            except Exception:  # noqa: BLE001 - 背景ジョブの失敗でサーバーを落とさない
                pass
            finally:
                git_services.sync.end_reindex()

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
