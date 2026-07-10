import pytest


@pytest.fixture
async def pctx(remote, tmp_path):
    origin, seed = remote
    from tests.conftest import make_settings
    from plk_memory.app import create_app
    from plk_memory.auth import current_client
    from tests.fakes import FakeGraphIndex, FakePromotionBackend
    settings = make_settings(tmp_path, origin, tokens={"tok-cc": "claude-code"}, admin_token="tok-admin")
    backend = FakePromotionBackend()
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


async def test_propose_creates_promotion_and_pr(pctx):
    svcs, backend = pctx
    add = await svcs.tool_add(**VALID_ARGS)
    out = await svcs.tool_propose_promotion(add["fact_id"], reason="安定運用に足る")
    assert out["state"] == "proposed" and out["pr_url"].endswith("/pull/101")
    assert len(backend.created) == 1


async def test_propose_rejects_non_domain_namespace(pctx):
    svcs, _ = pctx
    # shared は add 自体が不可なので、quarantine を propose 対象にして弾かれることを見る
    q = dict(VALID_ARGS, namespace="plk.quarantine", source_type="external-untrusted")
    add = await svcs.tool_add(**q)
    out = await svcs.tool_propose_promotion(add["fact_id"])
    assert "error" in out


async def test_propose_is_idempotent_per_fact(pctx):
    svcs, backend = pctx
    add = await svcs.tool_add(**VALID_ARGS)
    await svcs.tool_propose_promotion(add["fact_id"])
    out = await svcs.tool_propose_promotion(add["fact_id"])
    assert "error" in out and out.get("promotion_id")
    assert len(backend.created) == 1  # 二重 PR を作らない


async def test_concurrent_propose_same_fact_creates_one_record(pctx):
    import asyncio
    svcs, backend = pctx
    add = await svcs.tool_add(**VALID_ARGS)
    fid = add["fact_id"]
    r1, r2 = await asyncio.gather(
        svcs.tool_propose_promotion(fid),
        svcs.tool_propose_promotion(fid),
    )
    # どちらか片方だけが proposed を返し、もう片方は重複拒否になる
    assert "proposed" in [r1.get("state"), r2.get("state")]
    # 永続レコードは 1 件だけ（重複レコードが生まれない）
    assert len(svcs.promotion_store.by_fact(fid)) == 1
    # backend への PR 作成も 1 回だけ
    assert len(backend.created) == 1


async def test_poll_applies_on_merge_and_reingests(pctx):
    svcs, backend = pctx
    add = await svcs.tool_add(**VALID_ARGS)
    out = await svcs.tool_propose_promotion(add["fact_id"])
    # 人間が seed 側で PR をマージした状況を FakeBackend の状態で模す
    number = int(out["pr_url"].rsplit("/", 1)[1])
    backend.state_by_number[number] = "MERGED"
    result = await svcs.poll_promotions()
    assert result["applied"] == 1
    from plk_memory.promotions import PromotionState
    assert svcs.promotion_store.by_state(PromotionState.applied)
    # applied は pending から消える
    status = await svcs.tool_status()
    assert status["pending_promotions"] == []


async def test_propose_rolls_back_store_when_create_pr_fails(pctx):
    svcs, backend = pctx
    add = await svcs.tool_add(**VALID_ARGS)

    async def failing_create_pr(pr):
        raise RuntimeError("gh: rate limited")

    backend.create_pr = failing_create_pr
    out = await svcs.tool_propose_promotion(add["fact_id"])
    # ①error が返る
    assert "error" in out and "PR 作成に失敗" in out["error"]
    # ②store にレコードが残らない（復旧不能な proposed/pr_number=None を残さない）
    assert svcs.promotion_store.by_fact(add["fact_id"]) == []
    # ③同 fact の再 propose が通る（backend 復旧後）
    del backend.create_pr  # インスタンス属性を消してクラスの正常実装に戻す
    out2 = await svcs.tool_propose_promotion(add["fact_id"])
    assert out2["state"] == "proposed" and "pr_url" in out2


async def test_status_lists_pending(pctx):
    svcs, _ = pctx
    add = await svcs.tool_add(**VALID_ARGS)
    await svcs.tool_propose_promotion(add["fact_id"])
    status = await svcs.tool_status()
    assert len(status["pending_promotions"]) == 1
    assert status["pending_promotions"][0]["fact_id"] == add["fact_id"]
