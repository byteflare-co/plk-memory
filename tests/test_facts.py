import hashlib

import pytest

from plk_memory.facts import FactError, FactNotFound, FactService

VALID = dict(
    namespace="plk.domain.tax",
    kind="knowhow",
    statement="法人税の中間申告は前期税額20万円超で必要になる制度である",
    why="国税庁タックスアンサーの中間申告の要件に明記されているため",
    how_to_apply="設立2期目以降、前期法人税額を確認して要否を判定する",
    source="https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5000.htm",
    tags=["中間申告"],
    body="詳細メモ。",
)


@pytest.fixture
def svc(remote, tmp_path):
    origin, _ = remote
    from tests.conftest import make_store
    store = make_store(tmp_path, origin)
    return FactService(store, store.settings)


async def test_add_creates_valid_fact_and_pushes(svc, remote):
    fact_id = await svc.add(client="claude-code", **VALID)
    post, rel = svc.get(fact_id)
    assert post["written_by"] == "claude-code"
    assert post["source_type"] == "agent"
    assert rel.startswith("knowledge/domains/tax/")
    # push 済み = origin に届いている
    assert svc.store.git("rev-list", "--count", "origin/main..HEAD").strip() == "0"


async def test_add_rejects_user_source_type(svc):
    with pytest.raises(FactError, match="user"):
        await svc.add(client="claude-code", source_type="user", **VALID)


async def test_add_rejects_philosophy_kind(svc):
    args = {**VALID, "kind": "philosophy"}
    with pytest.raises(FactError, match="philosophy.*PR"):
        await svc.add(client="claude-code", **args)


async def test_add_rejects_shared_namespace(svc):
    args = {**VALID, "namespace": "plk.shared"}
    with pytest.raises(FactError, match="shared"):
        await svc.add(client="claude-code", **args)


async def test_untrusted_requires_quarantine(svc):
    args = {**VALID, "namespace": "plk.domain.dev"}
    with pytest.raises(FactError, match="quarantine"):
        await svc.add(client="claude-code", source_type="external-untrusted", **args)


async def test_add_rejects_secret_and_cleans_up(svc):
    args = {**VALID, "body": "キー: " + "sk-ant-" + "api03-" + "x" * 24}
    with pytest.raises(FactError, match="シークレット"):
        await svc.add(client="claude-code", **args)
    # 作業ツリーに書きかけファイルが残っていない
    assert svc.store.git("status", "--porcelain").strip() == ""


async def test_add_rejects_invalid_content(svc):
    args = {**VALID, "statement": "短い"}
    with pytest.raises(FactError):
        await svc.add(client="claude-code", **args)


async def test_supersedes_is_atomic_single_commit(svc):
    old_id = await svc.add(client="claude-code", **VALID)
    new_args = {**VALID, "statement": "中間申告の判定は前期税額だけでなく仮決算方式の選択も併せて検討する"}
    before = svc.store.git("rev-list", "--count", "HEAD").strip()
    new_id = await svc.add(client="claude-code", supersedes=[old_id], **new_args)
    after = svc.store.git("rev-list", "--count", "HEAD").strip()
    assert int(after) == int(before) + 1  # 追加+無効化が 1 commit
    old_post, _ = svc.get(old_id)
    assert old_post["status"] == "invalidated"
    assert old_post["superseded_by"] == new_id
    assert old_post["invalidation_reason"]


async def test_supersedes_missing_second_target_leaves_tree_clean(svc):
    old_id = await svc.add(client="claude-code", **VALID)
    args = {**VALID, "statement": "後継のファクトとして書かれた二十字以上ある要旨"}
    with pytest.raises(FactError, match="supersedes"):
        await svc.add(client="claude-code",
                      supersedes=[old_id, "01JZC2V7E8B3F4G5H6J7K8M9ZZ"], **args)
    assert svc.store.git("status", "--porcelain").strip() == ""
    old_post, _ = svc.get(old_id)
    assert old_post["status"] == "active"  # 巻き添え書き換えなし


async def test_supersedes_rejects_changed_expected_hash(svc):
    old_id = await svc.add(client="claude-code", **VALID)
    _, rel = svc.get(old_id)
    old_hash = hashlib.sha256(
        (svc.settings.data_repo_path / rel).read_bytes()
    ).hexdigest()
    await svc.invalidate(old_id, "依頼後に前提が変わったため無効化", client="codex")
    args = {**VALID, "statement": "古い提案を誤って反映しないための後継ファクトである"}
    with pytest.raises(FactError, match="変更されています"):
        await svc.add(
            client="plk-web-ui",
            supersedes=[old_id],
            expected_superseded_hashes={old_id: old_hash},
            **args,
        )


async def test_invalidate_writes_reason(svc):
    fact_id = await svc.add(client="claude-code", **VALID)
    await svc.invalidate(fact_id, "制度改正で前提が変わった", client="codex")
    post, _ = svc.get(fact_id)
    assert post["status"] == "invalidated"
    assert post["invalidation_reason"] == "制度改正で前提が変わった"


async def test_invalidate_rejects_stale_hash_and_already_invalidated(svc):
    fact_id = await svc.add(client="claude-code", **VALID)
    with pytest.raises(FactError, match="変更されています"):
        await svc.invalidate(
            fact_id,
            "古い画面からの無効化を拒否する",
            client="plk-web-ui",
            expected_hash="0" * 64,
        )
    await svc.invalidate(fact_id, "制度改正で前提が変わった", client="codex")
    with pytest.raises(FactError, match="active ではない"):
        await svc.invalidate(fact_id, "二重無効化を拒否する", client="codex")


async def test_history_returns_commits_and_chain(svc):
    old_id = await svc.add(client="claude-code", **VALID)
    new_args = {**VALID, "statement": "中間申告の判定は前期税額だけでなく仮決算方式の選択も併せて検討する"}
    new_id = await svc.add(client="claude-code", supersedes=[old_id], **new_args)
    h = svc.history(old_id)
    assert len(h["commits"]) >= 1
    assert h["superseded_by"] == new_id


def test_get_missing_raises(svc):
    with pytest.raises(FactNotFound):
        svc.get("01JZC2V7E8B3F4G5H6J7K8M9ZZ")
