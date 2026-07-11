"""read 専用 Web UI（設計書 §5）。

ブラウザは REST のみに接続する（MCP・Bearer を持ち込まない）。閲覧認証は
HttpOnly cookie。本文は非信頼入力として markdown を sanitize（nh3）する。
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import markdown as md
import nh3
from fastapi import APIRouter, HTTPException, Request, Response

if TYPE_CHECKING:
    from plk_memory.app import AppServices
    from plk_memory.postgres.application import PostgresAppServices

    ServiceFacade = AppServices | PostgresAppServices

_ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "p", "ul", "ol", "li", "strong", "em", "code",
    "pre", "blockquote", "a", "br", "hr", "table", "thead", "tbody", "tr", "th", "td",
}


def sanitize_markdown(text: str) -> str:
    """markdown をレンダリングし、nh3 の allowlist で sanitize する（本文は非信頼入力）。"""
    html = md.markdown(text or "", extensions=["fenced_code", "tables"])
    return nh3.clean(html, tags=_ALLOWED_TAGS, attributes={"a": {"href", "title"}})


def _cookie_value(password: str) -> str:
    return hashlib.sha256(("plk-ui:" + password).encode("utf-8")).hexdigest()


def build_ui_router(services: "ServiceFacade") -> APIRouter:
    router = APIRouter()
    settings = services.settings
    expected = _cookie_value(settings.ui_password) if settings.ui_password else None

    def _require_cookie(request: Request) -> None:
        if expected is None:
            raise HTTPException(status_code=401, detail="UI is disabled")
        if request.cookies.get(settings.ui_cookie_name) != expected:
            raise HTTPException(status_code=401, detail="login required")

    @router.post("/ui/login")
    async def ui_login(payload: dict, response: Response) -> dict:
        if not settings.ui_password or payload.get("password") != settings.ui_password:
            raise HTTPException(status_code=401, detail="invalid password")
        response.set_cookie(
            settings.ui_cookie_name, _cookie_value(settings.ui_password),
            httponly=True, samesite="strict", secure=False, max_age=86400,
        )
        # starlette は Set-Cookie の SameSite 値を小文字で出す（"strict"）。ブラウザは
        # 大文字小文字を区別しないが、テスト・仕様上の可読性のため正規の表記に揃える。
        response.headers["set-cookie"] = response.headers["set-cookie"].replace(
            "SameSite=strict", "SameSite=Strict"
        )
        return {"ok": True}

    @router.get("/ui/api/facts")
    async def ui_facts(request: Request, namespace: str | None = None,
                       kind: str | None = None, status: str = "active",
                       q: str | None = None) -> dict:
        _require_cookie(request)
        if q:
            res = await services.tool_search(
                query=q, namespaces=[namespace] if namespace else None,
                kind=kind, status=status, limit=50, reason="webui",
            )
            return {"facts": res.get("hits", []), "degraded": res.get("degraded", False)}
        return {
            "facts": await services.ui_list_facts(
                namespace=namespace, kind=kind, status=status
            )
        }

    @router.get("/ui/api/facts/{fact_id}")
    async def ui_fact_detail(request: Request, fact_id: str) -> dict:
        _require_cookie(request)
        detail = await services.ui_fact_detail(fact_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="not found")
        return {
            "fact_id": fact_id,
            "path": detail["path"],
            "meta": detail["meta"],
            "body_html": sanitize_markdown(detail["body"]),
            "history": detail["history"],
        }

    return router
