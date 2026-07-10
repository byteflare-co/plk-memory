from plk_memory.state import FactIndexEntry, StateStore, SyncState


def test_roundtrip(tmp_path):
    store = StateStore(tmp_path / "state.json")
    state = SyncState(
        last_ingested_commit="abc1234",
        facts={"01X": FactIndexEntry(episode_uuids=["u1"], content_hash="h" * 16, group_id="plk.main")},
        dead_letters={"knowledge/domains/tax/x.md": "boom"},
    )
    store.save(state)
    loaded = store.load()
    assert loaded == state


def test_load_missing_returns_empty(tmp_path):
    state = StateStore(tmp_path / "none.json").load()
    assert state.last_ingested_commit is None
    assert state.facts == {} and state.dead_letters == {}


def test_save_is_atomic_no_partial_file(tmp_path):
    # tmp ファイル経由の os.replace で書く（クラッシュで壊れた JSON を残さない）
    path = tmp_path / "state.json"
    store = StateStore(path)
    store.save(SyncState())
    assert path.exists()
    assert not list(tmp_path.glob("*.tmp"))
