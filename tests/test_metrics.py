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


def test_zero_hits_merge_exact_200_character_queries_when_hash_matches():
    query = "x" * 200
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
    ]

    rows = build_metrics(usage, [], [], now=NOW, tz=JST)["zero_hit"]

    assert len(rows) == 1
    assert rows[0]["count"] == 2
    assert rows[0]["clients"] == ["codex", "legacy"]


def test_zero_hits_keep_legacy_preview_separate_when_exact_and_long_hashes_exist():
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
            query_hash=hashlib.sha256(query_preview.encode()).hexdigest(),
            hits=0,
            outcome="ok",
            client="exact",
        ),
        usage_at(
            NOW + timedelta(minutes=2),
            query=query_preview,
            query_hash=hashlib.sha256((query_preview + " suffix").encode()).hexdigest(),
            hits=0,
            outcome="ok",
            client="longer",
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
    assert ok["verdict"] == "observed_breached"
    assert all(row["week"] != "2026-07-13" for row in ok["weeks"])
    sustained = build_metrics(
        _four_completed_weeks([3, 3, 3, 3]), [], [], now=NOW, tz=JST
    )
    assert sustained["kill_criteria"]["verdict"] == "observed_ok"


def test_decision_value_requires_four_complete_on_target_weeks():
    observation_start = datetime(2026, 6, 1, tzinfo=JST)
    sustained = build_metrics(
        _four_completed_weeks([3, 3, 3, 3]),
        [],
        [],
        now=NOW,
        tz=JST,
        observation_started_at=observation_start,
    )["decision_value"]
    assert sustained["status"] == "observed_sustained"
    assert sustained["four_week"] == {
        "required_weeks": 4,
        "evaluable_weeks": 4,
        "target_met_weeks": 4,
        "weekly_target": 3,
    }

    below = build_metrics(
        _four_completed_weeks([0, 1, 3, 0]),
        [],
        [],
        now=NOW,
        tz=JST,
        observation_started_at=observation_start,
    )["decision_value"]
    assert below["status"] == "target_not_met"
    assert below["primary_reason_code"] == "weekly_target_missed"
    assert below["four_week"]["target_met_weeks"] == 1


def test_decision_value_treats_measurement_gap_as_insufficient_not_zero():
    usage = _four_completed_weeks([3, 3, 3, 3])
    usage = [
        record for record in usage
        if record.get("decision_id") != "marker-decision-1"
    ]
    value = build_metrics(
        usage,
        [],
        [],
        now=NOW,
        tz=JST,
        observation_started_at=datetime(2026, 6, 1, tzinfo=JST),
    )["decision_value"]
    assert value["status"] == "insufficient_data"
    assert value["primary_reason_code"] == "measurement_gap"
    assert value["four_week"]["evaluable_weeks"] == 3
    affected = next(row for row in value["weekly"] if not row["evaluable"])
    assert "measurement_gap" in affected["unevaluable_reasons"]
    assert affected["strong_decisions"] == 3


def test_decision_value_attributes_strong_effect_only_to_used_auto_fact_cohort():
    week = datetime(2026, 6, 29, 9, tzinfo=JST)
    usage = _four_completed_weeks([0, 0, 0, 0])
    usage.extend([
        usage_at(
            week,
            search_id="AUTO-USED",
            client="codex",
            hits=1,
            outcome="ok",
            reason="auto-guideline",
            fact_ids=["FA"],
        ),
        usage_at(
            week + timedelta(days=7),
            search_id="AUTO-UNUSED-LATER",
            client="codex",
            hits=1,
            outcome="ok",
            reason="auto-guideline",
            fact_ids=["FB"],
        ),
        {
            "tool": "plk_record_decision",
            "ts": (week + timedelta(days=7, minutes=1)).isoformat(),
            "client": "codex",
            "decision_id": "COHORT",
            "search_ids": ["AUTO-USED", "AUTO-UNUSED-LATER"],
            "used_fact_ids": ["FA"],
            "effect": "changed_action",
            "outcome": "recorded",
        },
    ])
    value = build_metrics(
        usage,
        [],
        [],
        now=NOW,
        tz=JST,
        observation_started_at=datetime(2026, 6, 1, tzinfo=JST),
    )["decision_value"]
    rows = {row["week"]: row for row in value["weekly"]}
    assert rows["2026-06-29"]["changed_action_decisions"] == 1
    assert rows["2026-07-06"]["changed_action_decisions"] == 0


def test_decision_value_fails_closed_on_conflicting_duplicate_ids():
    usage = _four_completed_weeks([3, 3, 3, 3])
    original = next(record for record in usage if record.get("search_id") == "marker-1")
    usage.append({**original, "hits": 2})
    value = build_metrics(
        usage,
        [],
        [],
        now=NOW,
        tz=JST,
        observation_started_at=datetime(2026, 6, 1, tzinfo=JST),
    )["decision_value"]
    assert value["status"] == "insufficient_data"
    assert value["primary_reason_code"] == "invalid_records"
    assert value["data_quality"]["global_blockers"]["duplicate_search_id"] == 1


def test_decision_value_distinguishes_pre_observation_from_no_search_week():
    value = build_metrics(
        [],
        [],
        [],
        now=NOW,
        tz=JST,
        observation_started_at=datetime(2026, 7, 1, 12, tzinfo=JST),
    )["decision_value"]
    assert value["status"] == "insufficient_data"
    assert value["primary_reason_code"] == "no_eligible_searches"
    assert value["next_action"]["code"] == "verify_auto_search_flow"
    assert any(
        "pre_observation" in row["unevaluable_reasons"]
        for row in value["weekly"]
    )


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


def test_operational_readiness_separates_passes_from_missing_value_evidence():
    usage = []
    for index in range(10):
        search_id = f"S{index}"
        ts = NOW - timedelta(hours=index)
        usage.extend(
            [
                usage_at(
                    ts,
                    search_id=search_id,
                    client="codex",
                    hits=1,
                    outcome="ok",
                    latency_ms=500,
                    fact_ids=["F"],
                    reason="auto-guideline",
                ),
                {
                    "tool": "plk_record_decision",
                    "ts": ts.isoformat(),
                    "client": "codex",
                    "decision_id": f"D{index}",
                    "search_ids": [search_id],
                    "used_fact_ids": ["F"],
                    "effect": "confirmed",
                    "outcome": "recorded",
                },
            ]
        )
    history = [
        {
            "ts": NOW.isoformat(),
            "run_id": "R1",
            "runner": "embed",
            "hit5_rate": 0.9,
            "mrr": 0.8,
            "queries_hash": "sha256:a",
        },
        {
            "ts": NOW.isoformat(),
            "run_id": "R1",
            "runner": "graph(triplet)",
            "hit5_rate": 0.95,
            "mrr": 0.85,
            "queries_hash": "sha256:a",
        },
    ]

    readiness = build_metrics(usage, [], history, now=NOW, tz=JST)[
        "operational_readiness"
    ]
    gates = {item["id"]: item for item in readiness["gates"]}

    assert readiness["status"] == "insufficient_data"
    assert readiness["passed_gates"] == 4
    assert readiness["total_gates"] == 5
    assert gates["measurement"]["status"] == "pass"
    assert gates["client_coverage"]["status"] == "pass"
    assert gates["reliability"]["status"] == "pass"
    assert gates["retrieval_eval"]["status"] == "pass"
    assert gates["observed_value"]["status"] == "insufficient"


def test_operational_readiness_fails_closed_on_low_measurement_and_stale_eval():
    usage = [
        usage_at(
            NOW - timedelta(hours=index),
            search_id=f"S{index}",
            client="codex",
            hits=1,
            outcome="ok",
            latency_ms=6_000,
            fact_ids=["F"],
        )
        for index in range(10)
    ]
    history = [
        {
            "ts": (NOW - timedelta(days=31)).isoformat(),
            "run_id": "R1",
            "runner": "embed",
            "hit5_rate": 1.0,
            "mrr": 1.0,
        },
        {
            "ts": (NOW - timedelta(days=31)).isoformat(),
            "run_id": "R1",
            "runner": "graph(triplet)",
            "hit5_rate": 1.0,
            "mrr": 1.0,
        },
    ]

    readiness = build_metrics(usage, [], history, now=NOW, tz=JST)[
        "operational_readiness"
    ]
    gates = {item["id"]: item for item in readiness["gates"]}

    assert readiness["status"] == "needs_work"
    assert gates["measurement"]["status"] == "fail"
    assert gates["client_coverage"]["status"] == "fail"
    assert gates["reliability"]["status"] == "fail"
    assert gates["retrieval_eval"]["status"] == "stale"
