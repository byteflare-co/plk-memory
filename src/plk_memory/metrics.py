"""Pure metric aggregation for the local PLK dashboard."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from plk_memory.usage_records import parse_ts, referenced_fact_ids

WEEKS = 12
KILL_WEEKS = 4
KILL_THRESHOLD_WEEKLY_HITS = 3
READINESS_WINDOW_DAYS = 7
READINESS_MIN_SEARCHES = 10
READINESS_MEASUREMENT_TARGET = 0.90
READINESS_ACTIVE_CLIENT_MIN_SEARCHES = 3
READINESS_FAILURE_RATE_TARGET = 0.01
READINESS_LATENCY_P95_TARGET_MS = 5_000
READINESS_EVAL_MAX_AGE_DAYS = 30
DECISION_VALUE_OBSERVATION_STARTED_AT = datetime(
    2026, 7, 27, tzinfo=timezone(timedelta(hours=9))
)
DECISION_VALUE_FUTURE_TOLERANCE = timedelta(minutes=5)


def _week_start(value: datetime, tz: ZoneInfo) -> date:
    local = value.astimezone(tz)
    return local.date() - timedelta(days=local.weekday())


def _window_starts(now: datetime, tz: ZoneInfo, count: int = WEEKS) -> list[date]:
    current = _week_start(now, tz)
    return [current - timedelta(weeks=offset) for offset in reversed(range(count))]


def _outcome(record: dict) -> str:
    value = record.get("outcome")
    return value if value in {"ok", "degraded", "error"} else "ok"


def _hits(record: dict) -> int:
    value = record.get("hits")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _searches(usage: list[dict]) -> list[dict]:
    return [record for record in usage if record.get("tool") == "plk_search"]


def _operation_trace_stats(usage: list[dict]) -> dict:
    intents = {
        record["trace_id"]: record
        for record in usage
        if record.get("tool") == "plk_record_intent"
        and record.get("outcome") == "recorded"
        and isinstance(record.get("trace_id"), str)
    }
    searches = [
        record
        for record in usage
        if record.get("tool") == "plk_search"
        and isinstance(record.get("trace_id"), str)
    ]
    decisions = [
        record
        for record in usage
        if record.get("tool") == "plk_record_decision"
        and record.get("outcome") == "recorded"
        and isinstance(record.get("trace_id"), str)
    ]
    actions = [
        record
        for record in usage
        if record.get("tool") == "plk_record_action"
        and isinstance(record.get("trace_id"), str)
    ]
    searches_by_trace = Counter(record["trace_id"] for record in searches)
    decisions_by_trace = Counter(record["trace_id"] for record in decisions)
    attempted_by_trace = Counter(
        record["trace_id"] for record in actions if record.get("phase") == "attempted"
    )
    completed_by_trace = Counter(
        record["trace_id"] for record in actions if record.get("phase") == "completed"
    )
    terminal_outcomes = Counter(
        record.get("outcome")
        for record in actions
        if record.get("phase") == "completed"
        and record.get("outcome") in {"succeeded", "failed", "blocked", "cancelled"}
    )
    required = {
        trace_id
        for trace_id, record in intents.items()
        if record.get("plk_requirement") == "required"
    }
    requirements = Counter(
        record.get("plk_requirement")
        for record in intents.values()
        if record.get("plk_requirement") in {"required", "optional", "not_required"}
    )
    side_effects = Counter(
        record.get("side_effect")
        for record in intents.values()
        if record.get("side_effect")
        in {"read", "local_write", "external_write", "destructive"}
    )
    searched_required = {
        trace_id for trace_id in required if searches_by_trace[trace_id]
    }
    effects = Counter(
        record.get("effect")
        for record in decisions
        if isinstance(record.get("effect"), str)
    )
    clients: list[dict] = []
    client_names = {
        client
        for record in intents.values()
        if isinstance((client := record.get("client")), str)
    }
    for client in sorted(client_names):
        trace_ids = {
            trace_id
            for trace_id, record in intents.items()
            if record.get("client") == client
        }
        client_required = trace_ids & required
        client_searched = {
            trace_id for trace_id in client_required if searches_by_trace[trace_id]
        }
        clients.append(
            {
                "client": client,
                "intents": len(trace_ids),
                "plk_required": len(client_required),
                "required_searched": len(client_searched),
                "required_search_rate": len(client_searched) / len(client_required)
                if client_required
                else None,
            }
        )
    return {
        "intents": len(intents),
        "plk_required": len(required),
        "requirements": dict(requirements),
        "side_effects": dict(side_effects),
        "required_searched": len(searched_required),
        "required_search_rate": len(searched_required) / len(required)
        if required
        else None,
        "missing_required_search": len(required - searched_required),
        "with_decision": sum(
            bool(decisions_by_trace[trace_id]) for trace_id in intents
        ),
        "with_action_attempt": sum(
            bool(attempted_by_trace[trace_id]) for trace_id in intents
        ),
        "with_action_completion": sum(
            bool(completed_by_trace[trace_id]) for trace_id in intents
        ),
        "terminal_outcomes": dict(terminal_outcomes),
        "decision_linked_actions": sum(
            1
            for record in actions
            if record.get("phase") == "completed"
            and isinstance(record.get("decision_id"), str)
        ),
        "effects": dict(effects),
        "clients": clients,
    }


def _decisions(usage: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for record in usage:
        decision_id = record.get("decision_id")
        if (
            record.get("tool") != "plk_record_decision"
            or record.get("outcome") != "recorded"
            or not isinstance(decision_id, str)
            or decision_id in seen
        ):
            continue
        seen.add(decision_id)
        result.append(record)
    return result


def _validated_decisions(
    usage: list[dict],
    searches_by_id: dict[str, dict],
) -> list[dict]:
    """Fail closed when a hand-edited or legacy record violates the tool contract."""
    resolved: set[str] = set()
    result: list[dict] = []
    valid_effects = {"changed_action", "prevented_error", "confirmed"}
    valid_no_use = {
        "irrelevant",
        "already_known",
        "stale",
        "conflict",
        "insufficient",
    }
    for decision in _decisions(usage):
        search_ids = decision.get("search_ids")
        used_fact_ids = decision.get("used_fact_ids")
        client = decision.get("client")
        effect = decision.get("effect")
        if (
            not isinstance(search_ids, list)
            or not search_ids
            or not all(isinstance(item, str) for item in search_ids)
            or len(set(search_ids)) != len(search_ids)
            or not isinstance(used_fact_ids, list)
            or not all(isinstance(item, str) for item in used_fact_ids)
            or len(set(used_fact_ids)) != len(used_fact_ids)
            or not isinstance(client, str)
            or any(item not in searches_by_id for item in search_ids)
            or any(searches_by_id[item].get("client") != client for item in search_ids)
            or any(item in resolved for item in search_ids)
        ):
            continue
        returned = {
            fact_id
            for search_id in search_ids
            for fact_id in searches_by_id[search_id].get("fact_ids", [])
            if isinstance(fact_id, str)
        }
        if any(fact_id not in returned for fact_id in used_fact_ids):
            continue
        if effect == "none":
            if used_fact_ids or decision.get("no_use_reason") not in valid_no_use:
                continue
        elif effect in valid_effects:
            if not used_fact_ids or decision.get("no_use_reason") is not None:
                continue
        else:
            continue
        resolved.update(search_ids)
        result.append(decision)
    return result


def _nearest_rank(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _latency(values: list[int]) -> dict:
    return {
        "p50": _nearest_rank(values, 0.50),
        "p95": _nearest_rank(values, 0.95),
        "n": len(values),
    }


def _search_stats(usage: list[dict], now: datetime, tz: ZoneInfo) -> dict:
    searches = _searches(usage)
    starts = _window_starts(now, tz)
    rows = {
        start: {
            "week": start.isoformat(),
            "in_progress": start == starts[-1],
            "auto": 0,
            "manual": 0,
            "returned": 0,
            "ok_total": 0,
            "failures": 0,
        }
        for start in starts
    }
    for record in searches:
        ts = parse_ts(record.get("ts"))
        if ts is None:
            continue
        if ts > now:
            continue
        row = rows.get(_week_start(ts, tz))
        if row is None:
            continue
        if record.get("reason") == "auto-guideline":
            row["auto"] += 1
        else:
            row["manual"] += 1
        if _outcome(record) == "ok":
            row["ok_total"] += 1
            if _hits(record) > 0:
                row["returned"] += 1
        else:
            row["failures"] += 1

    clients = Counter(
        record["client"] for record in searches if isinstance(record.get("client"), str)
    )
    client_rows = [
        {"client": client, "count": count}
        for client, count in sorted(
            clients.items(), key=lambda item: (-item[1], item[0])
        )[:10]
    ]
    all_latency = [
        value
        for record in searches
        if isinstance((value := record.get("latency_ms")), int)
        and not isinstance(value, bool)
        and value >= 0
    ]
    cutoff = now.astimezone(timezone.utc) - timedelta(days=7)
    last7_latency = []
    last7_ok = 0
    last7_returned = 0
    for record in searches:
        value = record.get("latency_ms")
        ts = parse_ts(record.get("ts"))
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            and ts is not None
            and cutoff <= ts.astimezone(timezone.utc) <= now.astimezone(timezone.utc)
        ):
            last7_latency.append(value)
        if (
            ts is not None
            and cutoff <= ts.astimezone(timezone.utc) <= now.astimezone(timezone.utc)
            and _outcome(record) == "ok"
        ):
            last7_ok += 1
            if _hits(record) > 0:
                last7_returned += 1
    return {
        "total": len(searches),
        "weekly": list(rows.values()),
        "clients": client_rows,
        "last7d": {
            "returned": last7_returned,
            "ok_total": last7_ok,
            "return_rate": last7_returned / last7_ok if last7_ok else None,
        },
        "latency": {"last7d": _latency(last7_latency), "all": _latency(all_latency)},
    }


def _zero_hit_queries(usage: list[dict]) -> list[dict]:
    searches = _searches(usage)
    hashes_by_query: dict[str, set[str]] = {}
    for record in searches:
        query = record.get("query")
        query_hash = record.get("query_hash")
        if (
            isinstance(query, str)
            and len(query) <= 200
            and isinstance(query_hash, str)
            and len(query_hash) == 64
            and all(character in "0123456789abcdef" for character in query_hash)
        ):
            hashes_by_query.setdefault(query, set()).add(query_hash)
    legacy_query_hashes = {
        query: next(iter(query_hashes))
        for query, query_hashes in hashes_by_query.items()
        if len(query_hashes) == 1
        and hashlib.sha256(query.encode()).hexdigest() == next(iter(query_hashes))
    }

    groups: dict[str, dict] = {}
    for record in searches:
        query = record.get("query")
        query_hash = record.get("query_hash")
        hits = record.get("hits")
        if (
            _outcome(record) != "ok"
            or not isinstance(hits, int)
            or isinstance(hits, bool)
            or hits != 0
        ):
            continue
        if (
            isinstance(query_hash, str)
            and len(query_hash) == 64
            and all(character in "0123456789abcdef" for character in query_hash)
        ):
            group_key = f"hash:{query_hash}"
            display_query = (
                query
                if isinstance(query, str)
                else f"hash:{query_hash[:12]}…（平文非保存）"
            )
        elif isinstance(query, str) and query in legacy_query_hashes:
            group_key = f"hash:{legacy_query_hashes[query]}"
            display_query = query
        elif isinstance(query, str):
            group_key = f"query:{query}"
            display_query = query
        else:
            continue
        group = groups.setdefault(
            group_key,
            {
                "query": display_query,
                "count": 0,
                "last_ts": None,
                "clients": set(),
            },
        )
        if isinstance(query, str):
            group["query"] = query
        group["count"] += 1
        if isinstance(record.get("client"), str):
            group["clients"].add(record["client"])
        ts = parse_ts(record.get("ts"))
        if ts is not None:
            current = parse_ts(group["last_ts"])
            if current is None or ts > current:
                group["last_ts"] = ts.isoformat()
    rows = [
        {
            "query": group["query"],
            "count": group["count"],
            "last_ts": group["last_ts"],
            "clients": sorted(group["clients"]),
        }
        for group in groups.values()
    ]
    rows.sort(key=lambda row: row["query"])
    rows.sort(
        key=lambda row: (row["last_ts"] is not None, row["last_ts"] or ""),
        reverse=True,
    )
    return rows[:50]


def _normalize_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return parse_ts(value)


def _corpus_stats(
    posts: list[dict], usage: list[dict], now: datetime, tz: ZoneInfo
) -> dict:
    active = [post for post in posts if post.get("status") == "active"]
    invalidated = [post for post in posts if post.get("status") == "invalidated"]
    namespaces = Counter(
        post["namespace"] for post in active if isinstance(post.get("namespace"), str)
    )
    kinds = Counter(
        post["kind"] for post in active if isinstance(post.get("kind"), str)
    )
    starts = _window_starts(now, tz)
    added = {start: 0 for start in starts}
    for post in posts:
        created = _normalize_datetime(post.get("created_at"))
        if created is not None and (start := _week_start(created, tz)) in added:
            added[start] += 1
    returned = referenced_fact_ids(usage)
    unreturned = [
        {
            "id": post.get("id"),
            "namespace": post.get("namespace"),
            "statement": post.get("statement"),
        }
        for post in active
        if isinstance(post.get("id"), str) and post["id"] not in returned
    ]
    unreturned.sort(key=lambda item: str(item["id"]))
    return {
        "available": True,
        "skipped_files": 0,
        "status": {"active": len(active), "invalidated": len(invalidated)},
        "namespaces": [
            {"namespace": namespace, "count": count}
            for namespace, count in sorted(
                namespaces.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "kinds": {
            "philosophy": kinds.get("philosophy", 0),
            "logic": kinds.get("logic", 0),
            "knowhow": kinds.get("knowhow", 0),
        },
        "weekly_added": [
            {"week": start.isoformat(), "count": added[start]} for start in starts
        ],
        "unreturned": {"count": len(unreturned), "items": unreturned[:30]},
    }


def _contribution_stats(usage: list[dict], posts: list[dict] | None = None) -> dict:
    statements = {
        post["id"]: post["statement"]
        for post in (posts or [])
        if isinstance(post.get("id"), str) and isinstance(post.get("statement"), str)
    }
    searches = [
        record
        for record in _searches(usage)
        if _outcome(record) == "ok" and _hits(record) > 0
    ]
    measurable = [
        record for record in searches if isinstance(record.get("search_id"), str)
    ]
    searches_by_id = {
        record["search_id"]: record
        for record in measurable
        if isinstance(record.get("search_id"), str)
    }
    decisions = _validated_decisions(usage, searches_by_id)
    resolved_ids = {
        search_id
        for decision in decisions
        for search_id in decision.get("search_ids", [])
        if isinstance(search_id, str)
    }
    resolved = [
        record for record in measurable if record.get("search_id") in resolved_ids
    ]
    effects = Counter(
        decision["effect"]
        for decision in decisions
        if decision.get("effect")
        in {"changed_action", "prevented_error", "confirmed", "none"}
    )
    no_use_reasons = Counter(
        decision["no_use_reason"]
        for decision in decisions
        if decision.get("effect") == "none"
        and decision.get("no_use_reason")
        in {"irrelevant", "already_known", "stale", "conflict", "insufficient"}
    )
    adopted = (
        effects["changed_action"] + effects["prevented_error"] + effects["confirmed"]
    )
    strong = effects["changed_action"] + effects["prevented_error"]

    client_totals: dict[str, dict[str, int]] = {}
    for record in measurable:
        client = record.get("client")
        if not isinstance(client, str):
            client = "unknown"
        row = client_totals.setdefault(
            client, {"measurable": 0, "resolved": 0, "adopted": 0, "strong": 0}
        )
        row["measurable"] += 1
        if record.get("search_id") in resolved_ids:
            row["resolved"] += 1
    for decision in decisions:
        client = decision.get("client")
        if not isinstance(client, str):
            client = "unknown"
        row = client_totals.setdefault(
            client, {"measurable": 0, "resolved": 0, "adopted": 0, "strong": 0}
        )
        effect = decision.get("effect")
        if effect in {"changed_action", "prevented_error", "confirmed"}:
            row["adopted"] += 1
        if effect in {"changed_action", "prevented_error"}:
            row["strong"] += 1
    client_rows = [
        {
            "client": client,
            **values,
            "measurement_rate": values["resolved"] / values["measurable"]
            if values["measurable"]
            else None,
        }
        for client, values in client_totals.items()
    ]
    client_rows.sort(key=lambda row: (-row["measurable"], row["client"]))

    fact_rows: dict[str, dict[str, int | str]] = {}
    for record in measurable:
        for fact_id in record.get("fact_ids", []):
            if not isinstance(fact_id, str):
                continue
            row = fact_rows.setdefault(
                fact_id,
                {
                    "fact_id": fact_id,
                    "returned_searches": 0,
                    "used_decisions": 0,
                    "strong_decisions": 0,
                },
            )
            row["returned_searches"] = int(row["returned_searches"]) + 1
    for decision in decisions:
        effect = decision.get("effect")
        for fact_id in set(decision.get("used_fact_ids", [])):
            if not isinstance(fact_id, str):
                continue
            row = fact_rows.setdefault(
                fact_id,
                {
                    "fact_id": fact_id,
                    "returned_searches": 0,
                    "used_decisions": 0,
                    "strong_decisions": 0,
                },
            )
            row["used_decisions"] = int(row["used_decisions"]) + 1
            if effect in {"changed_action", "prevented_error"}:
                row["strong_decisions"] = int(row["strong_decisions"]) + 1
    facts = [
        {
            **row,
            "statement": statements.get(str(row["fact_id"])),
            "observed_use_rate": int(row["used_decisions"])
            / int(row["returned_searches"])
            if int(row["returned_searches"])
            else None,
        }
        for row in fact_rows.values()
    ]
    facts.sort(
        key=lambda row: (
            -int(row["strong_decisions"]),
            -int(row["used_decisions"]),
            -int(row["returned_searches"]),
            str(row["fact_id"]),
        )
    )
    linked_decisions = [
        decision
        for decision in decisions
        if any(
            search_id in searches_by_id for search_id in decision.get("search_ids", [])
        )
    ]
    return {
        "hit_searches": len(searches),
        "measurable_hit_searches": len(measurable),
        "resolved_hit_searches": len(resolved),
        "unresolved_hit_searches": len(measurable) - len(resolved),
        "measurement_rate": len(resolved) / len(measurable) if measurable else None,
        "decisions": len(linked_decisions),
        "adopted_decisions": adopted,
        "strong_contribution_decisions": strong,
        "adoption_rate": adopted / len(linked_decisions) if linked_decisions else None,
        "strong_contribution_rate": strong / len(linked_decisions)
        if linked_decisions
        else None,
        "effects": {
            "changed_action": effects["changed_action"],
            "prevented_error": effects["prevented_error"],
            "confirmed": effects["confirmed"],
            "none": effects["none"],
        },
        "no_use_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(
                no_use_reasons.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "clients": client_rows[:20],
        "facts": facts[:50],
    }


def _kill_criteria(usage: list[dict], now: datetime, tz: ZoneInfo) -> dict:
    current = _week_start(now, tz)
    starts = [
        current - timedelta(weeks=offset)
        for offset in reversed(range(1, KILL_WEEKS + 1))
    ]
    rows = {
        start: {
            "week": start.isoformat(),
            "auto_strong_contribution_decisions": 0,
            "_auto_searches": 0,
            "_resolved_searches": 0,
            "_strong_decision_ids": set(),
        }
        for start in starts
    }
    all_searches_by_id = {
        record["search_id"]: record
        for record in _searches(usage)
        if isinstance(record.get("search_id"), str)
        and _outcome(record) == "ok"
        and _hits(record) > 0
    }
    searches_by_id = {
        search_id: record
        for search_id, record in all_searches_by_id.items()
        if record.get("reason") == "auto-guideline"
    }
    decisions = _validated_decisions(usage, all_searches_by_id)
    decisions_by_search = {
        search_id: decision
        for decision in decisions
        for search_id in decision.get("search_ids", [])
    }
    for search_id, record in searches_by_id.items():
        ts = parse_ts(record.get("ts"))
        if ts is None or (row := rows.get(_week_start(ts, tz))) is None:
            continue
        row["_auto_searches"] += 1
        decision = decisions_by_search.get(search_id)
        if decision is None:
            continue
        row["_resolved_searches"] += 1
        if decision.get("effect") in {"changed_action", "prevented_error"}:
            row["_strong_decision_ids"].add(decision["decision_id"])
    values = list(rows.values())
    for row in values:
        row["auto_strong_contribution_decisions"] = len(row["_strong_decision_ids"])
    if not all(
        row["_auto_searches"] > 0 and row["_resolved_searches"] == row["_auto_searches"]
        for row in values
    ):
        verdict = "inconclusive"
    elif all(
        row["auto_strong_contribution_decisions"] >= KILL_THRESHOLD_WEEKLY_HITS
        for row in values
    ):
        verdict = "observed_ok"
    else:
        verdict = "observed_breached"
    for row in values:
        row.pop("_auto_searches")
        row.pop("_resolved_searches")
        row.pop("_strong_decision_ids")
    return {
        "threshold_weekly_hits": KILL_THRESHOLD_WEEKLY_HITS,
        "verdict": verdict,
        "weeks": values,
    }


def _decision_value(
    usage: list[dict],
    now: datetime,
    tz: ZoneInfo,
    *,
    observation_started_at: datetime,
) -> dict:
    """Build the fail-closed decision-value cohort used by the focused UI."""
    now_utc = now.astimezone(timezone.utc)
    future_limit = now_utc + DECISION_VALUE_FUTURE_TOLERANCE
    current_week = _week_start(now, tz)
    starts = [
        current_week - timedelta(weeks=offset)
        for offset in reversed(range(1, KILL_WEEKS + 1))
    ]
    observation_local = observation_started_at.astimezone(tz)
    observation_week = _week_start(observation_local, tz)
    observation_week_start = datetime.combine(
        observation_week, datetime.min.time(), tzinfo=tz
    )
    first_observation_week = (
        observation_week
        if observation_local == observation_week_start
        else observation_week + timedelta(weeks=1)
    )

    weekly_issues: dict[date, Counter[str]] = {start: Counter() for start in starts}
    issue_counts: Counter[str] = Counter()

    def record_issue(code: str, weeks: set[date] | None = None) -> None:
        issue_counts[code] += 1
        for week in weeks or set():
            if week in weekly_issues:
                weekly_issues[week][code] += 1

    candidate_searches = [
        record
        for record in _searches(usage)
        if _outcome(record) == "ok"
        and _hits(record) > 0
        and isinstance(record.get("search_id"), str)
    ]
    searches_grouped: dict[str, list[dict]] = {}
    for record in candidate_searches:
        searches_grouped.setdefault(record["search_id"], []).append(record)

    searches_by_id: dict[str, dict] = {}
    search_times: dict[str, datetime] = {}
    for search_id, records in searches_grouped.items():
        first = records[0]
        if any(record != first for record in records[1:]):
            weeks = {
                _week_start(ts, tz)
                for record in records
                if (ts := parse_ts(record.get("ts"))) is not None
            }
            record_issue("duplicate_search_id", weeks)
            continue
        ts = parse_ts(first.get("ts"))
        if ts is None:
            record_issue("invalid_timestamp")
            continue
        if ts.astimezone(timezone.utc) > future_limit:
            record_issue("future_timestamp", {_week_start(ts, tz)})
            continue
        searches_by_id[search_id] = first
        search_times[search_id] = ts

    candidate_decisions = [
        record
        for record in usage
        if record.get("tool") == "plk_record_decision"
        and record.get("outcome") == "recorded"
        and isinstance(record.get("decision_id"), str)
    ]
    decisions_grouped: dict[str, list[dict]] = {}
    for record in candidate_decisions:
        decisions_grouped.setdefault(record["decision_id"], []).append(record)

    normalized_decisions: list[dict] = []
    for _decision_id, records in decisions_grouped.items():
        first = records[0]
        linked_weeks = {
            _week_start(search_times[search_id], tz)
            for record in records
            for search_id in record.get("search_ids", [])
            if isinstance(search_id, str) and search_id in search_times
        }
        if any(record != first for record in records[1:]):
            record_issue("duplicate_decision_id", linked_weeks)
            continue
        ts = parse_ts(first.get("ts"))
        if ts is None:
            record_issue("invalid_timestamp", linked_weeks)
            continue
        if ts.astimezone(timezone.utc) > future_limit:
            record_issue("future_timestamp", linked_weeks)
            continue
        normalized_decisions.append(first)

    valid_decisions = _validated_decisions(normalized_decisions, searches_by_id)
    valid_decision_ids = {decision["decision_id"] for decision in valid_decisions}
    for decision in normalized_decisions:
        if decision["decision_id"] in valid_decision_ids:
            continue
        linked_weeks = {
            _week_start(search_times[search_id], tz)
            for search_id in decision.get("search_ids", [])
            if isinstance(search_id, str) and search_id in search_times
        }
        record_issue("invalid_decision", linked_weeks)

    resolved_ids = {
        search_id
        for decision in valid_decisions
        for search_id in decision.get("search_ids", [])
        if isinstance(search_id, str)
    }

    weekly_searches: dict[date, list[dict]] = {start: [] for start in starts}
    for search_id, record in searches_by_id.items():
        if record.get("reason") != "auto-guideline":
            continue
        week = _week_start(search_times[search_id], tz)
        if week in weekly_searches:
            weekly_searches[week].append(record)

    weekly_effects: dict[date, dict[str, set[str]]] = {
        start: {"changed_action": set(), "prevented_error": set()} for start in starts
    }
    for decision in valid_decisions:
        effect = decision.get("effect")
        if effect not in {"changed_action", "prevented_error"}:
            continue
        decision_ts = parse_ts(decision.get("ts"))
        if decision_ts is None:
            continue
        used = {
            fact_id
            for fact_id in decision.get("used_fact_ids", [])
            if isinstance(fact_id, str)
        }
        candidates: list[tuple[datetime, dict]] = []
        for search_id in decision.get("search_ids", []):
            if not isinstance(search_id, str) or search_id not in searches_by_id:
                continue
            search = searches_by_id[search_id]
            search_ts = search_times[search_id]
            returned = {
                fact_id
                for fact_id in search.get("fact_ids", [])
                if isinstance(fact_id, str)
            }
            if (
                search.get("reason") == "auto-guideline"
                and used.intersection(returned)
                and search_ts <= decision_ts
            ):
                candidates.append((search_ts, search))
        if not candidates:
            continue
        cohort_week = _week_start(max(candidates, key=lambda item: item[0])[0], tz)
        if cohort_week in weekly_effects:
            weekly_effects[cohort_week][effect].add(decision["decision_id"])

    rows = []
    for start in starts:
        searches = weekly_searches[start]
        measurable_ids = {
            record["search_id"]
            for record in searches
            if isinstance(record.get("search_id"), str)
        }
        resolved = len(measurable_ids.intersection(resolved_ids))
        changed = len(weekly_effects[start]["changed_action"])
        prevented = len(weekly_effects[start]["prevented_error"])
        reasons: list[str] = []
        if start < first_observation_week:
            reasons.append("pre_observation")
        elif not measurable_ids:
            reasons.append("no_eligible_searches")
        if measurable_ids and resolved != len(measurable_ids):
            reasons.append("measurement_gap")
        reasons.extend(sorted(weekly_issues[start]))
        evaluable = (
            start >= first_observation_week
            and bool(measurable_ids)
            and resolved == len(measurable_ids)
            and not weekly_issues[start]
        )
        strong = changed + prevented
        rows.append({
            "week": start.isoformat(),
            "in_progress": False,
            "auto_measurable_searches": len(measurable_ids),
            "auto_resolved_searches": resolved,
            "auto_measurement_rate": resolved / len(measurable_ids)
            if measurable_ids else None,
            "changed_action_decisions": changed,
            "prevented_error_decisions": prevented,
            "strong_decisions": strong,
            "target": KILL_THRESHOLD_WEEKLY_HITS,
            "target_met": evaluable and strong >= KILL_THRESHOLD_WEEKLY_HITS,
            "evaluable": evaluable,
            "unevaluable_reasons": reasons,
            "data_quality_blockers": sum(weekly_issues[start].values()),
        })

    evaluable_weeks = sum(1 for row in rows if row["evaluable"])
    target_met_weeks = sum(1 for row in rows if row["target_met"])
    if evaluable_weeks < KILL_WEEKS:
        status = "insufficient_data"
    elif target_met_weeks == KILL_WEEKS:
        status = "observed_sustained"
    else:
        status = "target_not_met"

    recent_cutoff = now_utc - timedelta(days=READINESS_WINDOW_DAYS)
    recent_searches = [
        record for search_id, record in searches_by_id.items()
        if recent_cutoff <= search_times[search_id].astimezone(timezone.utc) <= now_utc
    ]
    recent_ids = {
        record["search_id"] for record in recent_searches
        if isinstance(record.get("search_id"), str)
    }
    recent_resolved = len(recent_ids.intersection(resolved_ids))

    blockers: list[dict] = []
    data_quality_count = sum(
        count for code, count in issue_counts.items()
        if code in {
            "duplicate_search_id", "duplicate_decision_id", "invalid_decision",
            "invalid_timestamp", "future_timestamp",
        }
    )
    if data_quality_count:
        blockers.append({"code": "invalid_records", "count": data_quality_count, "target": None})
    missing_searches = sum(
        max(0, row["auto_measurable_searches"] - row["auto_resolved_searches"])
        for row in rows if "pre_observation" not in row["unevaluable_reasons"]
    )
    if missing_searches:
        blockers.append({"code": "measurement_gap", "count": missing_searches, "target": None})
    pre_observation = sum(
        1 for row in rows if "pre_observation" in row["unevaluable_reasons"]
    )
    if pre_observation:
        blockers.append({"code": "insufficient_history", "count": pre_observation, "target": None})
    no_search_weeks = sum(
        1 for row in rows if "no_eligible_searches" in row["unevaluable_reasons"]
    )
    if no_search_weeks:
        blockers.append({"code": "no_eligible_searches", "count": no_search_weeks, "target": None})
    missed_weeks = sum(
        1 for row in rows if row["evaluable"] and not row["target_met"]
    )
    if evaluable_weeks == KILL_WEEKS and missed_weeks:
        blockers.append({"code": "weekly_target_missed", "count": missed_weeks, "target": KILL_THRESHOLD_WEEKLY_HITS})
    if not blockers:
        blockers.append({"code": "complete", "count": 0, "target": None})

    priority = [
        "invalid_records", "measurement_gap", "no_eligible_searches",
        "insufficient_history", "weekly_target_missed", "complete",
    ]
    primary = next(code for code in priority if any(row["code"] == code for row in blockers))

    if primary == "invalid_records":
        next_action = {
            "code": "repair_invalid_records", "count": data_quality_count,
            "record_type": "usage", "destination": "data_quality",
        }
    elif primary == "measurement_gap":
        unresolved_clients = Counter(
            str(record.get("client") or "unknown")
            for record in searches_by_id.values()
            if record.get("reason") == "auto-guideline"
            and record.get("search_id") not in resolved_ids
        )
        client = (
            unresolved_clients.most_common(1)[0][0] if unresolved_clients else "unknown"
        )
        next_action = {
            "code": "record_missing_decisions",
            "count": missing_searches,
            "client": client,
            "destination": "decision_measurement",
        }
    elif primary == "no_eligible_searches":
        next_action = {
            "code": "verify_auto_search_flow",
            "weeks": no_search_weeks,
            "observation_started_at": observation_started_at.isoformat(),
            "destination": "decision_measurement",
        }
    elif primary == "insufficient_history":
        next_action = {
            "code": "observe_more_weeks",
            "weeks_remaining": pre_observation,
            "destination": "decision_value",
        }
    elif primary == "weekly_target_missed":
        missed = next(row for row in rows if row["evaluable"] and not row["target_met"])
        next_action = {
            "code": "inspect_below_target_week",
            "week": missed["week"],
            "strong_decisions": missed["strong_decisions"],
            "target": KILL_THRESHOLD_WEEKLY_HITS,
            "destination": "decision_breakdown",
        }
    else:
        next_action = {"code": "none", "destination": None}

    return {
        "status": status,
        "primary_reason_code": primary,
        "blockers": blockers,
        "scope": {
            "recent_coverage": "all_hit_searches",
            "weekly_value": "auto_guideline_only",
        },
        "observation_started_at": observation_started_at.isoformat(),
        "recent": {
            "days": READINESS_WINDOW_DAYS,
            "measurable_searches": len(recent_ids),
            "resolved_searches": recent_resolved,
            "measurement_rate": recent_resolved / len(recent_ids)
            if recent_ids
            else None,
            "minimum_searches": READINESS_MIN_SEARCHES,
            "target_rate": READINESS_MEASUREMENT_TARGET,
        },
        "four_week": {
            "required_weeks": KILL_WEEKS,
            "evaluable_weeks": evaluable_weeks,
            "target_met_weeks": target_met_weeks,
            "weekly_target": KILL_THRESHOLD_WEEKLY_HITS,
        },
        "weekly": rows,
        "next_action": next_action,
        "data_quality": {
            "global_blockers": dict(sorted(issue_counts.items())),
        },
    }


def _eval_stats(eval_history: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for record in eval_history:
        runner = record.get("runner")
        ts = parse_ts(record.get("ts"))
        if not isinstance(runner, str) or ts is None:
            continue
        row = {
            key: record.get(key)
            for key in ("hit5_rate", "mrr", "corpus_active", "queries_hash")
        }
        row["ts"] = ts.isoformat()
        grouped.setdefault(runner, []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: row["ts"])
    return grouped


def _operational_readiness(
    usage: list[dict],
    eval_history: list[dict],
    *,
    now: datetime,
    kill_criteria: dict,
) -> dict:
    """Summarize whether the local PLK has enough evidence for routine operation.

    This is an evidence scorecard, not a production certification.  Contribution
    remains agent self-report and the search-quality gate compares only runners
    evaluated in the same recorded run.
    """
    now_utc = now.astimezone(timezone.utc)
    cutoff = now_utc - timedelta(days=READINESS_WINDOW_DAYS)
    window_searches = []
    for record in _searches(usage):
        ts = parse_ts(record.get("ts"))
        if ts is not None and cutoff <= ts.astimezone(timezone.utc) <= now_utc:
            window_searches.append(record)

    measurable = [
        record
        for record in window_searches
        if _outcome(record) == "ok"
        and _hits(record) > 0
        and isinstance(record.get("search_id"), str)
    ]
    all_searches_by_id = {
        record["search_id"]: record
        for record in _searches(usage)
        if _outcome(record) == "ok"
        and _hits(record) > 0
        and isinstance(record.get("search_id"), str)
    }
    decisions = _validated_decisions(usage, all_searches_by_id)
    resolved_ids = {
        search_id
        for decision in decisions
        for search_id in decision.get("search_ids", [])
        if isinstance(search_id, str)
    }
    resolved = [
        record for record in measurable if record.get("search_id") in resolved_ids
    ]
    measurement_rate = len(resolved) / len(measurable) if measurable else None

    client_counts: dict[str, dict[str, int]] = {}
    for record in measurable:
        client = record.get("client")
        if not isinstance(client, str):
            client = "unknown"
        row = client_counts.setdefault(client, {"measurable": 0, "resolved": 0})
        row["measurable"] += 1
        if record.get("search_id") in resolved_ids:
            row["resolved"] += 1
    active_clients = [
        {
            "client": client,
            **counts,
            "measurement_rate": counts["resolved"] / counts["measurable"],
        }
        for client, counts in sorted(client_counts.items())
        if counts["measurable"] >= READINESS_ACTIVE_CLIENT_MIN_SEARCHES
    ]
    compliant_clients = [
        row
        for row in active_clients
        if row["measurement_rate"] >= READINESS_MEASUREMENT_TARGET
    ]
    client_coverage = (
        len(compliant_clients) / len(active_clients) if active_clients else None
    )

    failures = sum(
        1 for record in window_searches if _outcome(record) in {"degraded", "error"}
    )
    failure_rate = failures / len(window_searches) if window_searches else None
    latency_values = [
        value
        for record in window_searches
        if isinstance((value := record.get("latency_ms")), int)
        and not isinstance(value, bool)
        and value >= 0
    ]
    latency_p95 = _nearest_rank(latency_values, 0.95)

    valid_eval_rows = [
        (record, ts)
        for record in eval_history
        if (ts := parse_ts(record.get("ts"))) is not None
    ]
    eval_detail: dict = {
        "status": "insufficient",
        "latest_ts": None,
        "age_days": None,
        "graph_hit5_rate": None,
        "embed_hit5_rate": None,
        "same_run_comparison": False,
    }
    if valid_eval_rows:
        latest_record, latest_ts = max(valid_eval_rows, key=lambda item: item[1])
        run_id = latest_record.get("run_id")
        if isinstance(run_id, str):
            run_rows = [
                record
                for record, _ts in valid_eval_rows
                if record.get("run_id") == run_id
            ]
        else:
            latest_hash = latest_record.get("queries_hash")
            run_rows = [
                record
                for record, ts in valid_eval_rows
                if ts == latest_ts and record.get("queries_hash") == latest_hash
            ]
        graph_rows = [
            record
            for record in run_rows
            if isinstance(record.get("runner"), str)
            and record["runner"].startswith("graph(")
        ]
        embed_rows = [record for record in run_rows if record.get("runner") == "embed"]
        age_days = max(0, (now_utc - latest_ts.astimezone(timezone.utc)).days)
        eval_detail.update({
            "latest_ts": latest_ts.isoformat(),
            "age_days": age_days,
        })
        if graph_rows and embed_rows:
            graph_row = graph_rows[-1]
            embed_row = embed_rows[-1]
            graph_hit5 = graph_row.get("hit5_rate")
            embed_hit5 = embed_row.get("hit5_rate")
            graph_mrr = graph_row.get("mrr")
            embed_mrr = embed_row.get("mrr")
            comparable = all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in (graph_hit5, embed_hit5, graph_mrr, embed_mrr)
            )
            eval_detail.update({
                "graph_hit5_rate": graph_hit5,
                "embed_hit5_rate": embed_hit5,
                "same_run_comparison": comparable,
            })
            if age_days > READINESS_EVAL_MAX_AGE_DAYS:
                eval_detail["status"] = "stale"
            elif comparable:
                assert isinstance(graph_hit5, (int, float))
                assert isinstance(embed_hit5, (int, float))
                assert isinstance(graph_mrr, (int, float))
                assert isinstance(embed_mrr, (int, float))
                eval_detail["status"] = (
                    "pass"
                    if graph_hit5 >= embed_hit5 and graph_mrr >= embed_mrr
                    else "fail"
                )

    def gate(
        gate_id: str,
        label: str,
        status: str,
        current: str,
        target: str,
    ) -> dict:
        return {
            "id": gate_id,
            "label": label,
            "status": status,
            "current": current,
            "target": target,
        }

    enough_measurement = len(measurable) >= READINESS_MIN_SEARCHES
    measurement_status = (
        "insufficient"
        if not enough_measurement
        else "pass"
        if measurement_rate is not None
        and measurement_rate >= READINESS_MEASUREMENT_TARGET
        else "fail"
    )
    client_status = (
        "insufficient"
        if not active_clients
        else "pass"
        if client_coverage == 1.0
        else "fail"
    )
    enough_reliability = len(window_searches) >= READINESS_MIN_SEARCHES
    reliability_status = (
        "insufficient"
        if not enough_reliability or latency_p95 is None or failure_rate is None
        else "pass"
        if failure_rate <= READINESS_FAILURE_RATE_TARGET
        and latency_p95 <= READINESS_LATENCY_P95_TARGET_MS
        else "fail"
    )
    value_status = {
        "observed_ok": "pass",
        "observed_breached": "fail",
        "inconclusive": "insufficient",
    }.get(str(kill_criteria.get("verdict")), "insufficient")

    gates = [
        gate(
            "measurement",
            "検索から最終判断までの計測",
            measurement_status,
            f"{len(resolved)}/{len(measurable)}"
            + (f" ({measurement_rate:.0%})" if measurement_rate is not None else ""),
            f"直近{READINESS_WINDOW_DAYS}日で{READINESS_MEASUREMENT_TARGET:.0%}以上"
            f"（最低{READINESS_MIN_SEARCHES}検索）",
        ),
        gate(
            "client_coverage",
            "利用中クライアントの計測定着",
            client_status,
            f"{len(compliant_clients)}/{len(active_clients)} clients",
            f"各client {READINESS_MEASUREMENT_TARGET:.0%}以上"
            f"（最低{READINESS_ACTIVE_CLIENT_MIN_SEARCHES}検索/client）",
        ),
        gate(
            "observed_value",
            "強い意思決定貢献",
            value_status,
            str(kill_criteria.get("verdict", "inconclusive")),
            f"4完了週で毎週{KILL_THRESHOLD_WEEKLY_HITS}件以上、計測欠損なし",
        ),
        gate(
            "reliability",
            "検索の信頼性",
            reliability_status,
            f"failure {failure_rate:.1%}, p95 {latency_p95} ms"
            if failure_rate is not None and latency_p95 is not None
            else "データ不足",
            f"failure ≤ {READINESS_FAILURE_RATE_TARGET:.0%}, "
            f"p95 ≤ {READINESS_LATENCY_P95_TARGET_MS} ms",
        ),
        gate(
            "retrieval_eval",
            "検索品質の対照評価",
            str(eval_detail["status"]),
            (
                f"graph {eval_detail['graph_hit5_rate']:.0%}, "
                f"embed {eval_detail['embed_hit5_rate']:.0%}"
                if isinstance(eval_detail["graph_hit5_rate"], (int, float))
                and isinstance(eval_detail["embed_hit5_rate"], (int, float))
                else "同一runのgraph/embed評価なし"
            ),
            f"{READINESS_EVAL_MAX_AGE_DAYS}日以内、graphがembed以上",
        ),
    ]
    passed = sum(1 for item in gates if item["status"] == "pass")
    if passed == len(gates):
        status = "ready"
    elif any(item["status"] == "fail" for item in gates):
        status = "needs_work"
    else:
        status = "insufficient_data"
    return {
        "status": status,
        "passed_gates": passed,
        "total_gates": len(gates),
        "window_days": READINESS_WINDOW_DAYS,
        "gates": gates,
        "active_clients": active_clients,
        "eval": eval_detail,
        "note": "観測可能性と運用価値のゲート。因果効果や本番認証・復旧試験の証明ではありません。",
    }


def build_metrics(
    usage: list[dict],
    posts: list[dict],
    eval_history: list[dict],
    *,
    now: datetime,
    tz: ZoneInfo,
    observation_started_at: datetime = DECISION_VALUE_OBSERVATION_STARTED_AT,
) -> dict:
    """Build the complete metrics response without reading external state."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    kill_criteria = _kill_criteria(usage, now, tz)
    return {
        "generated_at": now.astimezone(tz).isoformat(timespec="seconds"),
        "search": _search_stats(usage, now, tz),
        "operation_traces": _operation_trace_stats(usage),
        "contribution": _contribution_stats(usage, posts),
        "decision_value": _decision_value(
            usage,
            now,
            tz,
            observation_started_at=observation_started_at,
        ),
        "zero_hit": _zero_hit_queries(usage),
        "corpus": _corpus_stats(posts, usage, now, tz),
        "kill_criteria": kill_criteria,
        "operational_readiness": _operational_readiness(
            usage,
            eval_history,
            now=now,
            kill_criteria=kill_criteria,
        ),
        "eval": _eval_stats(eval_history),
    }
