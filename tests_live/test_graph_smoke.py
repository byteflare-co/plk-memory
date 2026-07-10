"""FalkorDB / Ollama / Anthropic への実接続が必要な統合テスト。

DO NOT RUN in this sandbox — pytest addopts (`-m 'not live'`) は既定で
このファイルを除外する。実行するには `uv run pytest tests_live/ -m live`。
"""

import frontmatter
import pytest

from plk_memory.graphindex import GraphIndex
from plk_memory.settings import Settings

pytestmark = pytest.mark.live


async def test_upsert_search_delete_roundtrip():
    s = Settings(tokens={"t": "c"}, admin_token="a", _env_file=None)
    g = GraphIndex(s)
    await g.start()
    meta = {
        "id": "01JZC2LIVE0000000000000000",
        "kind": "knowhow",
        "statement": "持続化補助金の経費は税込金額で積算する",
        "why": "免税事業者は税込経理のため補助対象経費も税込で扱う",
        "how_to_apply": "申請書の経費明細を税込で記載する",
        "source": "https://example.com",
        "source_type": "user",
        "namespace": "plk.domain.tax",
        "status": "active",
        "written_by": "test",
        "created_at": "2026-07-02T10:00:00+09:00",
        "tags": ["補助金"],
    }
    post = frontmatter.Post("", **meta)
    entry = await g.upsert_fact(post, None)
    assert entry.episode_uuids
    hits = await g.search(
        "補助金の経費は税込か税抜か",
        [s.main_group],
        {u: meta["id"] for u in entry.episode_uuids},
        limit=5,
    )
    assert any(h.fact_id == meta["id"] for h in hits)
    await g.delete_fact(entry)
    await g.clear([s.main_group])
