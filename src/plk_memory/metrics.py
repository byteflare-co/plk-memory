"""Pure metric aggregation for the local PLK dashboard."""

from __future__ import annotations

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
    groups: dict[str, dict] = {}
    for record in _searches(usage):
        query = record.get("query")
        hits = record.get("hits")
        if (
            _outcome(record) != "ok"
            or not isinstance(hits, int)
            or isinstance(hits, bool)
            or hits != 0
            or not isinstance(query, str)
        ):
            continue
        group = groups.setdefault(query, {"count": 0, "last_ts": None, "clients": set()})
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
            "query": query,
            "count": group["count"],
            "last_ts": group["last_ts"],
            "clients": sorted(group["clients"]),
        }
        for query, group in groups.items()
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


def _kill_criteria(usage: list[dict], now: datetime, tz: ZoneInfo) -> dict:
    current = _week_start(now, tz)
    starts = [current - timedelta(weeks=offset) for offset in reversed(range(1, KILL_WEEKS + 1))]
    rows = {
        start: {"week": start.isoformat(), "auto_returned_searches": 0, "observed": False}
        for start in starts
    }
    for record in _searches(usage):
        ts = parse_ts(record.get("ts"))
        if ts is None or (row := rows.get(_week_start(ts, tz))) is None:
            continue
        row["observed"] = True
        if (
            record.get("reason") == "auto-guideline"
            and _outcome(record) == "ok"
            and _hits(record) > 0
        ):
            row["auto_returned_searches"] += 1
    values = list(rows.values())
    if not all(row["observed"] for row in values):
        verdict = "inconclusive"
    elif all(row["auto_returned_searches"] < KILL_THRESHOLD_WEEKLY_HITS for row in values):
        verdict = "proxy_breached"
    else:
        verdict = "proxy_ok"
    for row in values:
        row.pop("observed")
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
        "zero_hit": _zero_hit_queries(usage),
        "corpus": _corpus_stats(posts, usage, now, tz),
        "kill_criteria": _kill_criteria(usage, now, tz),
        "eval": _eval_stats(eval_history),
    }
