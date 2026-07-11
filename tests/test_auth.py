import httpx
import pytest
from fastapi import FastAPI

from plk_memory.auth import BearerAuthMiddleware, current_actor, current_client
from plk_memory.settings import Settings


ORG = "00000000-0000-0000-0000-000000000001"


def make_app():
    s = Settings(
        tokens={"tok-cc": "claude-code"},
        admin_token="tok-admin",
        default_organization_id=ORG,
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, settings=s)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/mcp/echo")
    async def echo():
        actor = current_actor.get()
        return {
            "client": current_client.get(),
            "organization_id": str(actor.organization_id) if actor else None,
        }

    @app.get("/admin/ping")
    async def admin_ping():
        return {"ok": True}

    return app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_healthz_open(client):
    r = await client.get("/healthz")
    assert r.status_code == 200


async def test_mcp_requires_token(client):
    r = await client.get("/mcp/echo")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")


async def test_mcp_valid_token_sets_client(client):
    r = await client.get("/mcp/echo", headers={"Authorization": "Bearer tok-cc"})
    assert r.status_code == 200
    assert r.json() == {"client": "claude-code", "organization_id": ORG}
    assert current_client.get() is None
    assert current_actor.get() is None


async def test_admin_needs_admin_token(client):
    r = await client.get("/admin/ping", headers={"Authorization": "Bearer tok-cc"})
    assert r.status_code == 401
    r = await client.get("/admin/ping", headers={"Authorization": "Bearer tok-admin"})
    assert r.status_code == 200
