"""利用ログ（JSONL。本文は記録しない — 設計書 §7/§9）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class UsageLog:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, client: str | None, tool: str, *, query: str | None = None,
            hits: int | None = None, latency_ms: int | None = None,
            reason: str | None = None, fact_ids: list[str] | None = None,
            search_id: str | None = None, outcome: str | None = None) -> None:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "client": client, "tool": tool,
            "query": (query or "")[:200] or None,
            "hits": hits, "latency_ms": latency_ms, "reason": reason,
            "fact_ids": fact_ids or None,
            "search_id": search_id, "outcome": outcome,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
