import asyncio

import pytest

from plk_memory.facts import FactService
from plk_memory.state import StateStore
from plk_memory.sync import SyncEngine
from tests.conftest import make_store
from tests.fakes import FakeGraphIndex
from tests.gitsync_helpers import (
    delete_file,
    modify_statement,
    push,
    rename_with_namespace,
    set_invalidated,
)


@pytest.fixture
def engine(remote, tmp_path):
    origin, seed = remote
    store = make_store(tmp_path, origin)
    facts = FactService(store, store.settings)
    graph = FakeGraphIndex()
    state = StateStore(tmp_path / "state.json")
    return SyncEngine(store, facts, graph, state, store.settings), seed, graph


async def test_initial_sync_ingests_all(engine, write_valid_fact):
    eng, seed, graph = engine
    # seed 側で 2 ファクトを push（人間の編集を模倣）
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    write_valid_fact(seed, "knowledge/domains/dev/f2.md",
                      id="01JZC2V7E8B3F4G5H6J7K8M9N2", namespace="plk.domain.dev")
    push(seed)
    result = await eng.sync()
    assert result["upserted"] == 2
    assert len(graph.docs) == 2


async def test_incremental_add_modify_delete(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    # modify + add + delete を 1 push で
    modify_statement(seed, "knowledge/domains/tax/f1.md", "修正された知見の要旨で二十字以上ある")
    write_valid_fact(seed, "knowledge/domains/dev/f3.md",
                      id="01JZC2V7E8B3F4G5H6J7K8M9N3", namespace="plk.domain.dev")
    push(seed)
    r = await eng.sync()
    assert r["upserted"] == 2 and r["deleted"] == 0
    delete_file(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    r = await eng.sync()
    assert r["deleted"] == 1
    assert "01JZC2V7E8B3F4G5H6J7K8M9N0" not in graph.docs


async def test_rename_promotion_delete_and_readd(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    rename_with_namespace(seed, "knowledge/domains/tax/f1.md", "knowledge/shared/f1.md", "plk.shared")
    push(seed)
    r = await eng.sync()
    assert r["upserted"] == 1  # 新側
    assert len(graph.docs) == 1


async def test_dead_letter_recorded_and_recovered(engine, write_valid_fact):
    eng, seed, graph = engine
    graph.fail_for = {"01JZC2V7E8B3F4G5H6J7K8M9N0"}
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    r = await eng.sync()
    assert r["dead_letters"]
    graph.fail_for = set()
    r2 = await eng.sync()  # 再同期で回収（level-triggered）
    assert not r2["dead_letters"]
    assert len(graph.docs) == 1


async def test_invalidated_fact_removed_from_index(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    set_invalidated(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    assert len(graph.docs) == 0


async def test_reindex_clears_and_rebuilds(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    r = await eng.reindex()
    assert r["upserted"] == 1 and len(graph.docs) == 1
    assert eng.maintenance is False


async def test_concurrent_sync_calls_are_serialized(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    graph.upsert_delay = 0.05
    r1, r2 = await asyncio.gather(eng.sync(), eng.sync())
    # 2 回目の sync はロック解放後に HEAD が既に一致しているため no-op になる。
    assert graph.upsert_calls == 1
    assert r1["upserted"] + r2["upserted"] == 1


async def test_degraded_when_graph_not_ready(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    graph.ready = False
    r = await eng.sync()
    assert r["upserted"] == 0
    assert r["dead_letters"] == {}
    assert r["degraded"] is not None
    assert eng.degraded is not None

    graph.ready = True
    r2 = await eng.sync()
    assert r2["upserted"] == 1
    assert r2["degraded"] is None
    assert len(graph.docs) == 1


async def test_begin_reindex_is_atomic_check_and_set(engine):
    eng, seed, graph = engine
    assert eng.begin_reindex() is True      # 1 件目は取得成功
    assert eng.maintenance is True
    assert eng.begin_reindex() is False     # 2 件目は実行中を検知して False
    eng.end_reindex()
    assert eng.maintenance is False
    assert eng.begin_reindex() is True       # 解放後は再取得できる
    eng.end_reindex()


async def test_reindex_rejects_double_start(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    eng.maintenance = True  # 別 reindex 実行中を模す
    from plk_memory.sync import ReindexInProgress
    with pytest.raises(ReindexInProgress):
        await eng.reindex()
    eng.maintenance = False
