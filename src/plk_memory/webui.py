"""read 専用 Web UI（設計書 §5）。

ブラウザは REST のみに接続する（MCP・Bearer を持ち込まない）。閲覧認証は
HttpOnly cookie。本文は非信頼入力として markdown を sanitize（nh3）する。
"""

from __future__ import annotations

import ipaddress
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import markdown as md
import nh3
from fastapi import APIRouter, HTTPException, Request, Response, status

if TYPE_CHECKING:
    from plk_memory.facade import ServiceFacade

_ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "p", "ul", "ol", "li", "strong", "em", "code",
    "pre", "blockquote", "a", "br", "hr", "table", "thead", "tbody", "tr", "th", "td",
}


def sanitize_markdown(text: str) -> str:
    """markdown をレンダリングし、nh3 の allowlist で sanitize する（本文は非信頼入力）。"""
    html = md.markdown(text or "", extensions=["fenced_code", "tables"])
    return nh3.clean(html, tags=_ALLOWED_TAGS, attributes={"a": {"href", "title"}})


@dataclass(frozen=True)
class _UISession:
    csrf: str
    expires_at: float


class _UISessions:
    """Short-lived in-process sessions for the localhost UI."""

    def __init__(self, ttl_seconds: int = 86400) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, _UISession] = {}

    def create(self) -> tuple[str, _UISession]:
        self._prune()
        token = secrets.token_urlsafe(32)
        session = _UISession(
            csrf=secrets.token_urlsafe(32),
            expires_at=time.monotonic() + self.ttl_seconds,
        )
        self._items[token] = session
        return token, session

    def get(self, token: str | None) -> _UISession | None:
        self._prune()
        return self._items.get(token) if token else None

    def _prune(self) -> None:
        now = time.monotonic()
        self._items = {
            token: session
            for token, session in self._items.items()
            if session.expires_at > now
        }


def build_ui_router(services: "ServiceFacade") -> APIRouter:
    router = APIRouter()
    settings = services.settings
    sessions = _UISessions()

    def _set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            settings.ui_cookie_name,
            token,
            httponly=True,
            samesite="strict",
            secure=False,
            max_age=86400,
        )
        response.headers["set-cookie"] = response.headers["set-cookie"].replace(
            "SameSite=strict", "SameSite=Strict"
        )

    def _require_loopback(request: Request) -> None:
        client_host = request.client.host if request.client else ""
        try:
            is_loopback = ipaddress.ip_address(client_host).is_loopback
        except ValueError:
            is_loopback = client_host == "localhost"
        host_header = request.headers.get("host", "")
        if host_header.startswith("["):
            raw_host = host_header.split("]", 1)[0].lstrip("[")
        else:
            raw_host = host_header.split(":", 1)[0]
        if not is_loopback or raw_host not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(status_code=403, detail="UI writes require loopback origin")

    def _require_cookie(request: Request) -> _UISession | None:
        if not settings.ui_password:
            return
        session = sessions.get(request.cookies.get(settings.ui_cookie_name))
        if session is None:
            raise HTTPException(status_code=401, detail="login required")
        return session

    def _require_write(request: Request) -> None:
        if not settings.ui_writes_enabled:
            raise HTTPException(status_code=403, detail="UI writes are disabled")
        _require_loopback(request)
        session = _require_cookie(request)
        if session is None:
            session = sessions.get(request.cookies.get(settings.ui_cookie_name))
            if session is None:
                raise HTTPException(status_code=401, detail="UI session required")
        if settings.storage_backend != "git":
            raise HTTPException(status_code=501, detail="UI writes currently require Git backend")
        content_type = request.headers.get("content-type", "").split(";", 1)[0]
        if content_type != "application/json":
            raise HTTPException(status_code=415, detail="application/json required")
        provided = request.headers.get("x-plk-csrf", "")
        if not provided or not secrets.compare_digest(provided, session.csrf):
            raise HTTPException(status_code=403, detail="invalid CSRF token")

    @router.post("/ui/login")
    async def ui_login(request: Request, payload: dict, response: Response) -> dict:
        if not settings.ui_password:
            if not settings.ui_writes_enabled:
                return {"ok": True}
            _require_loopback(request)
            token, session = sessions.create()
            _set_session_cookie(response, token)
            return {"ok": True, "csrf": session.csrf}
        password = payload.get("password")
        if (
            not isinstance(password, str)
            or not secrets.compare_digest(password, settings.ui_password)
        ):
            raise HTTPException(status_code=401, detail="invalid password")
        token, session = sessions.create()
        _set_session_cookie(response, token)
        return {"ok": True, "csrf": session.csrf}

    @router.get("/ui/session")
    async def ui_session(request: Request, response: Response) -> dict:
        session = _require_cookie(request)
        if session is None and settings.ui_writes_enabled:
            _require_loopback(request)
            token, session = sessions.create()
            _set_session_cookie(response, token)
        return {"ok": True, "csrf": session.csrf if session else None}

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

    @router.post(
        "/ui/api/facts/{fact_id}/feedback",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def ui_submit_feedback(request: Request, fact_id: str, payload: dict) -> dict:
        _require_write(request)
        result = await services.ui_submit_feedback(fact_id, str(payload.get("feedback", "")))
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @router.get("/ui/api/facts/{fact_id}/feedback")
    async def ui_feedback_requests(request: Request, fact_id: str) -> dict:
        _require_cookie(request)
        if settings.storage_backend != "git":
            return {"requests": []}
        return {"requests": await services.ui_feedback_requests(fact_id)}

    @router.post("/ui/api/feedback/{request_id}/apply")
    async def ui_apply_feedback(request: Request, request_id: str) -> dict:
        _require_write(request)
        result = await services.ui_apply_feedback(request_id)
        if result.get("error"):
            code = 409 if result.get("stale") or result.get("retry") else 400
            raise HTTPException(status_code=code, detail=result["error"])
        return result

    @router.post("/ui/api/feedback/{request_id}/reject")
    async def ui_reject_feedback(request: Request, request_id: str) -> dict:
        _require_write(request)
        result = await services.ui_reject_feedback(request_id)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @router.post("/ui/api/facts/{fact_id}/invalidate")
    async def ui_invalidate_fact(request: Request, fact_id: str, payload: dict) -> dict:
        _require_write(request)
        expected_hash = payload.get("expected_hash")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise HTTPException(status_code=400, detail="expected_hash is required")
        result = await services.ui_invalidate_fact(
            fact_id,
            str(payload.get("reason", "")),
            expected_hash,
        )
        if result.get("error"):
            code = 409 if result.get("retry") else 400
            raise HTTPException(status_code=code, detail=result["error"])
        return result

    return router
