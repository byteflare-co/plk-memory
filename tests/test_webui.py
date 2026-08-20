import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from plk_memory.app import create_app
from plk_memory.feedback import FeedbackProposal
from plk_memory.webui import sanitize_markdown
from plk_memory.workflow_evaluation import (
    EvaluationRevisions,
    StageRatings,
    WorkflowReviewSubmission,
    append_review,
    load_review_suite,
)
from tests.conftest import make_settings
from tests.fakes import FakeGraphIndex
from tests.gitsync_helpers import push


class StaticFeedbackRunner:
    async def propose(self, *, original: dict, feedback: str) -> FeedbackProposal:
        return FeedbackProposal(
            statement=str(original["statement"]) + "（改善）",
            why=str(original["why"]),
            how_to_apply=str(original["how_to_apply"]),
            tags=list(original["tags"]),
            body=str(original["body"]),
            rationale=feedback,
        )


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
                             admin_token="adm", ui_password="s3cret",
                             ui_writes_enabled=True)
    app = create_app(settings=settings, graph=FakeGraphIndex())
    app.state.services.store.ensure_repo()
    app.state.services.store.fetch_and_ff()
    app.state.services.feedback.runner = StaticFeedbackRunner()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1"
    ) as c:
        yield c


@pytest.fixture
async def open_uiclient(remote, tmp_path, write_valid_fact):
    origin, seed = remote
    write_valid_fact(seed, "knowledge/domains/tax/x.md")
    push(seed)
    settings = make_settings(tmp_path, origin, tokens={"tok-cc": "cc"},
                             admin_token="adm", ui_password="",
                             ui_writes_enabled=False)
    app = create_app(settings=settings, graph=FakeGraphIndex())
    app.state.services.store.ensure_repo()
    app.state.services.store.fetch_and_ff()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://plk") as c:
        yield c


async def test_ui_api_requires_cookie(uiclient):
    r = await uiclient.get("/ui/api/facts")
    assert r.status_code == 401

    metrics = await uiclient.get("/ui/api/metrics")
    assert metrics.status_code == 401


async def test_ui_without_password_allows_direct_read(open_uiclient):
    r = await open_uiclient.get("/ui/api/facts")
    assert r.status_code == 200
    assert r.json()["facts"]


async def test_metrics_missing_sources_returns_empty_structure(open_uiclient):
    response = await open_uiclient.get("/ui/api/metrics")
    assert response.status_code == 200
    body = response.json()
    assert len(body["search"]["weekly"]) == 12
    assert body["search"]["total"] == 0
    assert body["zero_hit"] == [] and body["eval"] == {}
    assert body["corpus"]["available"] is True
    assert body["decision_value"]["status"] == "insufficient_data"
    assert len(body["decision_value"]["weekly"]) == 4


def _workflow_case_path() -> Path:
    return Path(__file__).parents[1] / "scripts" / "eval" / "workflow_cases.yaml"


def _workflow_review() -> WorkflowReviewSubmission:
    return WorkflowReviewSubmission(
        review_id="ui-review-1",
        case_id="browser-byteflare-profile-selection",
        variant_id="unique-match",
        reviewed_at=datetime.now(timezone.utc),
        reviewer="private-reviewer",
        trace_id="trace-private",
        search_ids=["search-private"],
        action_ids=["action-private"],
        ratings=StageRatings(
            trigger="pass", retrieval="pass", application="pass", action="pass"
        ),
        evidence_tier="A",
        evidence_refs=["evidence-private"],
        revisions=EvaluationRevisions(
            client="codex@1",
            model="gpt@1",
            instruction="agents@1",
            retriever="graph@1",
            corpus="git@1",
        ),
    )


async def test_workflow_evaluation_api_requires_existing_ui_auth(uiclient):
    response = await uiclient.get("/ui/api/workflow-evaluation")
    assert response.status_code == 401


async def test_workflow_evaluation_api_is_aggregate_only_and_matches_cli(
    remote, tmp_path, write_valid_fact
):
    origin, seed = remote
    write_valid_fact(seed, "knowledge/domains/tax/x.md")
    push(seed)
    cases = _workflow_case_path()
    store = tmp_path / "reviews.jsonl"
    settings = make_settings(
        tmp_path,
        origin,
        ui_password="",
        workflow_review_path=store,
        workflow_cases_path=cases,
        workflow_reviewer_id="test-human-reviewer",
        workflow_reviewer_token="synthetic-review-token",
    )
    append_review(
        store,
        _workflow_review(),
        suite=load_review_suite(cases),
        settings=settings,
    )
    app = create_app(settings=settings, graph=FakeGraphIndex())
    app.state.services.store.ensure_repo()
    app.state.services.store.fetch_and_ff()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://plk") as client:
        response = await client.get("/ui/api/workflow-evaluation")
    assert response.status_code == 200
    payload = response.json()
    assert payload["e2e_success_rate"] == 1.0
    assert payload["by_case"]["browser-byteflare-profile-selection"]["evaluable"] == 1
    serialized = json.dumps(payload)
    for private_value in (
        "private-reviewer",
        "evidence-private",
        "trace-private",
        "search-private",
        "action-private",
        "ui-review-1",
    ):
        assert private_value not in serialized

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/eval/workflow_review.py",
            "report",
            "--store",
            str(store),
            "--cases",
            str(cases),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "PLK_WORKFLOW_REVIEWER_ID": "test-human-reviewer",
            "PLK_WORKFLOW_REVIEWER_TOKEN": "synthetic-review-token",
        },
    )
    assert json.loads(completed.stdout) == payload


async def test_workflow_evaluation_api_fails_closed_for_unsafe_store(
    remote, tmp_path, write_valid_fact
):
    origin, seed = remote
    write_valid_fact(seed, "knowledge/domains/tax/x.md")
    push(seed)
    store = tmp_path / "reviews.jsonl"
    store.write_text("malformed\n", encoding="utf-8")
    store.chmod(0o600)
    settings = make_settings(
        tmp_path,
        origin,
        ui_password="",
        workflow_review_path=store,
        workflow_cases_path=_workflow_case_path(),
    )
    app = create_app(settings=settings, graph=FakeGraphIndex())
    app.state.services.store.ensure_repo()
    app.state.services.store.fetch_and_ff()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://plk") as client:
        response = await client.get("/ui/api/workflow-evaluation")
    assert response.status_code == 503
    assert response.json()["detail"] == "workflow evaluation data is unavailable"


async def test_metrics_skips_broken_jsonl_and_malformed_fact(
    remote, tmp_path, write_valid_fact
):
    origin, seed = remote
    write_valid_fact(seed, "knowledge/domains/tax/valid.md")
    push(seed)
    settings = make_settings(tmp_path, origin, ui_password="")
    settings.usage_log_path.write_text("not-json\nnull\n[]\n", encoding="utf-8")
    settings.eval_history_path.write_text("not-json\nnull\n", encoding="utf-8")
    app = create_app(settings=settings, graph=FakeGraphIndex())
    app.state.services.store.ensure_repo()
    app.state.services.store.fetch_and_ff()
    broken = settings.knowledge_dir / "domains" / "tax" / "broken.md"
    broken.write_text("---\n[invalid yaml\n---\n", encoding="utf-8")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://plk") as client:
        response = await client.get("/ui/api/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["search"]["total"] == 0 and body["eval"] == {}
    assert body["corpus"]["status"]["active"] == 1
    assert body["corpus"]["skipped_files"] == 1


async def test_ui_without_password_login_is_noop(open_uiclient):
    r = await open_uiclient.post("/ui/login", json={})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert "set-cookie" not in r.headers


async def test_login_form_is_hidden_until_auth_is_required(uiclient):
    r = await uiclient.get("/")
    assert r.status_code == 200
    login_rules = r.text.split("#login {", 1)[1].split("}", 1)[0]
    assert "display: none" in login_rules


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


async def test_ui_proposal_preview_includes_body(uiclient):
    r = await uiclient.get("/static/app.js")
    assert "proposalField(wrap, 'body'" in r.text


async def test_metrics_frontend_uses_safe_dom_and_metrics_endpoint(uiclient):
    response = await uiclient.get("/static/app.js")
    assert "fetch('/ui/api/metrics')" in response.text
    assert response.text.count("innerHTML") == 1
    assert "body.innerHTML = data.body_html" in response.text
    assert "title.textContent" in response.text
    # チャートはホスト実幅で描画し、letterbox（中央寄せの左右余白）を避ける
    assert "chartWidth(host" in response.text
    assert "renderMetricsCharts(lastMetricsData)" in response.text


async def test_metrics_frontend_uses_clear_labels(uiclient):
    page = await uiclient.get("/")
    script = await uiclient.get("/static/app.js")
    visible_copy = page.text + script.text
    assert "判断価値" in page.text
    assert "検索品質" in page.text
    assert "データ状態" in page.text
    assert "週ごとの強い影響の報告" in page.text
    assert "検索方式の対照評価" in page.text
    assert "キル基準" not in visible_copy
    assert "コーパス" not in visible_copy
    assert "proxy OK" not in visible_copy


async def test_metrics_frontend_explains_status_and_next_action(uiclient):
    page = await uiclient.get("/")
    script = await uiclient.get("/static/app.js")
    assert 'id="decisionValueTitle"' in page.text
    assert 'id="decisionNextActionTitle"' in page.text
    assert 'id="decisionValueStats"' in page.text
    assert "判定可能な完了週" in script.text
    assert "未計測や観測開始前の週を0件として扱わず" in script.text
    assert "因果効果や判断の正しさは示しません" in page.text
    assert 'role="tablist" aria-label="利用状況の詳細"' in page.text
    assert "ArrowRight" in script.text and "Home" in script.text


def _font_size_px(css: str, selector: str) -> int:
    """`selector { ... font-size: Npx ... }` の N を返す（宣言順・改行に依存しない）。

    セレクタは規則の先頭に現れるものだけを拾う（`html, body {` を `body` と誤認しない）。
    """
    rule = re.compile(r"(?:^|[{}\n])[ \t]*" + re.escape(selector) + r"\s*\{([^}]*)\}", re.M)
    for match in rule.finditer(css):
        size = re.search(r"font-size:\s*(\d+(?:\.\d+)?)px", match.group(1))
        if size:
            return int(float(size.group(1)))
    raise AssertionError(f"font-size を特定できない: {selector}")


async def test_metrics_frontend_uses_readable_type_sizes(uiclient):
    page = await uiclient.get("/")
    # 具体値ではなく「読める下限」を守る。デザイン変更のたびに壊れないようにする。
    assert _font_size_px(page.text, "body") >= 14
    assert _font_size_px(page.text, ".stat-value") >= 28
    assert _font_size_px(page.text, ".metric-card h2") >= 16
    assert _font_size_px(page.text, ".metrics-heading h1") >= 24
    assert "@media (max-width: 720px)" in page.text
    assert "min-width: 0" in page.text


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


async def test_ui_write_requires_csrf(uiclient):
    await uiclient.post("/ui/login", json={"password": "s3cret"})
    facts = (await uiclient.get("/ui/api/facts")).json()["facts"]
    fid = facts[0]["fact_id"]
    r = await uiclient.post(
        f"/ui/api/facts/{fid}/feedback", json={"feedback": "条件を明確にして"}
    )
    assert r.status_code == 403


async def test_passwordless_loopback_write_session_is_explicitly_gated(
    remote, tmp_path, write_valid_fact
):
    origin, seed = remote
    write_valid_fact(seed, "knowledge/domains/tax/x.md")
    push(seed)
    settings = make_settings(
        tmp_path,
        origin,
        ui_password="",
        ui_writes_enabled=True,
    )
    app = create_app(settings=settings, graph=FakeGraphIndex())
    app.state.services.store.ensure_repo()
    app.state.services.store.fetch_and_ff()
    app.state.services.feedback.runner = StaticFeedbackRunner()
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1"
    ) as client:
        session = await client.get("/ui/session")
        assert session.status_code == 200
        csrf = session.json()["csrf"]
        assert csrf
        facts = (await client.get("/ui/api/facts")).json()["facts"]
        fid = facts[0]["fact_id"]
        accepted = await client.post(
            f"/ui/api/facts/{fid}/feedback",
            json={"feedback": "条件を明確にしてください"},
            headers={"x-plk-csrf": csrf},
        )
        assert accepted.status_code == 202
        await app.state.services.feedback.close()


async def test_passwordless_write_session_rejects_remote_client(
    remote, tmp_path
):
    origin, _ = remote
    settings = make_settings(
        tmp_path,
        origin,
        ui_password="",
        ui_writes_enabled=True,
    )
    app = create_app(settings=settings, graph=FakeGraphIndex())
    transport = httpx.ASGITransport(app=app, client=("203.0.113.10", 12345))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1"
    ) as client:
        session = await client.get("/ui/session")
        assert session.status_code == 403


async def test_ui_feedback_proposal_and_explicit_apply(uiclient):
    login = await uiclient.post("/ui/login", json={"password": "s3cret"})
    csrf = login.json()["csrf"]
    headers = {"x-plk-csrf": csrf}
    facts = (await uiclient.get("/ui/api/facts")).json()["facts"]
    fid = facts[0]["fact_id"]

    submitted = await uiclient.post(
        f"/ui/api/facts/{fid}/feedback",
        json={"feedback": "条件を明確にして"},
        headers=headers,
    )
    assert submitted.status_code == 202
    request_id = submitted.json()["id"]

    request = None
    for _ in range(100):
        rows = (
            await uiclient.get(f"/ui/api/facts/{fid}/feedback")
        ).json()["requests"]
        request = next(row for row in rows if row["id"] == request_id)
        if request["state"] == "proposed":
            break
        await asyncio.sleep(0.01)
    assert request is not None and request["state"] == "proposed"

    applied = await uiclient.post(
        f"/ui/api/feedback/{request_id}/apply", json={}, headers=headers
    )
    assert applied.status_code == 200
    replacement = applied.json()["fact_id"]
    assert replacement != fid
    old = await uiclient.get(f"/ui/api/facts/{fid}")
    new = await uiclient.get(f"/ui/api/facts/{replacement}")
    assert old.json()["meta"]["status"] == "invalidated"
    assert new.json()["meta"]["statement"].endswith("（改善）")


async def test_ui_invalidate_requires_reason(uiclient):
    login = await uiclient.post("/ui/login", json={"password": "s3cret"})
    csrf = login.json()["csrf"]
    facts = (await uiclient.get("/ui/api/facts")).json()["facts"]
    fid = facts[0]["fact_id"]
    detail = (await uiclient.get(f"/ui/api/facts/{fid}")).json()
    r = await uiclient.post(
        f"/ui/api/facts/{fid}/invalidate",
        json={"reason": "短い", "expected_hash": detail["meta"]["_content_hash"]},
        headers={"x-plk-csrf": csrf},
    )
    assert r.status_code == 400
