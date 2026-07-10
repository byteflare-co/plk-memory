import json

from plk_memory.usage_log import UsageLog


def test_appends_jsonl_and_truncates_query(tmp_path):
    log = UsageLog(tmp_path / "u.jsonl")
    log.log("claude-code", "plk_search", query="あ" * 500, hits=3, latency_ms=42,
            reason="auto-guideline", fact_ids=["01A", "01B"])
    log.log("codex", "plk_add")
    lines = (tmp_path / "u.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["client"] == "claude-code" and len(rec["query"]) == 200
    assert rec["reason"] == "auto-guideline" and "ts" in rec
    assert rec["fact_ids"] == ["01A", "01B"]
    assert json.loads(lines[1])["fact_ids"] is None
