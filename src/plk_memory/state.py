"""同期状態の永続化（設計書 §6-3: last_ingested_commit・fact→episode 対応・dead letters）。"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class FactIndexEntry(BaseModel):
    episode_uuids: list[str] = []
    content_hash: str = ""
    group_id: str = ""


class SyncState(BaseModel):
    last_ingested_commit: str | None = None
    facts: dict[str, FactIndexEntry] = {}
    dead_letters: dict[str, str] = {}


class StateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> SyncState:
        if not self.path.exists():
            return SyncState()
        return SyncState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, state: SyncState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(state.model_dump_json(indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
