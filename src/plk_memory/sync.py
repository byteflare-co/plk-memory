"""level-triggered 同期エンジン（設計書 §6-3〜5）。

`_delete_by_id` は async に統一する（rename・delete いずれの経路も await で呼ぶ）。
frontmatter が無い/id を持たない md（例: CONVENTIONS.md 以外の非ファクトファイル）は
ファクトとして扱わず、dead_letter にも記録しない（FactService.index() と同じ扱い）。
rename は「旧 entry を delete → 新 entry を upsert」で 1 ファクトの移動として扱うため、
`deleted` カウントには含めない（実際にファクトが失われたわけではないため）。
"""

from __future__ import annotations

import asyncio

import frontmatter

from plk_memory.facts import FactService, require_metadata_str
from plk_memory.gitstore import GitStore, HistoryRewritten
from plk_memory.settings import Settings
from plk_memory.state import StateStore, SyncState


def parse_name_status(text: str) -> list[list[str]]:
    return [line.split("\t") for line in text.splitlines() if line.strip()]


class ReindexInProgress(RuntimeError):
    pass


class SyncEngine:
    def __init__(self, store: GitStore, facts: FactService, graph, state_store: StateStore, settings: Settings):
        self.store = store
        self.facts = facts
        self.graph = graph
        self.state_store = state_store
        self.settings = settings
        self.maintenance = False
        self.degraded: str | None = None
        self._sync_lock = asyncio.Lock()

    async def sync(self) -> dict:
        async with self._sync_lock:
            return await self._sync_locked()

    async def _sync_locked(self) -> dict:
        try:
            # Keep the dedicated clone on one immutable HEAD while graph/state
            # projection reads it. This shares the same lock as add/invalidate.
            async with self.store.write_lock():
                return await self._sync_store_locked()
        except HistoryRewritten as e:
            self.degraded = str(e)
            return {
                "upserted": 0, "deleted": 0, "dead_letters": {},
                "head": self.store.head(), "degraded": self.degraded,
            }

    async def _sync_store_locked(self) -> dict:
        # git 由来の degraded 解除。graph 未 ready であれば直後で上書きされる
        # （「git は正常・graph が原因」という状態を正しく表すための順序）。
        self.degraded = None
        if not self.graph.ready:
            self.degraded = "graph index not ready"
            return {
                "upserted": 0, "deleted": 0, "dead_letters": {},
                "head": self.store.head(), "degraded": self.degraded,
            }

        state = self.state_store.load()
        head = self.store.head()
        upserted = deleted = 0

        # 対象 path 集合を決める（初回=全ファイル / 差分 + 既存 dead letters）
        targets: dict[str, None] = {}
        if state.last_ingested_commit is None:
            for _, rel in self.facts.list_posts():
                targets[rel] = None
        elif state.last_ingested_commit != head:
            diff = self.store.git(
                "diff", "--name-status", "--find-renames",
                f"{state.last_ingested_commit}..{head}", "--",
                self.settings.knowledge_subdir + "/",
            )
            for entry in parse_name_status(diff):
                status, paths = entry[0], entry[1:]
                if status.startswith("R"):
                    old_id = self._id_at(state.last_ingested_commit, paths[0])
                    await self._delete_by_id(state, old_id)
                    # rename は delete+upsert で 1 ファクトの移動として扱う（deleted には含めない）
                    targets[paths[1]] = None
                elif status == "D":
                    old_id = self._id_at(state.last_ingested_commit, paths[0])
                    if await self._delete_by_id(state, old_id):
                        deleted += 1
                else:  # A / M
                    targets[paths[0]] = None

        for p in list(state.dead_letters):
            targets.setdefault(p, None)

        for rel in sorted(targets):
            try:
                path = self.settings.data_repo_path / rel
                if not path.exists():
                    state.dead_letters.pop(rel, None)
                    continue
                post = frontmatter.load(path)
                if post.get("id") is None:
                    # ファクトの frontmatter を持たない md（非対象ファイル）は無視する。
                    state.dead_letters.pop(rel, None)
                    continue
                fid = require_metadata_str(post, "id")
                old = state.facts.get(fid)
                entry = await self.graph.upsert_fact(post, old)
                if entry.episode_uuids:
                    state.facts[fid] = entry
                else:
                    state.facts.pop(fid, None)  # invalidated
                state.dead_letters.pop(rel, None)
                upserted += 1
            except Exception as e:
                state.dead_letters[rel] = str(e)

        state.last_ingested_commit = head
        self.state_store.save(state)
        return {
            "upserted": upserted, "deleted": deleted,
            "dead_letters": dict(state.dead_letters), "head": head, "degraded": None,
        }

    def _id_at(self, ref: str, rel: str) -> str | None:
        try:
            post = frontmatter.loads(self.store.git("show", f"{ref}:{rel}"))
            if post.get("id") is None:
                return None
            return require_metadata_str(post, "id")
        except Exception:
            return None

    async def _delete_by_id(self, state: SyncState, fact_id: str | None) -> bool:
        if fact_id and fact_id in state.facts:
            await self.graph.delete_fact(state.facts.pop(fact_id))
            return True
        return False

    def begin_reindex(self) -> bool:
        """ルート用の同期 check-and-set。既に実行中なら False。
        event loop 上で await を挟まずに呼ぶことで、/admin/reindex 連打の
        2 件目を確実に 409 にする（silent drop 修正）。"""
        if self.maintenance:
            return False
        self.maintenance = True
        return True

    def end_reindex(self) -> None:
        self.maintenance = False

    async def _do_reindex(self) -> dict:
        """フラグ管理を含まない再構築本体。呼び出し側が maintenance を保持している前提。"""
        async with self._sync_lock:
            await self.graph.clear(self.settings.all_groups())
            state = self.state_store.load()
            state.facts = {}
            state.dead_letters = {}
            state.last_ingested_commit = None
            self.state_store.save(state)
            return await self._sync_locked()

    async def reindex(self) -> dict:
        """スタンドアロン用（テスト・手動）。自己でフラグを立て、二重起動を拒否する。"""
        if not self.begin_reindex():
            raise ReindexInProgress("reindex は既に実行中")
        try:
            return await self._do_reindex()
        finally:
            self.end_reindex()

    async def status(self) -> dict:
        state = self.state_store.load()
        head = self.store.head()
        unpushed = self.store.git("rev-list", "--count", "origin/main..HEAD").strip()
        result = {
            "head": head,
            "last_ingested_commit": state.last_ingested_commit,
            "index_stale": state.last_ingested_commit != head,
            "indexed_facts": len(state.facts),
            "dead_letters": dict(state.dead_letters),
            "unpushed_commits": int(unpushed),
            "maintenance": self.maintenance,
            "degraded": self.degraded,
        }
        # 台帳（state.facts）とグラフ実体の乖離チェック。indexed_facts > 0 なのに
        # グラフのエッジ総数が 0 なら、RDB 消失・誤ルーティング等で検索が全クエリ
        # 0 ヒットになる状態（index_stale では検知不能）。復旧は /admin/reindex。
        graph_edges: dict[str, int] | None = None
        graph_empty_mismatch: bool | None = None
        if self.graph.ready:
            try:
                counts = await self.graph.edge_counts(self.settings.all_groups())
                graph_edges = counts
                graph_empty_mismatch = bool(state.facts) and sum(counts.values()) == 0
            except Exception as e:
                result["graph_count_error"] = str(e)
        result["graph_edges"] = graph_edges
        result["graph_empty_mismatch"] = graph_empty_mismatch
        return result
