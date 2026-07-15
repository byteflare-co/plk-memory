import json
from datetime import timezone

from plk_memory.curation import _parse_ts, read_usage
from plk_memory.usage_records import parse_ts, read_eval_history, referenced_fact_ids


def test_read_usage_skips_non_objects_and_removes_invalid_fields(tmp_path):
    path = tmp_path / "usage.jsonl"
    lines = [
        "null",
        "[]",
        '"text"',
        "not-json",
        json.dumps({
            "tool": "plk_search",
            "hits": "two",
            "latency_ms": True,
            "fact_ids": ["01A", 2],
            "client": ["codex"],
            "unknown": {"kept": True},
        }),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    assert read_usage(path) == [{"tool": "plk_search", "unknown": {"kept": True}}]


def test_read_eval_history_validates_object_fields(tmp_path):
    path = tmp_path / "eval.jsonl"
    path.write_text(
        '{"runner":"graph","hit5_rate":"bad","mrr":0.5}\n[]\n',
        encoding="utf-8",
    )
    assert read_eval_history(path) == [{"runner": "graph", "mrr": 0.5}]


def test_parse_ts_and_referenced_ids_match_curation_contract():
    naive = parse_ts("2026-07-15T10:00:00")
    assert naive is not None and naive.tzinfo == timezone.utc
    assert _parse_ts("2026-07-15T10:00:00") == naive
    assert parse_ts(123) is None and parse_ts("invalid") is None
    usage = [
        {"tool": "plk_history", "fact_id": "01A"},
        {"tool": "plk_search", "fact_ids": ["01B", "01C"]},
        {"fact_ids": ["01B", 123]},
    ]
    assert referenced_fact_ids(usage) == {"01A", "01B", "01C"}


def test_missing_or_unreadable_files_are_empty(tmp_path):
    assert read_usage(tmp_path / "missing.jsonl") == []
    invalid_utf8 = tmp_path / "invalid.jsonl"
    invalid_utf8.write_bytes(b'\xff\xfe{"tool":"plk_search"}\n')
    assert read_usage(invalid_utf8) == []
    assert read_eval_history(invalid_utf8) == []
