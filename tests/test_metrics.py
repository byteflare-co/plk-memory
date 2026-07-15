from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from plk_memory.metrics import build_metrics

JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 7, 15, 12, tzinfo=JST)


def usage_at(local: datetime, **values) -> dict:
    return {"tool": "plk_search", "ts": local.isoformat(), **values}


def test_week_boundaries_outcomes_legacy_and_missing_ts():
    usage = [
        usage_at(datetime(2026, 7, 13, 0, tzinfo=JST), hits=1, outcome="ok", reason="auto-guideline"),
        usage_at(datetime(2026, 7, 12, 23, 59, 59, tzinfo=JST), hits=0, outcome="ok"),
        usage_at(datetime(2026, 7, 6, 0, tzinfo=JST), hits=1),  # legacy outcome=ok
        usage_at(datetime(2026, 7, 14, 0, tzinfo=JST), hits=0, outcome="degraded"),
        {"tool": "plk_search", "hits": 1, "client": "no-ts", "latency_ms": 7},
    ]
    result = build_metrics(usage, [], [], now=NOW, tz=JST)
    current = result["search"]["weekly"][-1]
    previous = result["search"]["weekly"][-2]
    assert current == {
        "week": "2026-07-13", "in_progress": True, "auto": 1, "manual": 1,
        "returned": 1, "ok_total": 1, "failures": 1,
    }
    assert previous["week"] == "2026-07-06"
    assert previous["manual"] == 2 and previous["returned"] == 1
    assert result["search"]["total"] == 5
    assert result["search"]["clients"] == [{"client": "no-ts", "count": 1}]


def test_utc_timestamp_is_bucketed_in_jst_and_latency_uses_nearest_rank():
    usage = [
        {"tool": "plk_search", "ts": "2026-07-12T15:00:00+00:00", "hits": 1,
         "latency_ms": value, "outcome": "ok"}
        for value in [1, 2, 3, 4, 100]
    ]
    usage.append({"tool": "plk_search", "hits": 0, "latency_ms": 1000})
    result = build_metrics(usage, [], [], now=NOW, tz=JST)
    assert result["search"]["weekly"][-1]["manual"] == 5
    assert result["search"]["latency"]["last7d"] == {"p50": 3, "p95": 100, "n": 5}
    assert result["search"]["latency"]["all"] == {"p50": 3, "p95": 1000, "n": 6}


def test_zero_hits_group_all_then_sort_and_exclude_failures():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    usage = [
        usage_at(base + timedelta(minutes=i), query=f"q{i}", hits=0, outcome="ok", client="codex")
        for i in range(55)
    ]
    usage += [
        usage_at(base + timedelta(days=10), query="q0", hits=0, outcome="ok", client="claude"),
        usage_at(base + timedelta(days=20), query="infra", hits=0, outcome="error"),
        usage_at(base + timedelta(days=20), query="has-hit", hits=1, outcome="ok"),
        usage_at(base + timedelta(days=20), query="missing-hits", outcome="ok"),
        usage_at(base + timedelta(days=20), query="bool-hits", hits=False, outcome="ok"),
    ]
    rows = build_metrics(usage, [], [], now=NOW, tz=JST)["zero_hit"]
    assert len(rows) == 50 and rows[0]["query"] == "q0"
    assert rows[0]["count"] == 2 and rows[0]["clients"] == ["claude", "codex"]
    assert all(
        row["query"] not in {"infra", "has-hit", "missing-hits", "bool-hits"}
        for row in rows
    )


def test_corpus_datetime_types_and_unreturned():
    posts = [
        {"id": "01A", "status": "active", "namespace": "plk.domain.tax", "kind": "logic",
         "statement": "a", "created_at": datetime(2026, 7, 13, tzinfo=JST)},
        {"id": "01B", "status": "active", "namespace": "plk.domain.tax", "kind": "knowhow",
         "statement": "b", "created_at": "2026-07-12T15:00:00+00:00"},
        {"id": "01C", "status": "invalidated", "namespace": "plk.domain.dev", "kind": "logic",
         "statement": "c", "created_at": "invalid"},
    ]
    usage = [{"tool": "plk_search", "fact_ids": ["01A"]}]
    corpus = build_metrics(usage, posts, [], now=NOW, tz=JST)["corpus"]
    assert corpus["status"] == {"active": 2, "invalidated": 1}
    assert corpus["weekly_added"][-1]["count"] == 2
    assert corpus["unreturned"] == {
        "count": 1,
        "items": [{"id": "01B", "namespace": "plk.domain.tax", "statement": "b"}],
    }


def _four_completed_weeks(counts: list[int]) -> list[dict]:
    current = datetime(2026, 7, 13, tzinfo=JST)
    records = []
    for offset, count in enumerate(reversed(counts), start=1):
        week = current - timedelta(weeks=offset)
        records.append(usage_at(week, hits=0, outcome="ok"))  # marks the week observed
        records.extend(
            usage_at(week + timedelta(hours=i + 1), hits=1, outcome="ok", reason="auto-guideline")
            for i in range(count)
        )
    return records


def test_kill_criteria_three_verdicts_and_ignores_current_week():
    empty = build_metrics([], [], [], now=NOW, tz=JST)["kill_criteria"]
    assert empty["verdict"] == "inconclusive"
    breached = build_metrics(_four_completed_weeks([0, 1, 2, 0]), [], [], now=NOW, tz=JST)
    assert breached["kill_criteria"]["verdict"] == "proxy_breached"
    ok_usage = _four_completed_weeks([0, 1, 3, 0])
    ok_usage += [usage_at(datetime(2026, 7, 13, tzinfo=JST), hits=10,
                          outcome="ok", reason="auto-guideline")]
    ok = build_metrics(ok_usage, [], [], now=NOW, tz=JST)["kill_criteria"]
    assert ok["verdict"] == "proxy_ok"
    assert all(row["week"] != "2026-07-13" for row in ok["weeks"])


def test_eval_grouping_sorts_and_keeps_queries_hash():
    history = [
        {"runner": "graph", "ts": "2026-07-02T00:00:00Z", "hit5_rate": .8,
         "mrr": .7, "corpus_active": 2, "queries_hash": "sha256:b"},
        {"runner": "graph", "ts": "2026-07-01T00:00:00Z", "hit5_rate": .6,
         "mrr": .5, "corpus_active": 1, "queries_hash": "sha256:a"},
    ]
    rows = build_metrics([], [], history, now=NOW, tz=JST)["eval"]["graph"]
    assert [row["queries_hash"] for row in rows] == ["sha256:a", "sha256:b"]
