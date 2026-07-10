"""Bearer 認証（クライアント別トークン）と呼び出し元 contextvar（設計書 §7）。"""

from __future__ import annotations

from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from plk_memory.settings import Settings

current_client: ContextVar[str | None] = ContextVar("current_client", default=None)


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

        if path.startswith("/admin"):
            if not self.settings.admin_token or token != self.settings.admin_token:
                return JSONResponse({"error": "admin token required"}, status_code=401)
        elif path.startswith("/mcp"):
            if self.settings.auth_mode == "jwt":
                # JWTVerifier で完全検証（署名・issuer・audience・expiry）。
                # 拒否は必ずこの JSONResponse 401 で起きる（クライアントが要求する
                # 401 + application/json の契約を構造的に保証する）。
                # FastMCP 内部（mcp_tools の auth=）の再検証は defense in depth として残す。
                access = await self.verifier.verify_token(token) if (self.verifier and token) else None
                sub = (access.claims or {}).get("sub") if access is not None else None
                if not sub:
                    return JSONResponse({"error": "invalid or missing JWT"}, status_code=401)
                current_client.set(str(sub))
            else:
                client = self.settings.tokens.get(token)
                if client is None:
                    return JSONResponse({"error": "invalid or missing bearer token"}, status_code=401)
                current_client.set(client)
        return await call_next(request)


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
