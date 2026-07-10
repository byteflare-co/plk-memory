from types import SimpleNamespace

import frontmatter
import pytest
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

from plk_memory.graphindex import _build_llm_client, _resolve_hits
from plk_memory.settings import Settings


def edge(fact, episodes, score=None):
    return SimpleNamespace(fact=fact, episodes=episodes, score=score)


def test_resolve_maps_dedupes_and_limits():
    u2f = {"u1": "F1", "u2": "F2", "u3": "F3"}
    edges = [
        edge("最初のfact", ["u1"]),
        edge("同じファクト由来の別エッジ", ["u1"]),  # dedupe される
        edge("別ファクト", ["u2"]),
        edge("帰属不明", []),  # スキップ
        edge("未知uuid", ["zz"]),  # スキップ
        edge("3件目", ["u3"]),
    ]
    hits = _resolve_hits(edges, u2f, limit=2)
    assert [h.fact_id for h in hits] == ["F1", "F2"]
    assert hits[0].fact_text == "最初のfact"


def test_resolve_maps_by_edge_uuid_for_triplet_mode():
    """triplet モードでは state の episode_uuids に edge uuid を格納しており、
    EntityEdge の episodes は空。edge.uuid 経由の帰属が無いと triplet 検索が
    恒久 0 ヒットになる（Task 14 で発見した実バグの回帰テスト）。"""
    u2f = {"edge-1": "F1", "ep-2": "F2"}
    edges = [
        SimpleNamespace(uuid="edge-1", fact="tripletエッジ", episodes=[], score=None),
        SimpleNamespace(uuid="edge-x", fact="episode由来", episodes=["ep-2"], score=None),
        SimpleNamespace(uuid="edge-y", fact="帰属不明", episodes=[], score=None),
    ]
    hits = _resolve_hits(edges, u2f, limit=5)
    assert [h.fact_id for h in hits] == ["F1", "F2"]


def make_settings(**kw) -> Settings:
    base = dict(tokens={"t1": "claude-code"}, admin_token="adm", _env_file=None)
    base.update(kw)
    return Settings(**base)


def test_build_llm_client_unknown_provider_raises():
    settings = make_settings(llm_provider="unknown")
    with pytest.raises(ValueError, match="unknown"):
        _build_llm_client(settings)


def test_build_llm_client_anthropic_selects_anthropic_client():
    settings = make_settings(llm_provider="anthropic", anthropic_model="claude-haiku-4-5-latest")
    client = _build_llm_client(settings)
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-haiku-4-5-latest"


def test_build_llm_client_openai_compatible_selects_openai_generic_client():
    settings = make_settings(
        llm_provider="openai-compatible",
        llm_model="gpt-oss:20b",
        llm_base_url="http://localhost:11434/v1",
        llm_api_key="ollama",
    )
    client = _build_llm_client(settings)
    assert isinstance(client, OpenAIGenericClient)
    assert client.model == "gpt-oss:20b"
    assert str(client.client.base_url).rstrip("/") == "http://localhost:11434/v1"


class _FakeDriver:
    def __init__(self, database: str = "default_db"):
        self.database = database

    def clone(self, database: str) -> "_FakeDriver":
        return _FakeDriver(database)


class _FakeGraphiti:
    """route の driver 切替を記録する偽 graphiti。

    search 中に await を挟み、操作開始時と終了時に見えていた driver が
    同一（= 別コルーチンの _route_group と interleave していない）ことを検証する。
    """

    def __init__(self):
        self.driver = _FakeDriver()
        self.clients = SimpleNamespace(driver=self.driver)
        self.observed: list[tuple[str, str]] = []

    async def search(self, query, group_ids, num_results):
        import asyncio

        start_db = self.driver.database
        assert self.clients.driver is self.driver
        await asyncio.sleep(0.01)  # 別コルーチンに制御を渡す
        end_db = self.driver.database
        self.observed.append((start_db, end_db))
        assert group_ids == [start_db]
        return []


async def test_search_route_is_atomic_under_concurrency():
    """並行 search で route→操作が interleave しないこと（_op_lock の検証）。

    _route_group は graphiti の共有状態（driver / clients.driver）を書き換えるため、
    ロックなしでは sleep 中に別コルーチンが別 group へ付け替え、start/end の driver
    が食い違う（= 別 group のグラフを読む）。
    """
    import asyncio

    settings = make_settings()
    from plk_memory.graphindex import GraphIndex

    g = GraphIndex(settings)
    g._graphiti = _FakeGraphiti()  # type: ignore[assignment]
    g._ready = True

    await asyncio.gather(
        g.search("q", ["group-a"], {}, limit=3),
        g.search("q", ["group-b"], {}, limit=3),
        g.search("q", ["group-a", "group-b"], {}, limit=3),
    )

    fake = g._graphiti
    assert len(fake.observed) == 4  # 1 + 1 + 2 groups
    for start_db, end_db in fake.observed:
        assert start_db == end_db, f"driver が操作中に付け替わった: {start_db} -> {end_db}"


async def test_triplet_upsert_bypasses_graphiti_llm_dedupe(monkeypatch):
    """Curated triplet ingest should store explicit relations without add_triplet LLM calls."""
    from plk_memory import graphindex
    from plk_memory.graphindex import GraphIndex

    settings = make_settings(ingest_mode="triplet")
    g = GraphIndex(settings)
    driver = _FakeDriver()

    async def add_triplet(*_args, **_kwargs):
        raise AssertionError("Graphiti.add_triplet should not be called for curated triplets")

    g._graphiti = SimpleNamespace(  # type: ignore[assignment]
        driver=driver,
        clients=SimpleNamespace(driver=driver),
        embedder=object(),
        add_triplet=add_triplet,
    )
    g._ready = True

    captured = {}

    async def fake_node_embeddings(_embedder, nodes):
        captured["nodes"] = nodes

    async def fake_edge_embeddings(_embedder, edges):
        captured["edges"] = edges

    async def fake_bulk(driver_arg, episodic_nodes, episodic_edges, entity_nodes, entity_edges, embedder):
        captured["driver"] = driver_arg
        captured["entity_nodes"] = entity_nodes
        captured["entity_edges"] = entity_edges

    monkeypatch.setattr(graphindex, "create_entity_node_embeddings", fake_node_embeddings)
    monkeypatch.setattr(graphindex, "create_entity_edge_embeddings", fake_edge_embeddings)
    monkeypatch.setattr(graphindex, "add_nodes_and_edges_bulk", fake_bulk)

    post = frontmatter.Post(
        "",
        id="01JZC2V7E8B3F4G5H6J7K8M9N9",
        namespace="plk.domain.agent",
        status="active",
        statement="不明点は本人に質問する前にまず一次情報を調べる",
        tags=[],
    )
    entry = await g.upsert_fact(post, old=None)

    assert len(entry.episode_uuids) == 1
    assert entry.episode_uuids == [captured["entity_edges"][0].uuid]
    assert captured["entity_edges"][0].fact == post["statement"]
    assert captured["entity_nodes"][1].name == "plk.domain.agent"
    assert captured["driver"].database == settings.main_group
