import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import APIRouter
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from plk_memory.app import create_app
from plk_memory.auth import build_jwt_verifier, client_from_jwt
from plk_memory.settings import Settings
from tests.conftest import make_settings as make_app_settings
from tests.fakes import FakeGraphIndex

ISSUER = "https://plk-memory.local/"
AUDIENCE = "plk-memory"


@pytest.fixture
def keypair():
    return RSAKeyPair.generate()


def make_settings(keypair) -> Settings:
    return Settings(
        auth_mode="jwt", jwt_issuer=ISSUER, jwt_audience=AUDIENCE,
        jwt_public_key=keypair.public_key, _env_file=None,
    )


async def test_valid_token_is_accepted(keypair):
    verifier = build_jwt_verifier(make_settings(keypair))
    token = keypair.create_token(subject="claude-code", issuer=ISSUER, audience=AUDIENCE)
    access = await verifier.verify_token(token)
    assert access is not None


async def test_wrong_issuer_is_rejected(keypair):
    verifier = build_jwt_verifier(make_settings(keypair))
    token = keypair.create_token(subject="claude-code", issuer="https://evil.example/", audience=AUDIENCE)
    assert await verifier.verify_token(token) is None


async def test_wrong_audience_is_rejected(keypair):
    verifier = build_jwt_verifier(make_settings(keypair))
    token = keypair.create_token(subject="claude-code", issuer=ISSUER, audience="other-service")
    assert await verifier.verify_token(token) is None


async def test_expired_token_is_rejected(keypair):
    verifier = build_jwt_verifier(make_settings(keypair))
    token = keypair.create_token(
        subject="claude-code", issuer=ISSUER, audience=AUDIENCE, expires_in_seconds=-10,
    )
    assert await verifier.verify_token(token) is None


def test_client_from_jwt_extracts_sub(keypair):
    token = keypair.create_token(subject="codex", issuer=ISSUER, audience=AUDIENCE)
    assert client_from_jwt(token) == "codex"


# --- ASGI end-to-end（jwt モードの create_app。拒否経路は必ず BearerAuthMiddleware の
#     401 JSON で起きることを検証する — レビュー指摘: 署名不正・issuer 不正・期限切れが
#     FastMCP 内部レイヤに漏れて非 JSON 応答になっていないかの回帰網） ---

VALID_ARGS = dict(
    namespace="plk.domain.tax", kind="knowhow",
    statement="法人税の中間申告は前期税額20万円超で必要になる制度である",
    why="国税庁タックスアンサーの中間申告の要件に明記されているため",
    how_to_apply="設立2期目以降、前期法人税額を確認して要否を判定する",
    source="https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5000.htm",
)


@pytest.fixture
async def jwt_ctx(remote, tmp_path, keypair):
    origin, _seed = remote
    settings = make_app_settings(
        tmp_path, origin, tokens={},
        auth_mode="jwt", jwt_issuer=ISSUER, jwt_audience=AUDIENCE,
        jwt_public_key=keypair.public_key,
    )
    graph = FakeGraphIndex()
    app = create_app(settings=settings, graph=graph)

    # written_by 検証用のテスト専用ルート。/mcp mount がパスを食うため router 先頭に挿入する
    # （middleware は router 全体を包むので認証経路は本番と同一）。
    router = APIRouter()

    @router.post("/mcp/_test_add")
    async def _test_add() -> dict:
        return await app.state.services.tool_add(**VALID_ARGS)

    app.router.routes.insert(0, router.routes[0])

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c, app


async def test_e2e_valid_jwt_reaches_mcp_layer(jwt_ctx, keypair):
    c, _app = jwt_ctx
    token = keypair.create_token(subject="claude-code", issuer=ISSUER, audience=AUDIENCE)
    # 認証を通過して MCP プロトコル応答（406: streaming ヘッダ要求）に到達する
    # （test_app.py の bearer 版疎通テストと同じ到達点）。
    r = await c.post("/mcp/", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 406
    assert r.json()["jsonrpc"] == "2.0"


async def test_e2e_wrong_signature_rejected_with_json_401(jwt_ctx):
    c, _app = jwt_ctx
    other = RSAKeyPair.generate()  # サーバーが知らない鍵で署名
    token = other.create_token(subject="claude-code", issuer=ISSUER, audience=AUDIENCE)
    r = await c.post("/mcp/", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    assert "error" in r.json()


async def test_e2e_expired_jwt_rejected_with_json_401(jwt_ctx, keypair):
    c, _app = jwt_ctx
    token = keypair.create_token(
        subject="claude-code", issuer=ISSUER, audience=AUDIENCE, expires_in_seconds=-10,
    )
    r = await c.post("/mcp/", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    assert "error" in r.json()


async def test_e2e_wrong_issuer_rejected_with_json_401(jwt_ctx, keypair):
    c, _app = jwt_ctx
    token = keypair.create_token(
        subject="claude-code", issuer="https://evil.example/", audience=AUDIENCE,
    )
    r = await c.post("/mcp/", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    assert "error" in r.json()


async def test_e2e_written_by_comes_from_jwt_sub(jwt_ctx, keypair):
    c, app = jwt_ctx
    token = keypair.create_token(subject="codex", issuer=ISSUER, audience=AUDIENCE)
    r = await c.post("/mcp/_test_add", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    fact_id = r.json()["fact_id"]
    post, _path = app.state.services.facts.get(fact_id)
    assert post.metadata["written_by"] == "codex"
