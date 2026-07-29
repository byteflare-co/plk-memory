import hashlib
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


def test_zero_hits_use_query_hash_when_plaintext_is_not_stored():
    query_hash = "a" * 64
    usage = [
        usage_at(
            NOW,
            query=None,
            query_hash=query_hash,
            hits=0,
            outcome="ok",
            client="codex",
        ),
        usage_at(
            NOW + timedelta(minutes=1),
            query=None,
            query_hash=query_hash,
            hits=0,
            outcome="ok",
            client="claude",
        ),
    ]

    rows = build_metrics(usage, [], [], now=NOW, tz=JST)["zero_hit"]

    assert rows == [
        {
            "query": "hash:aaaaaaaaaaaa…（平文非保存）",
            "count": 2,
            "last_ts": (NOW + timedelta(minutes=1)).isoformat(),
            "clients": ["claude", "codex"],
        }
    ]


def test_zero_hits_merge_plaintext_and_redacted_records_by_query_hash():
    query = "same missing query"
    query_hash = hashlib.sha256(query.encode()).hexdigest()
    usage = [
        usage_at(
            NOW,
            query=query,
            query_hash=query_hash,
            hits=0,
            outcome="ok",
            client="codex",
        ),
        usage_at(
            NOW + timedelta(minutes=1),
            query=None,
            query_hash=query_hash,
            hits=0,
            outcome="ok",
            client="claude",
        ),
    ]

    rows = build_metrics(usage, [], [], now=NOW, tz=JST)["zero_hit"]

    assert rows == [
        {
            "query": "same missing query",
            "count": 2,
            "last_ts": (NOW + timedelta(minutes=1)).isoformat(),
            "clients": ["claude", "codex"],
        }
    ]


def test_zero_hits_merge_legacy_plaintext_with_new_hashed_records():
    query = "legacy missing query"
    query_hash = hashlib.sha256(query.encode()).hexdigest()
    usage = [
        usage_at(
            NOW,
            query=query,
            hits=0,
            outcome="ok",
            client="legacy",
        ),
        usage_at(
            NOW + timedelta(minutes=1),
            query=query,
            query_hash=query_hash,
            hits=0,
            outcome="ok",
            client="codex",
        ),
        usage_at(
            NOW + timedelta(minutes=2),
            query=None,
            query_hash=query_hash,
            hits=0,
            outcome="ok",
            client="claude",
        ),
    ]

    rows = build_metrics(usage, [], [], now=NOW, tz=JST)["zero_hit"]

    assert rows == [
        {
            "query": "legacy missing query",
            "count": 3,
            "last_ts": (NOW + timedelta(minutes=2)).isoformat(),
            "clients": ["claude", "codex", "legacy"],
        }
    ]


def test_zero_hits_do_not_guess_legacy_bucket_for_ambiguous_preview():
    query_preview = "x" * 200
    usage = [
        usage_at(
            NOW,
            query=query_preview,
            hits=0,
            outcome="ok",
            client="legacy",
        ),
        usage_at(
            NOW + timedelta(minutes=1),
            query=query_preview,
            query_hash=hashlib.sha256((query_preview + " first").encode()).hexdigest(),
            hits=0,
            outcome="ok",
            client="codex",
        ),
        usage_at(
            NOW + timedelta(minutes=2),
            query=query_preview,
            query_hash=hashlib.sha256((query_preview + " second").encode()).hexdigest(),
            hits=0,
            outcome="ok",
            client="claude",
        ),
    ]

    rows = build_metrics(usage, [], [], now=NOW, tz=JST)["zero_hit"]

    assert [row["count"] for row in rows] == [1, 1, 1]


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
        marker_id = f"marker-{offset}"
        records.extend(
            [
                usage_at(
                    week,
                    hits=1,
                    outcome="ok",
                    reason="auto-guideline",
                    client="codex",
                    search_id=marker_id,
                    fact_ids=["F"],
                ),
                {
                    "tool": "plk_record_decision",
                    "ts": week.isoformat(),
                    "client": "codex",
                    "decision_id": f"marker-decision-{offset}",
                    "search_ids": [marker_id],
                    "used_fact_ids": [],
                    "effect": "none",
                    "no_use_reason": "irrelevant",
                    "outcome": "recorded",
                },
            ]
        )
        for index in range(count):
            search_id = f"strong-{offset}-{index}"
            timestamp = week + timedelta(hours=index + 1)
            records.extend(
                [
                    usage_at(
                        timestamp,
                        hits=1,
                        outcome="ok",
                        reason="auto-guideline",
                        client="codex",
                        search_id=search_id,
                        fact_ids=["F"],
                    ),
                    {
                        "tool": "plk_record_decision",
                        "ts": timestamp.isoformat(),
                        "client": "codex",
                        "decision_id": f"decision-{offset}-{index}",
                        "search_ids": [search_id],
                        "used_fact_ids": ["F"],
                        "effect": "changed_action",
                        "outcome": "recorded",
                    },
                ]
            )
    return records


def test_kill_criteria_three_verdicts_and_ignores_current_week():
    empty = build_metrics([], [], [], now=NOW, tz=JST)["kill_criteria"]
    assert empty["verdict"] == "inconclusive"
    breached = build_metrics(_four_completed_weeks([0, 1, 2, 0]), [], [], now=NOW, tz=JST)
    assert breached["kill_criteria"]["verdict"] == "observed_breached"
    ok_usage = _four_completed_weeks([0, 1, 3, 0])
    ok_usage += [usage_at(datetime(2026, 7, 13, tzinfo=JST), hits=10,
                          outcome="ok", reason="auto-guideline")]
    ok = build_metrics(ok_usage, [], [], now=NOW, tz=JST)["kill_criteria"]
    assert ok["verdict"] == "observed_ok"
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


def test_contribution_separates_unmeasured_adoption_and_strong_effects():
    usage = [
        usage_at(
            NOW,
            search_id="S1",
            client="codex",
            hits=2,
            outcome="ok",
            fact_ids=["F1", "F2"],
        ),
        usage_at(
            NOW,
            search_id="S2",
            client="codex",
            hits=1,
            outcome="ok",
            fact_ids=["F2"],
        ),
        usage_at(
            NOW,
            search_id="S3",
            client="claude",
            hits=1,
            outcome="ok",
            fact_ids=["F3"],
        ),
        usage_at(NOW, search_id="ZERO", client="codex", hits=0, outcome="ok"),
        {
            "tool": "plk_record_decision",
            "ts": NOW.isoformat(),
            "client": "codex",
            "decision_id": "D1",
            "search_ids": ["S1", "S2"],
            "used_fact_ids": ["F2"],
            "effect": "prevented_error",
            "outcome": "recorded",
        },
    ]
    contribution = build_metrics(usage, [], [], now=NOW, tz=JST)["contribution"]
    assert contribution["hit_searches"] == 3
    assert contribution["resolved_hit_searches"] == 2
    assert contribution["unresolved_hit_searches"] == 1
    assert contribution["measurement_rate"] == 2 / 3
    assert contribution["decisions"] == 1
    assert contribution["adopted_decisions"] == 1
    assert contribution["strong_contribution_decisions"] == 1
    assert contribution["effects"]["prevented_error"] == 1
    assert contribution["clients"][0] == {
        "client": "codex",
        "measurable": 2,
        "resolved": 2,
        "adopted": 1,
        "strong": 1,
        "measurement_rate": 1,
    }
    facts = {row["fact_id"]: row for row in contribution["facts"]}
    assert facts["F2"]["returned_searches"] == 2
    assert facts["F2"]["used_decisions"] == 1
    assert facts["F2"]["strong_decisions"] == 1


def test_contribution_ignores_invalid_or_cross_client_decision_records():
    usage = [
        usage_at(
            NOW,
            search_id="S1",
            client="codex",
            hits=1,
            outcome="ok",
            fact_ids=["F1"],
        ),
        {
            "tool": "plk_record_decision",
            "ts": NOW.isoformat(),
            "client": "claude",
            "decision_id": "FOREIGN",
            "search_ids": ["S1"],
            "used_fact_ids": ["F1"],
            "effect": "changed_action",
            "outcome": "recorded",
        },
        {
            "tool": "plk_record_decision",
            "ts": NOW.isoformat(),
            "client": "codex",
            "decision_id": "UNRETURNED",
            "search_ids": ["S1"],
            "used_fact_ids": ["OTHER"],
            "effect": "prevented_error",
            "outcome": "recorded",
        },
    ]
    contribution = build_metrics(usage, [], [], now=NOW, tz=JST)["contribution"]
    assert contribution["resolved_hit_searches"] == 0
    assert contribution["unresolved_hit_searches"] == 1
    assert contribution["decisions"] == 0
    assert contribution["strong_contribution_decisions"] == 0
