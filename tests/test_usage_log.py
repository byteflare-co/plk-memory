import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from plk_memory.telemetry import (
    DecisionCommand,
    FactReference,
    TelemetryConflict,
    TelemetryError,
)
from plk_memory.usage_log import UsageLog


def test_appends_jsonl_and_truncates_query(tmp_path):
    log = UsageLog(tmp_path / "u.jsonl")
    log.log("claude-code", "plk_search", query="あ" * 500, hits=3, latency_ms=42,
            reason="auto-guideline", fact_ids=["01A", "01B"],
            search_id="01SEARCH", outcome="ok")
    log.log("codex", "plk_add")
    lines = (tmp_path / "u.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["client"] == "claude-code" and len(rec["query"]) == 200
    assert rec["reason"] == "auto-guideline" and "ts" in rec
    assert rec["fact_ids"] == ["01A", "01B"]
    assert rec["search_id"] == "01SEARCH" and rec["outcome"] == "ok"
    assert len(rec["query_hash"]) == 64
    assert os.stat(tmp_path / "u.jsonl").st_mode & 0o777 == 0o600
    assert json.loads(lines[1])["fact_ids"] is None


async def test_records_one_decision_for_multiple_searches_idempotently(tmp_path):
    log = UsageLog(tmp_path / "u.jsonl")
    await log.record_search(
        client="codex",
        search_id="S1",
        query="query one",
        hits=1,
        latency_ms=5,
        reason="auto-guideline",
        fact_refs=[FactReference(fact_id="F1", content_hash="a" * 64)],
        outcome="ok",
    )
    await log.record_search(
        client="codex",
        search_id="S2",
        query="query two",
        hits=1,
        latency_ms=7,
        reason="auto-guideline",
        fact_refs=[FactReference(fact_id="F2", content_hash="b" * 64)],
        outcome="ok",
    )
    command = DecisionCommand(
        decision_id="D1",
        search_ids=("S1", "S2"),
        used_fact_ids=("F2",),
        effect="changed_action",
    )

    first = await log.record_decision(client="codex", command=command)
    replay = await log.record_decision(client="codex", command=command)

    assert first["replayed"] is False
    assert replay["replayed"] is True
    decision = (await log.list_usage())[-1]
    assert decision["search_ids"] == ["S1", "S2"]
    assert decision["used_fact_refs"] == [
        {"fact_id": "F2", "content_hash": "b" * 64}
    ]

    with pytest.raises(TelemetryConflict):
        await log.record_decision(
            client="codex",
            command=command.model_copy(update={"effect": "prevented_error"}),
        )


async def test_rejects_foreign_search_unreturned_fact_and_double_resolution(tmp_path):
    log = UsageLog(tmp_path / "u.jsonl")
    await log.record_search(
        client="claude",
        search_id="S1",
        query="query",
        hits=1,
        latency_ms=1,
        reason=None,
        fact_refs=[FactReference(fact_id="F1", content_hash="c" * 64)],
        outcome="ok",
    )
    with pytest.raises(TelemetryError, match="another client"):
        await log.record_decision(
            client="codex",
            command=DecisionCommand(
                decision_id="D1",
                search_ids=("S1",),
                used_fact_ids=("F1",),
                effect="confirmed",
            ),
        )
    with pytest.raises(TelemetryError, match="were not returned"):
        await log.record_decision(
            client="claude",
            command=DecisionCommand(
                decision_id="D2",
                search_ids=("S1",),
                used_fact_ids=("OTHER",),
                effect="confirmed",
            ),
        )
    await log.record_decision(
        client="claude",
        command=DecisionCommand(
            decision_id="D3",
            search_ids=("S1",),
            used_fact_ids=(),
            effect="none",
            no_use_reason="irrelevant",
        ),
    )
    with pytest.raises(TelemetryConflict, match="already resolved"):
        await log.record_decision(
            client="claude",
            command=DecisionCommand(
                decision_id="D4",
                search_ids=("S1",),
                used_fact_ids=("F1",),
                effect="confirmed",
            ),
        )


def test_decision_contract_requires_effect_consistent_fact_usage():
    with pytest.raises(ValidationError, match="requires no_use_reason"):
        DecisionCommand(
            decision_id="D1",
            search_ids=("S1",),
            used_fact_ids=(),
            effect="none",
        )
    with pytest.raises(ValidationError, match="requires used_fact_ids"):
        DecisionCommand(
            decision_id="D2",
            search_ids=("S1",),
            used_fact_ids=(),
            effect="changed_action",
        )
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        DecisionCommand(
            decision_id="D3",
            search_ids=("S1", "S1"),
            used_fact_ids=("F1",),
            effect="confirmed",
        )


async def test_zero_hit_search_needs_no_decision_record(tmp_path):
    log = UsageLog(tmp_path / "u.jsonl")
    await log.record_search(
        client="codex",
        search_id="ZERO",
        query="missing",
        hits=0,
        latency_ms=1,
        reason="auto-guideline",
        fact_refs=[],
        outcome="ok",
    )
    with pytest.raises(TelemetryError, match="did not return facts"):
        await log.record_decision(
            client="codex",
            command=DecisionCommand(
                decision_id="D0",
                search_ids=("ZERO",),
                used_fact_ids=(),
                effect="none",
                no_use_reason="irrelevant",
            ),
        )


async def test_redacts_expired_query_but_keeps_hash(tmp_path):
    path = tmp_path / "u.jsonl"
    old = datetime.now(timezone.utc) - timedelta(days=31)
    path.write_text(
        json.dumps(
            {
                "ts": old.isoformat(),
                "client": "codex",
                "tool": "plk_search",
                "query": "private query",
                "query_hash": "d" * 64,
                "hits": 0,
                "search_id": "S1",
                "outcome": "ok",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    records = await UsageLog(path, raw_query_retention_days=30).list_usage()
    assert records[0]["query"] is None
    assert records[0]["query_hash"] == "d" * 64
    assert "private query" not in path.read_text(encoding="utf-8")


async def test_zero_day_retention_never_persists_plaintext(tmp_path):
    path = tmp_path / "u.jsonl"
    log = UsageLog(path, raw_query_retention_days=0)

    await log.record_search(
        client="codex",
        search_id="S1",
        query="private query",
        hits=0,
        latency_ms=1,
        reason="auto-guideline",
        fact_refs=[],
        outcome="ok",
    )

    records = await log.list_usage()
    assert records[0]["query"] is None
    assert len(records[0]["query_hash"]) == 64
    assert "private query" not in path.read_text(encoding="utf-8")
    await log.close()


def test_search_append_does_not_scan_existing_usage_log(tmp_path, monkeypatch):
    path = tmp_path / "u.jsonl"
    log = UsageLog(path)
    calls = 0
    original = log._redact_expired_queries

    def counted_redaction():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(log, "_redact_expired_queries", counted_redaction)
    log.log("codex", "plk_search", query="one", search_id="S1", outcome="ok")
    log.log("codex", "plk_search", query="two", search_id="S2", outcome="ok")

    assert calls == 0


async def test_active_log_redacts_last_query_without_later_access(tmp_path):
    path = tmp_path / "u.jsonl"
    log = UsageLog(path, raw_query_retention_days=0.000001)
    await log.record_search(
        client="codex",
        search_id="S1",
        query="last private query",
        hits=1,
        latency_ms=1,
        reason="auto-guideline",
        fact_refs=[FactReference(fact_id="F1")],
        outcome="ok",
    )

    await asyncio.sleep(0.2)

    assert "last private query" not in path.read_text(encoding="utf-8")
    await log.close()
