"""テスト用の in-memory GraphIndex（interface 互換）。"""

import asyncio

from plk_memory.graphindex import SearchHit
from plk_memory.rendering import content_hash, render_episode
from plk_memory.state import FactIndexEntry


class FakeGraphIndex:
    def __init__(self, fail_for: set[str] | None = None, upsert_delay: float = 0.0):
        self.docs: dict[str, dict] = {}  # fact_id -> {text, group_id}
        self.fail_for = fail_for or set()
        self.ready = True
        self.upsert_delay = upsert_delay
        self.upsert_calls = 0

    async def start(self):
        pass

    async def upsert_fact(self, post, old):
        self.upsert_calls += 1
        if self.upsert_delay:
            await asyncio.sleep(self.upsert_delay)
        fid = post["id"]
        if fid in self.fail_for:
            raise RuntimeError(f"fake ingest failure: {fid}")
        if old:
            self.docs.pop(next(iter(old.episode_uuids), None), None)
        if post["status"] == "invalidated":
            self.docs.pop(fid, None)
            return FactIndexEntry()
        self.docs[fid] = {"text": render_episode(post), "group_id": "plk-main"}
        return FactIndexEntry(episode_uuids=[fid], content_hash=content_hash(post), group_id="plk-main")

    async def delete_fact(self, old):
        for u in old.episode_uuids:
            self.docs.pop(u, None)

    async def search(self, query, group_ids, uuid_to_fact, limit=10):
        hits = [
            SearchHit(fact_id=fid, fact_text=d["text"][:80])
            for fid, d in self.docs.items()
            if any(tok in d["text"] for tok in query.split())
        ]
        return hits[:limit]

    async def clear(self, group_ids):
        self.docs.clear()


class FakePromotionBackend:
    """テスト用: PR 作成を記録し、merged_state を制御可能にする。"""

    def __init__(self):
        self.created: list = []
        self.state_by_number: dict[int, str] = {}
        self._next_number = 100

    async def create_pr(self, pr):
        self._next_number += 1
        number = self._next_number
        self.created.append(pr)
        self.state_by_number[number] = "OPEN"
        return number, f"https://github.com/cutsome/agent-organization/pull/{number}"

    async def merged_state(self, pr_number):
        return self.state_by_number.get(pr_number, "OPEN")
