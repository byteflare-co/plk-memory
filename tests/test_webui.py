import httpx
import pytest

from plk_memory.app import create_app
from plk_memory.webui import sanitize_markdown
from tests.conftest import make_settings
from tests.fakes import FakeGraphIndex
from tests.gitsync_helpers import push


def test_sanitize_strips_script_keeps_markup():
    html = sanitize_markdown("# 見出し\n\n<script>alert(1)</script>\n\n**強調**")
    assert "<script" not in html.lower()
    assert "<strong>" in html or "<em>" in html or "<h1>" in html


@pytest.fixture
async def uiclient(remote, tmp_path, write_valid_fact):
    origin, seed = remote
    write_valid_fact(seed, "knowledge/domains/tax/x.md")
    push(seed)
    settings = make_settings(tmp_path, origin, tokens={"tok-cc": "cc"},
                             admin_token="adm", ui_password="s3cret")
    app = create_app(settings=settings, graph=FakeGraphIndex())
    app.state.services.store.ensure_repo()
    app.state.services.store.fetch_and_ff()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://plk") as c:
        yield c


@pytest.fixture
async def open_uiclient(remote, tmp_path, write_valid_fact):
    origin, seed = remote
    write_valid_fact(seed, "knowledge/domains/tax/x.md")
    push(seed)
    settings = make_settings(tmp_path, origin, tokens={"tok-cc": "cc"},
                             admin_token="adm", ui_password="")
    app = create_app(settings=settings, graph=FakeGraphIndex())
    app.state.services.store.ensure_repo()
    app.state.services.store.fetch_and_ff()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://plk") as c:
        yield c


async def test_ui_api_requires_cookie(uiclient):
    r = await uiclient.get("/ui/api/facts")
    assert r.status_code == 401


async def test_ui_without_password_allows_direct_read(open_uiclient):
    r = await open_uiclient.get("/ui/api/facts")
    assert r.status_code == 200
    assert r.json()["facts"]


async def test_ui_without_password_login_is_noop(open_uiclient):
    r = await open_uiclient.post("/ui/login", json={})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert "set-cookie" not in r.headers


async def test_login_form_is_hidden_until_auth_is_required(uiclient):
    r = await uiclient.get("/")
    assert r.status_code == 200
    assert "display: none; max-width: 340px" in r.text


async def test_ui_login_sets_httponly_cookie_and_lists(uiclient):
    r = await uiclient.post("/ui/login", json={"password": "s3cret"})
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie
    r2 = await uiclient.get("/ui/api/facts")
    assert r2.status_code == 200
    assert any(f["namespace"] == "plk.domain.tax" for f in r2.json()["facts"])


async def test_ui_api_filters_by_kind(uiclient):
    await uiclient.post("/ui/login", json={"password": "s3cret"})

    knowhow = await uiclient.get("/ui/api/facts", params={"kind": "knowhow"})
    assert knowhow.status_code == 200
    assert knowhow.json()["facts"]
    assert all(f["kind"] == "knowhow" for f in knowhow.json()["facts"])

    logic = await uiclient.get("/ui/api/facts", params={"kind": "logic"})
    assert logic.status_code == 200
    assert logic.json()["facts"] == []


async def test_ui_page_has_kind_filter(uiclient):
    r = await uiclient.get("/")
    assert r.status_code == 200
    assert 'id="kindToggle"' in r.text
    assert 'data-v="philosophy"' in r.text
    assert 'data-v="logic"' in r.text
    assert 'data-v="knowhow"' in r.text


async def test_ui_login_wrong_password(uiclient):
    r = await uiclient.post("/ui/login", json={"password": "nope"})
    assert r.status_code == 401


async def test_csp_header_present(uiclient):
    r = await uiclient.get("/")
    assert "content-security-policy" in {k.lower() for k in r.headers}


async def test_ui_detail_has_sanitized_body_and_history(uiclient):
    await uiclient.post("/ui/login", json={"password": "s3cret"})
    facts = (await uiclient.get("/ui/api/facts")).json()["facts"]
    fid = facts[0]["fact_id"]
    r = await uiclient.get(f"/ui/api/facts/{fid}")
    assert r.status_code == 200
    body = r.json()
    assert "body_html" in body and "history" in body
    assert "<script" not in body["body_html"].lower()
