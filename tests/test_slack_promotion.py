import pytest

from plk_memory.app import create_app
from plk_memory.auth import current_client
from plk_memory.promotions import PromotionState, new_promotion
from plk_memory.slack_promotion import (
    SlackPromotionBackend,
    build_approval_blocks,
    parse_action_callback,
)
from tests.conftest import make_settings
from tests.fakes import FakeGraphIndex


def make_pr():
    return new_promotion(
        fact_id="01JZC2V7E8B3F4G5H6J7K8M9N0",
        from_namespace="plk.domain.tax",
        old_path="knowledge/domains/tax/x.md",
        new_path="knowledge/shared/x.md",
        branch="promote/01JZC2V7E8B3F4G5H6J7K8M9N0",
    )


def test_build_approval_blocks_golden():
    pr = make_pr()
    blocks = build_approval_blocks(pr)
    assert blocks == [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*plk-memory 昇格リクエスト*\n"
                    "・fact_id: `01JZC2V7E8B3F4G5H6J7K8M9N0`\n"
                    "・from: `plk.domain.tax` → to: `plk.shared`\n"
                    "・rename: `knowledge/domains/tax/x.md` → `knowledge/shared/x.md`"
                ),
            },
        },
        {
            "type": "actions",
            "block_id": pr.id,
            "elements": [
                {
                    "type": "button",
                    "action_id": "plk_promote_approve",
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "承認"},
                    "value": pr.id,
                },
                {
                    "type": "button",
                    "action_id": "plk_promote_reject",
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "却下"},
                    "value": pr.id,
                },
            ],
        },
    ]


def test_parse_approve_callback():
    # Slack backend では承認と適用が分離するため、承認は中間状態 APPROVED に写像される
    pr = make_pr()
    payload = {
        "actions": [{"action_id": "plk_promote_approve", "value": pr.id}],
    }
    assert parse_action_callback(payload) == (pr.id, "APPROVED")


def test_parse_reject_callback():
    pr = make_pr()
    payload = {"actions": [{"action_id": "plk_promote_reject", "value": pr.id}]}
    assert parse_action_callback(payload) == (pr.id, "CLOSED")


async def test_backend_state_lifecycle():
    """スタブ backend の 4 値語彙: OPEN →（承認）APPROVED →（適用）MERGED。"""
    pr = make_pr()
    backend = SlackPromotionBackend()
    number, url = await backend.create_pr(pr)         # Protocol: create_pr
    assert isinstance(number, int) and url.startswith("https://")
    # 承認コールバックが来るまでは未確定（OPEN）
    assert await backend.merged_state(number) == "OPEN"
    # Slack 承認ボタン押下を模した callback → 承認（APPROVED、まだ未適用）
    pid, mapped = parse_action_callback(
        {"actions": [{"action_id": "plk_promote_approve", "value": pr.id}]}
    )
    assert pid == pr.id
    backend.record_decision(number, mapped)
    assert await backend.merged_state(number) == "APPROVED"
    # 適用（実装では git 移動＋commit）→ MERGED
    backend.record_applied(number)
    assert await backend.merged_state(number) == "MERGED"


@pytest.fixture
async def sctx(remote, tmp_path):
    origin, seed = remote
    settings = make_settings(tmp_path, origin, tokens={"tok-cc": "claude-code"}, admin_token="tok-admin")
    backend = SlackPromotionBackend()
    app = create_app(settings=settings, graph=FakeGraphIndex(), promotion_backend=backend)
    svcs = app.state.services
    svcs.store.ensure_repo()
    current_client.set("claude-code")
    return svcs, backend


VALID_ARGS = dict(
    namespace="plk.domain.tax", kind="knowhow",
    statement="法人税の中間申告は前期税額20万円超で必要になる制度である",
    why="国税庁タックスアンサーの中間申告の要件に明記されているため",
    how_to_apply="設立2期目以降、前期法人税額を確認して要否を判定する",
    source="https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5000.htm",
)


async def _propose(svcs):
    add = await svcs.tool_add(**VALID_ARGS)
    out = await svcs.tool_propose_promotion(add["fact_id"], reason="安定運用に足る")
    assert out["state"] == "proposed"
    pr = svcs.promotion_store.get(out["promotion_id"])
    return pr


async def test_poll_drives_approved_then_applied(sctx):
    """承認と適用の分離を poll_promotions 経由で e2e に通す（approved 経路の実駆動）。"""
    svcs, backend = sctx
    pr = await _propose(svcs)
    number = pr.pr_number

    # ① 承認 callback → poll → proposed → approved（sync はまだ走らない）
    pid, mapped = parse_action_callback(
        {"actions": [{"action_id": "plk_promote_approve", "value": pr.id}]}
    )
    assert pid == pr.id
    backend.record_decision(number, mapped)
    result = await svcs.poll_promotions()
    assert result["applied"] == 0
    assert svcs.promotion_store.get(pr.id).state is PromotionState.approved

    # ② 適用の記録 → poll → approved → applied
    backend.record_applied(number)
    result = await svcs.poll_promotions()
    assert result["applied"] == 1
    assert svcs.promotion_store.get(pr.id).state is PromotionState.applied


async def test_poll_drives_rejected_on_reject_callback(sctx):
    svcs, backend = sctx
    pr = await _propose(svcs)

    pid, mapped = parse_action_callback(
        {"actions": [{"action_id": "plk_promote_reject", "value": pr.id}]}
    )
    assert (pid, mapped) == (pr.id, "CLOSED")
    backend.record_decision(pr.pr_number, mapped)
    result = await svcs.poll_promotions()
    assert result["rejected"] == 1
    assert svcs.promotion_store.get(pr.id).state is PromotionState.rejected
