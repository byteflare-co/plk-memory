"""Metrics and curation JSONL readers with boundary validation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_USAGE_TYPES: dict[str, type | tuple[type, ...]] = {
    "ts": str,
    "client": str,
    "tool": str,
    "query": str,
    "hits": int,
    "latency_ms": int,
    "reason": str,
    "fact_id": str,
    "search_id": str,
    "outcome": str,
}

_EVAL_TYPES: dict[str, type | tuple[type, ...]] = {
    "ts": str,
    "run_id": str,
    "runner": str,
    "queries": int,
    "queries_hash": str,
    "hit5": int,
    "hit5_rate": (int, float),
    "mrr": (int, float),
    "corpus_active": int,
    "corpus_total": int,
    "corpus_revision": str,
    "corpus_scope": str,
    "embed_model": str,
    "llm_model": str,
    "graph_mode": str,
}


def parse_ts(value: object) -> datetime | None:
    """Parse an ISO timestamp, treating a naive value as UTC."""
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _read_jsonl(path: Path, field_types: dict[str, Any]) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        record = dict(value)
        for field, expected in field_types.items():
            current = record.get(field)
            if current is not None and (
                not isinstance(current, expected)
                or (isinstance(current, bool) and expected in {int, (int, float)})
            ):
                record.pop(field, None)
        fact_ids = record.get("fact_ids")
        if fact_ids is not None and (
            not isinstance(fact_ids, list)
            or not all(isinstance(item, str) for item in fact_ids)
        ):
            record.pop("fact_ids", None)
        records.append(record)
    return records


def read_usage(path: Path) -> list[dict]:
    return _read_jsonl(path, _USAGE_TYPES)


def read_eval_history(path: Path) -> list[dict]:
    return _read_jsonl(path, _EVAL_TYPES)


def referenced_fact_ids(usage: list[dict]) -> set[str]:
    referenced = {
        fact_id
        for record in usage
        if isinstance((fact_id := record.get("fact_id")), str)
    }
    for record in usage:
        fact_ids = record.get("fact_ids")
        if isinstance(fact_ids, list):
            referenced.update(item for item in fact_ids if isinstance(item, str))
    return referenced
