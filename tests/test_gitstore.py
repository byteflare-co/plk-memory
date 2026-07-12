import subprocess

import pytest

from plk_memory.gitstore import (
    AnotherInstanceRunning,
    GitStore,
    HistoryRewritten,
    WriteConflict,
    rewrite_namespace_line,
)
from tests.conftest import make_settings, make_store, sh
from tests.gitsync_helpers import push


def test_rewrite_namespace_line_changes_only_that_line():
    """回帰: frontmatter の load→dumps 往復がキー順・クォート・datetime 表記を
    正規化してしまい、昇格 PR が「namespace 1 行のみの rename」にならず CI が
    落ちたバグ（P2 Task 10・実 PR #1 で発覚）。namespace 行以外はバイト不変であること。"""
    text = (
        "---\n"
        "id: 01JZC2V7E8B3F4G5H6J7K8M9N0\n"
        'statement: "A -> B の順で mcp<2 を維持する。"\n'
        "created_at: 2026-07-02T14:18:51+09:00\n"
        "namespace: plk.domain.dev\n"
        'tags: ["MCP", "python-sdk"]\n'
        "---\n"
        "\n"
        "本文（末尾改行なし）"
    )
    out = rewrite_namespace_line(text)
    assert out == text.replace("namespace: plk.domain.dev", "namespace: plk.shared")
    diff = [(a, b) for a, b in zip(text.splitlines(), out.splitlines()) if a != b]
    assert diff == [("namespace: plk.domain.dev", "namespace: plk.shared")]


def test_rewrite_namespace_line_raises_without_namespace():
    with pytest.raises(ValueError):
        rewrite_namespace_line("---\nid: x\n---\nbody")


def test_ensure_repo_clones(remote, tmp_path):
    origin, _ = remote
    store = make_store(tmp_path, origin)
    assert (store.settings.data_repo_path / "knowledge" / "a.md").exists()


def test_single_instance_guard(remote, tmp_path):
    origin, _ = remote
    store = make_store(tmp_path, origin)
    second = GitStore(store.settings)
    with pytest.raises(AnotherInstanceRunning):
        second.ensure_repo()


async def test_commit_and_push_reaches_remote(remote, tmp_path):
    origin, seed = remote
    store = make_store(tmp_path, origin)
    (store.settings.data_repo_path / "knowledge" / "b.md").write_text("b", encoding="utf-8")
    sha = await store.commit_and_push(["knowledge/b.md"], "add b")
    sh(seed, "pull")
    assert (seed / "knowledge" / "b.md").exists()
    assert sha in sh(seed, "log", "--format=%H", "-1")


async def test_push_rejected_then_rebase_succeeds(remote, tmp_path):
    origin, seed = remote
    store = make_store(tmp_path, origin)
    # リモートに他者の commit を先行させる（non-conflicting）
    (seed / "knowledge" / "other.md").write_text("o", encoding="utf-8")
    sh(seed, "add", "-A")
    sh(seed, "commit", "-m", "other")
    sh(seed, "push")
    (store.settings.data_repo_path / "knowledge" / "b.md").write_text("b", encoding="utf-8")
    await store.commit_and_push(["knowledge/b.md"], "add b")
    log = sh(seed, "pull") + sh(seed, "log", "--oneline")
    assert "add b" in log and "other" in log


async def test_conflicting_push_raises_write_conflict(remote, tmp_path):
    origin, seed = remote
    store = make_store(tmp_path, origin)
    # 同一ファイルをリモートとローカルで別内容に
    (seed / "knowledge" / "a.md").write_text("remote version", encoding="utf-8")
    sh(seed, "add", "-A")
    sh(seed, "commit", "-m", "remote edit")
    sh(seed, "push")
    (store.settings.data_repo_path / "knowledge" / "a.md").write_text("local version", encoding="utf-8")
    with pytest.raises(WriteConflict):
        await store.commit_and_push(["knowledge/a.md"], "local edit")
    # 作業ツリーが壊れていない（rebase 中で止まっていない）こと
    assert "rebase" not in store.git("status").lower()


async def test_push_retry_exhausted_resets_to_remote(remote, tmp_path, monkeypatch):
    origin, _ = remote
    store = make_store(tmp_path, origin)
    original_git = GitStore.git

    def failing_push(self, *args):
        if args and args[0] == "push":
            raise subprocess.CalledProcessError(1, ["git", "push"])
        return original_git(self, *args)

    monkeypatch.setattr(GitStore, "git", failing_push)
    (store.settings.data_repo_path / "knowledge" / "b.md").write_text("b", encoding="utf-8")
    with pytest.raises(WriteConflict, match="リトライ上限"):
        await store.commit_and_push(["knowledge/b.md"], "add b")
    monkeypatch.undo()
    # ローカル commit が破棄され origin と分岐していない
    assert store.git("rev-list", "--count", "origin/main..HEAD").strip() == "0"
    assert store.git("status", "--porcelain").strip() == ""


def test_history_rewrite_detected_not_reset(remote, tmp_path):
    origin, seed = remote
    store = make_store(tmp_path, origin)
    # リモート履歴を書き換え（amend + force push）
    sh(seed, "commit", "--amend", "-m", "rewritten")
    sh(seed, "push", "--force")
    with pytest.raises(HistoryRewritten):
        store.fetch_and_ff()


def test_ensure_repo_uses_configured_identity(remote, tmp_path):
    origin, _ = remote
    s = make_settings(tmp_path, origin, git_author_name="alice", git_author_email="alice@example.com")
    store = GitStore(s)
    store.ensure_repo()
    assert store.git("config", "user.name").strip() == "alice"
    assert store.git("config", "user.email").strip() == "alice@example.com"


async def test_build_promotion_branch_pushes_and_keeps_main(remote, tmp_path, write_valid_fact):
    origin, seed = remote
    store = make_store(tmp_path, origin)
    # seed に昇格対象ファクトを置いて main に反映
    write_valid_fact(seed, "knowledge/domains/tax/x.md")
    push(seed)
    store.fetch_and_ff()
    main_before = store.head()
    await store.build_promotion_branch(
        old_rel="knowledge/domains/tax/x.md",
        new_rel="knowledge/shared/x.md",
        branch="promote/x",
        message="promote x",
    )
    # メイン作業ツリーの HEAD は不変（read と競合しない）
    assert store.head() == main_before
    # origin にブランチが push されている
    assert "promote/x" in sh(seed, "ls-remote", "--heads", str(origin))
    # git が rename として検出し、内容差分は namespace 行 1 行のみ（CI check_promotion の要件）
    sh(seed, "fetch", "origin", "promote/x")
    stat = sh(seed, "diff", "--find-renames", "--name-status", "origin/main", "FETCH_HEAD")
    assert stat.strip().startswith("R")  # R100 ではなく R9x（1 行差分）でも rename 扱い
    body_diff = sh(seed, "diff", "--find-renames", "origin/main", "FETCH_HEAD")
    added = [ln for ln in body_diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln for ln in body_diff.splitlines() if ln.startswith("-") and not ln.startswith("---")]
    assert added == ["+namespace: plk.shared"]
    assert len(removed) == 1 and removed[0].startswith("-namespace:")
