"""Git backend search and decision telemetry stored as private JSONL."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from plk_memory.telemetry import (
    DecisionCommand,
    FactReference,
    TelemetryConflict,
    TelemetryError,
)
from plk_memory.usage_records import read_usage


class UsageLog:
    def __init__(self, path: Path, *, raw_query_retention_days: int = 30):
        self.path = path
        self.raw_query_retention_days = raw_query_retention_days
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.chmod(0o600)

    def log(self, client: str | None, tool: str, *, query: str | None = None,
            hits: int | None = None, latency_ms: int | None = None,
            reason: str | None = None, fact_ids: list[str] | None = None,
            fact_refs: list[dict] | None = None,
            search_id: str | None = None, outcome: str | None = None) -> None:
        query_preview = (query or "")[:200] or None
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "client": client, "tool": tool,
            "query": query_preview,
            "query_hash": hashlib.sha256((query or "").encode()).hexdigest()
            if query
            else None,
            "hits": hits, "latency_ms": latency_ms, "reason": reason,
            "fact_ids": fact_ids or None,
            "fact_refs": fact_refs or None,
            "search_id": search_id, "outcome": outcome,
        }
        with self._lock:
            self._redact_expired_queries()
            self._append(rec)

    async def record_search(
        self,
        *,
        client: str,
        search_id: str,
        query: str,
        hits: int,
        latency_ms: int,
        reason: str | None,
        fact_refs: list[FactReference],
        outcome: str,
    ) -> None:
        self.log(
            client,
            "plk_search",
            query=query,
            hits=hits,
            latency_ms=latency_ms,
            reason=reason,
            fact_ids=[ref.fact_id for ref in fact_refs],
            fact_refs=[ref.model_dump(mode="json", exclude_none=True) for ref in fact_refs],
            search_id=search_id,
            outcome=outcome,
        )

    async def record_decision(
        self,
        *,
        client: str,
        command: DecisionCommand,
    ) -> dict:
        with self._lock:
            records = read_usage(self.path)
            request_hash = command.request_hash()
            existing = next(
                (
                    record
                    for record in records
                    if record.get("tool") == "plk_record_decision"
                    and record.get("decision_id") == command.decision_id
                ),
                None,
            )
            if existing is not None:
                if (
                    existing.get("request_hash") != request_hash
                    or existing.get("client") != client
                ):
                    raise TelemetryConflict(
                        "decision_id is already used for a different decision"
                    )
                return {
                    "recorded": True,
                    "replayed": True,
                    "decision_id": command.decision_id,
                }

            searches = {
                record.get("search_id"): record
                for record in records
                if record.get("tool") == "plk_search"
                and isinstance(record.get("search_id"), str)
            }
            missing = [item for item in command.search_ids if item not in searches]
            if missing:
                raise TelemetryError(f"unknown search_ids: {', '.join(missing)}")
            foreign = [
                item
                for item in command.search_ids
                if searches[item].get("client") != client
            ]
            if foreign:
                raise TelemetryError(
                    f"search_ids belong to another client: {', '.join(foreign)}"
                )
            no_hits = [
                item
                for item in command.search_ids
                if searches[item].get("outcome") != "ok"
                or not isinstance(searches[item].get("hits"), int)
                or searches[item].get("hits", 0) <= 0
            ]
            if no_hits:
                raise TelemetryError(
                    "search_ids did not return facts: " + ", ".join(no_hits)
                )
            resolved = {
                search_id
                for record in records
                if record.get("tool") == "plk_record_decision"
                for search_id in record.get("search_ids", [])
                if isinstance(search_id, str)
            }
            duplicate = [item for item in command.search_ids if item in resolved]
            if duplicate:
                raise TelemetryConflict(
                    f"search_ids are already resolved: {', '.join(duplicate)}"
                )
            returned = {
                fact_id
                for search_id in command.search_ids
                for fact_id in searches[search_id].get("fact_ids", [])
                if isinstance(fact_id, str)
            }
            invalid = [item for item in command.used_fact_ids if item not in returned]
            if invalid:
                raise TelemetryError(
                    f"used_fact_ids were not returned by these searches: {', '.join(invalid)}"
                )
            refs_by_id = {
                ref.get("fact_id"): ref
                for search_id in command.search_ids
                for ref in searches[search_id].get("fact_refs", [])
                if isinstance(ref, dict) and isinstance(ref.get("fact_id"), str)
            }
            rec = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "client": client,
                "tool": "plk_record_decision",
                **command.model_dump(mode="json"),
                "used_fact_refs": [
                    refs_by_id.get(fact_id, {"fact_id": fact_id})
                    for fact_id in command.used_fact_ids
                ],
                "request_hash": request_hash,
                "outcome": "recorded",
            }
            self._append(rec)
        return {
            "recorded": True,
            "replayed": False,
            "decision_id": command.decision_id,
        }

    async def list_usage(self) -> list[dict]:
        with self._lock:
            self._redact_expired_queries()
            return read_usage(self.path)

    def _append(self, record: dict) -> None:
        descriptor = os.open(
            self.path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(
                descriptor,
                (json.dumps(record, ensure_ascii=False) + "\n").encode(),
            )
        finally:
            os.close(descriptor)
        self.path.chmod(0o600)

    def _redact_expired_queries(self) -> None:
        if not self.path.exists():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=self.raw_query_retention_days
        )
        changed = False
        output: list[str] = []
        for line in lines:
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    output.append(line)
                    continue
                timestamp = datetime.fromisoformat(record.get("ts", ""))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
            except (json.JSONDecodeError, TypeError, ValueError):
                output.append(line)
                continue
            if (
                record.get("tool") == "plk_search"
                and record.get("query") is not None
                and timestamp < cutoff
            ):
                record["query"] = None
                changed = True
            output.append(json.dumps(record, ensure_ascii=False))
        if not changed:
            return
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, self.path)
