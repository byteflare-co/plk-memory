"""GitHub PR を PromotionRequest のバックエンドとして駆動する（設計書 §7・§9）。

⚠️ verify-and-adapt: `gh` CLI のサブコマンド/フラグ/JSON 出力キーは
インストール版（gh 2.91.0, 2026-04-22）で `gh pr create --help` /
`gh pr view --help` を実行して確認済み。`--title`/`--body`/`--head`/`--base`/
`--repo` および `--json state,mergedAt` は brief 記載どおりで適応不要だった。
`gh pr create` は標準出力に作成した PR の URL のみを出力する（末尾に改行）。

認証は Mac の既存 `gh auth`（`gh auth status` で確認済み、token scope に
`repo` を含む）を利用。push 用 fine-grained PAT と PR 用資格情報の 2 分離は
EC2/組織展開 期の課題 — 設計書 §7 準拠の注記のみ。Mac 常駐期は新規 PAT を発行しない。
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from typing import Protocol

from plk_memory.gitstore import GitStore
from plk_memory.promotions import PromotionRequest
from plk_memory.settings import Settings

# HTML タグ・HTML コメント（`<...>` の組）のみを除去する。
# 旧実装の `[<>]` 一括除去だと、平文の `->` や `A > B` の比較表現の `>` まで潰れて
# PR 本文の rename 行が `old - new` に化ける表示バグがあった（P2 Task 10 で発見）。
_HTML = re.compile(r"<[^>]*>")


class PromotionBackendError(RuntimeError):
    """gh CLI との対話で回復不能な失敗が起きたときに送出する（silent な偽 PR 番号を防ぐ）。"""


class PromotionBackend(Protocol):
    """PromotionRequest を駆動するバックエンドの構造的型（Task 6 が Fake を注入するため）。

    merged_state の語彙は 4 値: "OPEN" / "APPROVED" / "MERGED" / "CLOSED"。
    "APPROVED" は承認と適用が分離するバックエンド（Slack 承認アダプタ等）専用の
    中間状態で、poll_promotions が proposed → approved の遷移に写像する。
    GitHub backend は承認＝マージのため "APPROVED" を返さない — 既存の GitHub
    経路（OPEN/MERGED/CLOSED の 3 値）への影響はゼロ。
    """

    async def create_pr(self, pr: PromotionRequest) -> tuple[int, str]: ...

    async def merged_state(self, pr_number: int) -> str: ...


def promotion_pr_body(pr: PromotionRequest) -> str:
    """固定テンプレート。生 HTML / HTML コメントを含めない（設計書 §7）。"""
    body = (
        "plk-memory 自動生成の昇格リクエストです。\n\n"
        f"- fact_id: {pr.fact_id}\n"
        f"- from: {pr.from_namespace}\n"
        f"- to: {pr.to_namespace}\n"
        f"- rename: {pr.old_path} -> {pr.new_path}\n\n"
        "承認判断は本文でなく Files changed（namespace 行 1 行のみの rename）を正とすること。\n"
    )
    return _HTML.sub("", body)


def parse_pr_view(json_str: str) -> str:
    data = json.loads(json_str)
    if data.get("mergedAt"):
        return "MERGED"
    return str(data.get("state", "OPEN")).upper()


class GitHubPromotionBackend:
    def __init__(self, store: GitStore, settings: Settings):
        self.store = store
        self.settings = settings

    async def create_pr(self, pr: PromotionRequest) -> tuple[int, str]:
        await self.store.build_promotion_branch(
            old_rel=pr.old_path, new_rel=pr.new_path, branch=pr.branch,
            message=f"promote: {pr.old_path} -> {pr.new_path}",
        )
        title = f"promote {pr.fact_id} to shared"
        try:
            url = await asyncio.to_thread(
                self._gh, "pr", "create", "--repo", self.settings.repo_slug,
                "--base", "main", "--head", pr.branch,
                "--title", title, "--body", promotion_pr_body(pr),
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            if "already exists" in stderr.lower():
                # 同一ブランチ（同一ファクトの再提案）で既に OPEN な PR がある場合は
                # 偽の新規 PR を作らず、既存 PR を照会して再利用する。
                return await self._reuse_existing_pr(pr.branch)
            raise PromotionBackendError(
                f"gh pr create に失敗した（fact_id={pr.fact_id}）: {stderr.strip() or e}"
            ) from e
        url = url.strip()
        m = re.search(r"/pull/(\d+)", url)
        if m is None:
            # silent に偽の PR 番号（0）を返すと下流の merged_state に流れて誤判定するため例外化する。
            raise PromotionBackendError(
                f"gh pr create の出力から PR 番号を抽出できない（fact_id={pr.fact_id}）: {url!r}"
            )
        number = int(m.group(1))
        return number, url

    async def _reuse_existing_pr(self, branch: str) -> tuple[int, str]:
        out = await asyncio.to_thread(
            self._gh, "pr", "view", branch, "--repo", self.settings.repo_slug,
            "--json", "number,url",
        )
        data = json.loads(out)
        return int(data["number"]), str(data["url"])

    async def merged_state(self, pr_number: int) -> str:
        out = await asyncio.to_thread(
            self._gh, "pr", "view", str(pr_number), "--repo", self.settings.repo_slug,
            "--json", "state,mergedAt",
        )
        return parse_pr_view(out)

    def _gh(self, *args: str) -> str:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
        return r.stdout
