import httpx
import pytest
from asgi_lifespan import LifespanManager

from plk_memory.app import create_app
from tests.conftest import make_settings
from tests.fakes import FakeGraphIndex

AUTH_CC = {"Authorization": "Bearer tok-cc"}
AUTH_ADMIN = {"Authorization": "Bearer tok-admin"}

lifespan_ctx = LifespanManager

VALID_ARGS = dict(
    namespace="plk.domain.tax", kind="knowhow",
    statement="法人税の中間申告は前期税額20万円超で必要になる制度である",
    why="国税庁タックスアンサーの中間申告の要件に明記されているため",
    how_to_apply="設立2期目以降、前期法人税額を確認して要否を判定する",
    source="https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5000.htm",
)


@pytest.fixture
async def ctx(remote, tmp_path):
    origin, seed = remote
    settings = make_settings(tmp_path, origin,
                              tokens={"tok-cc": "claude-code"}, admin_token="tok-admin")
    graph = FakeGraphIndex()
    app = create_app(settings=settings, graph=graph)
    async with lifespan_ctx(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c, app, graph


async def test_healthz_no_auth(ctx):
    c, *_ = ctx
    r = await c.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True


async def test_mcp_endpoint_requires_auth(ctx):
    c, *_ = ctx
    r = await c.post("/mcp/", json={})
    assert r.status_code == 401


async def test_mcp_endpoint_reachable_with_auth(ctx):
    # フル MCP セッションハンドシェイク（initialize 等）までは行わず、mount 配線と
    # 認証ミドルウェアを通過して実際の MCP プロトコル応答（406: streaming ヘッダ要求）
    # に到達することだけを確認する（brief: 疎通確認テストの現実的な到達点）。
    c, *_ = ctx
    r = await c.post("/mcp/", json={}, headers=AUTH_CC)
    assert r.status_code == 406
    assert r.json()["jsonrpc"] == "2.0"


async def test_add_then_sync_then_search_tools(ctx):
    c, app, graph = ctx
    svcs = app.state.services
    from plk_memory.auth import current_client
    current_client.set("claude-code")
    result = await svcs.tool_add(**VALID_ARGS)
    assert "fact_id" in result
    await svcs.sync.sync()
    hits = await svcs.tool_search(query="中間申告 前期税額", reason="test")
    assert hits["degraded"] is False
    assert any(h["fact_id"] == result["fact_id"] for h in hits["hits"])


async def test_search_degraded_when_graph_down(ctx):
    c, app, graph = ctx
    graph.ready = False
    svcs = app.state.services
    out = await svcs.tool_search(query="なんでも")
    assert out["degraded"] is True and out["hits"] == []


async def test_admin_reindex_blocks_writes(ctx):
    c, app, graph = ctx
    svcs = app.state.services
    svcs.sync.maintenance = True
    from plk_memory.auth import current_client
    current_client.set("claude-code")
    out = await svcs.tool_add(**VALID_ARGS)
    assert out.get("retry") is True and "error" in out
    svcs.sync.maintenance = False


async def test_admin_sync_endpoint(ctx):
    c, *_ = ctx
    r = await c.post("/admin/sync", headers=AUTH_ADMIN)
    assert r.status_code == 200 and "head" in r.json()


async def test_admin_reindex_double_start_returns_409(ctx):
    c, app, _ = ctx
    app.state.services.sync.maintenance = True
    r = await c.post("/admin/reindex", headers=AUTH_ADMIN)
    assert r.status_code == 409
    app.state.services.sync.maintenance = False


async def test_search_recall_survives_post_filter(ctx):
    c, app, graph = ctx
    # graph に kind 違いのダミーを多数 + 目的の 1 件を最後に積む
    svcs = app.state.services
    # FakeGraphIndex は docs[fact_id] に text/group_id を持つ。search は query トークン一致で返す。
    for i in range(30):
        graph.docs[f"noise{i}"] = {"text": "中間申告 ノイズ", "group_id": "plk-main"}
    # 目的ファクトを実 add
    from plk_memory.auth import current_client
    current_client.set("claude-code")
    r = await svcs.tool_add(**VALID_ARGS)
    await svcs.sync.sync()
    # ノイズは facts.get で FactNotFound になり弾かれるが、候補プールが広いので目的が残る
    hits = await svcs.tool_search(query="中間申告", limit=5)
    assert any(h["fact_id"] == r["fact_id"] for h in hits["hits"])


async def test_status_tool_reports_freshness(ctx):
    c, app, _ = ctx
    out = await app.state.services.tool_status()
    assert {"head", "last_ingested_commit", "indexed_facts", "dead_letters", "unpushed_commits"} <= out.keys()


async def test_tool_add_without_auth_context_errors(ctx):
    c, app, _ = ctx
    from plk_memory.auth import current_client
    current_client.set(None)
    with pytest.raises(PermissionError):
        await app.state.services.tool_add(**VALID_ARGS)


async def test_tool_add_write_conflict_returns_retryable_error(ctx, monkeypatch):
    c, app, _ = ctx
    svcs = app.state.services
    from plk_memory.auth import current_client
    from plk_memory.gitstore import WriteConflict

    current_client.set("claude-code")

    async def _raise_conflict(*args, **kwargs):
        raise WriteConflict("push リトライ上限超過")

    monkeypatch.setattr(svcs.facts, "add", _raise_conflict)
    out = await svcs.tool_add(**VALID_ARGS)
    assert out == {"error": "push リトライ上限超過", "retry": True}


async def test_disallowed_host_rejected_when_allowlist_set(remote, tmp_path):
    origin, seed = remote
    settings = make_settings(tmp_path, origin, tokens={"tok-cc": "claude-code"},
                             admin_token="tok-admin", allowed_hosts=["plk.example.com"])
    app = create_app(settings=settings, graph=FakeGraphIndex())
    import httpx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://evil.example") as c:
        r = await c.get("/healthz", headers={"host": "evil.example"})
        assert r.status_code == 400  # TrustedHostMiddleware
        r2 = await c.get("/healthz", headers={"host": "plk.example.com"})
        assert r2.status_code == 200
