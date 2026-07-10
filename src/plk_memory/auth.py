"""Bearer 認証（クライアント別トークン）と呼び出し元 contextvar（設計書 §7）。"""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from plk_memory.settings import Settings
from plk_memory.domain import ActorContext

current_client: ContextVar[str | None] = ContextVar("current_client", default=None)
current_actor: ContextVar[ActorContext | None] = ContextVar("current_actor", default=None)


def actor_from_claims(settings: Settings, claims: dict) -> ActorContext | None:
    """Build a tenant-scoped actor only from already verified JWT claims."""

    subject = claims.get("sub")
    organization = claims.get(settings.jwt_organization_claim)
    if not subject or not organization:
        return None
    try:
        organization_id = UUID(str(organization))
    except ValueError:
        return None
    raw_roles = claims.get(settings.jwt_roles_claim, [])
    if isinstance(raw_roles, str):
        roles = frozenset(part for part in raw_roles.split() if part)
    elif isinstance(raw_roles, list):
        roles = frozenset(str(role) for role in raw_roles)
    else:
        return None
    raw_actor_type = claims.get("actor_type", "agent")
    actor_type = raw_actor_type if raw_actor_type in {"human", "agent", "service"} else "agent"
    return ActorContext(
        organization_id=organization_id,
        actor_id=str(subject),
        actor_type=actor_type,
        roles=roles,
    )


def bearer_actor(settings: Settings, client: str) -> ActorContext | None:
    """Compatibility actor for local bearer clients during the cutover."""

    if not settings.default_organization_id:
        return None
    try:
        organization_id = UUID(settings.default_organization_id)
    except ValueError:
        return None
    return ActorContext(
        organization_id=organization_id,
        actor_id=client,
        actor_type="agent",
        roles=frozenset({"writer"}),
    )


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings, verifier=None):
        super().__init__(app)
        self.settings = settings
        # jwt モードでは JWTVerifier による完全検証（署名・issuer・audience・expiry）を
        # この middleware で行う。app 構築時に settings から作って渡すのが基本だが、
        # 直接構築（テスト等）でも動くよう未指定なら自前で組み立てる。
        if verifier is None and settings.auth_mode == "jwt":
            verifier = build_jwt_verifier(settings)
        self.verifier = verifier

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        token = ""
        authz = request.headers.get("authorization", "")
        if authz.lower().startswith("bearer "):
            token = authz[7:].strip()

        client_token = None
        actor_token = None
        try:
            if path.startswith("/admin"):
                if not self.settings.admin_token or token != self.settings.admin_token:
                    return JSONResponse({"error": "admin token required"}, status_code=401)
            elif path.startswith("/mcp"):
                if self.settings.auth_mode == "jwt":
                # JWTVerifier で完全検証（署名・issuer・audience・expiry）。
                # 拒否は必ずこの JSONResponse 401 で起きる（クライアントが要求する
                # 401 + application/json の契約を構造的に保証する）。
                # FastMCP 内部（mcp_tools の auth=）の再検証は defense in depth として残す。
                    access = (
                        await self.verifier.verify_token(token)
                        if (self.verifier and token)
                        else None
                    )
                    claims = (access.claims or {}) if access is not None else {}
                    sub = claims.get("sub")
                    if not sub:
                        return JSONResponse({"error": "invalid or missing JWT"}, status_code=401)
                    actor = actor_from_claims(self.settings, claims)
                    if self.settings.storage_backend == "postgres" and actor is None:
                        return JSONResponse(
                            {"error": "JWT organization claim required"}, status_code=401
                        )
                    client_token = current_client.set(str(sub))
                    actor_token = current_actor.set(actor)
                else:
                    client = self.settings.tokens.get(token)
                    if client is None:
                        return JSONResponse(
                            {"error": "invalid or missing bearer token"}, status_code=401
                        )
                    actor = bearer_actor(self.settings, client)
                    if self.settings.storage_backend == "postgres" and actor is None:
                        return JSONResponse(
                            {"error": "default organization is required"}, status_code=401
                        )
                    client_token = current_client.set(client)
                    actor_token = current_actor.set(actor)
            return await call_next(request)
        finally:
            if actor_token is not None:
                current_actor.reset(actor_token)
            if client_token is not None:
                current_client.reset(client_token)


def build_jwt_verifier(settings: Settings):
    """設計書 §7 の逆輸入時 AuthProvider = FastMCP JWTVerifier。
    jwks_uri があれば JWKS 配信から公開鍵を取得（本番/Auth0 相当）。
    空なら jwt_public_key(PEM) を直接使う（テスト・オフライン検証）。"""
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    if settings.jwks_uri:
        return JWTVerifier(
            jwks_uri=settings.jwks_uri, issuer=settings.jwt_issuer,
            audience=settings.jwt_audience, algorithm="RS256",
        )
    return JWTVerifier(
        public_key=settings.jwt_public_key, issuer=settings.jwt_issuer,
        audience=settings.jwt_audience, algorithm="RS256",
    )


def client_from_jwt(token: str) -> str | None:
    """JWT の sub クレームを取り出す（unsigned decode。デバッグ・表示用ユーティリティ）。

    認証判断には使わないこと — middleware の認証経路は JWTVerifier による完全検証
    （署名・issuer・audience・expiry）を行い、検証済み AccessToken.claims から sub を
    導出する（レビュー指摘: 拒否経路を必ず middleware の 401 JSON に集約するため）。"""
    import jwt as pyjwt

    try:
        claims = pyjwt.decode(token, options={"verify_signature": False})
    except pyjwt.PyJWTError:
        return None
    sub = claims.get("sub")
    return str(sub) if sub else None
