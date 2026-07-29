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
        record["client"]
        for record in searches
        if isinstance(record.get("client"), str)
    )
    client_rows = [
        {"client": client, "count": count}
        for client, count in sorted(clients.items(), key=lambda item: (-item[1], item[0]))[:10]
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
            and len(query) < 200
            and isinstance(query_hash, str)
            and len(query_hash) == 64
            and all(character in "0123456789abcdef" for character in query_hash)
            and hashlib.sha256(query.encode()).hexdigest() == query_hash
        ):
            hashes_by_query.setdefault(query, set()).add(query_hash)
    legacy_query_hashes = {
        query: next(iter(query_hashes))
        for query, query_hashes in hashes_by_query.items()
        if len(query_hashes) == 1
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


def _corpus_stats(posts: list[dict], usage: list[dict], now: datetime, tz: ZoneInfo) -> dict:
    active = [post for post in posts if post.get("status") == "active"]
    invalidated = [post for post in posts if post.get("status") == "invalidated"]
    namespaces = Counter(
        post["namespace"] for post in active if isinstance(post.get("namespace"), str)
    )
    kinds = Counter(post["kind"] for post in active if isinstance(post.get("kind"), str))
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
            for namespace, count in sorted(namespaces.items(), key=lambda item: (-item[1], item[0]))
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


def _contribution_stats(usage: list[dict]) -> dict:
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
    adopted = effects["changed_action"] + effects["prevented_error"] + effects["confirmed"]
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
            search_id in searches_by_id
            for search_id in decision.get("search_ids", [])
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
    starts = [current - timedelta(weeks=offset) for offset in reversed(range(1, KILL_WEEKS + 1))]
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
        row["auto_strong_contribution_decisions"] = len(
            row["_strong_decision_ids"]
        )
    if not all(
        row["_auto_searches"] > 0
        and row["_resolved_searches"] == row["_auto_searches"]
        for row in values
    ):
        verdict = "inconclusive"
    elif all(
        row["auto_strong_contribution_decisions"] < KILL_THRESHOLD_WEEKLY_HITS
        for row in values
    ):
        verdict = "observed_breached"
    else:
        verdict = "observed_ok"
    for row in values:
        row.pop("_auto_searches")
        row.pop("_resolved_searches")
        row.pop("_strong_decision_ids")
    return {
        "threshold_weekly_hits": KILL_THRESHOLD_WEEKLY_HITS,
        "verdict": verdict,
        "weeks": values,
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


def build_metrics(
    usage: list[dict],
    posts: list[dict],
    eval_history: list[dict],
    *,
    now: datetime,
    tz: ZoneInfo,
) -> dict:
    """Build the complete metrics response without reading external state."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return {
        "generated_at": now.astimezone(tz).isoformat(timespec="seconds"),
        "search": _search_stats(usage, now, tz),
        "contribution": _contribution_stats(usage),
        "zero_hit": _zero_hit_queries(usage),
        "corpus": _corpus_stats(posts, usage, now, tz),
        "kill_criteria": _kill_criteria(usage, now, tz),
        "eval": _eval_stats(eval_history),
    }
