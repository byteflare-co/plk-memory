"""PromotionRequest 状態機械と永続化（設計書 §5・§9: API 内第一級リソース）。

GitHub PR はこの状態機械のバックエンド実装（github_promotion.py）に過ぎない。
状態機械を API 側に置くことで UI/バックエンド差し替え（Slack Block Kit 等）が
UI アダプタ交換で済む（設計書 §2 の決定）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel
from ulid import ULID


class PromotionState(str, Enum):
    proposed = "proposed"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"


_ALLOWED: dict[PromotionState, set[PromotionState]] = {
    PromotionState.proposed: {PromotionState.approved, PromotionState.applied, PromotionState.rejected},
    PromotionState.approved: {PromotionState.applied, PromotionState.rejected},
    PromotionState.applied: set(),
    PromotionState.rejected: set(),
}


class PromotionError(RuntimeError):
    pass


class PromotionRequest(BaseModel):
    id: str
    fact_id: str
    from_namespace: str
    to_namespace: str = "plk.shared"
    old_path: str
    new_path: str
    branch: str
    state: PromotionState = PromotionState.proposed
    pr_number: int | None = None
    pr_url: str | None = None
    reason: str | None = None
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_promotion(*, fact_id: str, from_namespace: str, old_path: str, new_path: str,
                  branch: str, reason: str | None = None) -> PromotionRequest:
    now = _now()
    return PromotionRequest(
        id=str(ULID()), fact_id=fact_id, from_namespace=from_namespace,
        old_path=old_path, new_path=new_path, branch=branch, reason=reason,
        created_at=now, updated_at=now,
    )


def transition(pr: PromotionRequest, new_state: PromotionState) -> PromotionRequest:
    if new_state not in _ALLOWED[pr.state]:
        raise PromotionError(f"不正な遷移: {pr.state.value} -> {new_state.value}")
    return pr.model_copy(update={"state": new_state, "updated_at": _now()})


class PromotionStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, PromotionRequest]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {k: PromotionRequest.model_validate(v) for k, v in raw.items()}

    def save(self, items: dict[str, PromotionRequest]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        payload = {k: v.model_dump() for k, v in items.items()}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def upsert(self, pr: PromotionRequest) -> None:
        items = self.load()
        items[pr.id] = pr
        self.save(items)

    def delete(self, promotion_id: str) -> None:
        """レコードを削除する（存在しない id は no-op）。create_pr 失敗時のロールバック用。"""
        items = self.load()
        if items.pop(promotion_id, None) is not None:
            self.save(items)

    def get(self, promotion_id: str) -> PromotionRequest:
        return self.load()[promotion_id]

    def by_state(self, state: PromotionState) -> list[PromotionRequest]:
        return [p for p in self.load().values() if p.state is state]

    def by_fact(self, fact_id: str) -> list[PromotionRequest]:
        return [p for p in self.load().values() if p.fact_id == fact_id]
