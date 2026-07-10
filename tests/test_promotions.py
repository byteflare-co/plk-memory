import pytest

from plk_memory.promotions import (
    PromotionError, PromotionRequest, PromotionState, PromotionStore, new_promotion, transition,
)


def make_pr(**over) -> PromotionRequest:
    base = dict(
        fact_id="01JZC2V7E8B3F4G5H6J7K8M9N0",
        from_namespace="plk.domain.tax",
        old_path="knowledge/domains/tax/x.md",
        new_path="knowledge/shared/x.md",
        branch="promote/01JZC2V7E8B3F4G5H6J7K8M9N0",
    )
    base.update(over)
    return new_promotion(**base)


def test_new_promotion_defaults():
    pr = make_pr()
    assert pr.state is PromotionState.proposed
    assert pr.to_namespace == "plk.shared"
    assert pr.created_at and pr.updated_at


def test_valid_transitions():
    pr = transition(make_pr(), PromotionState.applied)
    assert pr.state is PromotionState.applied


def test_invalid_transition_from_terminal():
    pr = transition(make_pr(), PromotionState.rejected)
    with pytest.raises(PromotionError):
        transition(pr, PromotionState.applied)


def test_store_roundtrip_and_queries(tmp_path):
    store = PromotionStore(tmp_path / "promotions.json")
    pr1 = make_pr()
    pr2 = make_pr(fact_id="01JZC2V7E8B3F4G5H6J7K8M9N2",
                  old_path="knowledge/domains/dev/y.md", new_path="knowledge/shared/y.md",
                  from_namespace="plk.domain.dev")
    store.upsert(pr1)
    store.upsert(pr2)
    assert set(store.load().keys()) == {pr1.id, pr2.id}
    assert [p.id for p in store.by_state(PromotionState.proposed)] == [pr1.id, pr2.id]
    store.upsert(transition(store.get(pr1.id), PromotionState.applied))
    assert [p.id for p in store.by_state(PromotionState.proposed)] == [pr2.id]
    assert store.by_fact(pr2.fact_id)[0].id == pr2.id


def test_store_delete_removes_record_and_missing_id_is_noop(tmp_path):
    store = PromotionStore(tmp_path / "promotions.json")
    pr = make_pr()
    store.upsert(pr)
    store.delete(pr.id)
    assert store.load() == {}
    store.delete("does-not-exist")  # no-op（例外を投げない）
    store.delete(pr.id)  # 二重 delete も no-op


def test_store_atomic_no_partial_file(tmp_path):
    path = tmp_path / "promotions.json"
    PromotionStore(path).upsert(make_pr())
    assert path.exists()
    assert not list(tmp_path.glob("*.tmp"))
