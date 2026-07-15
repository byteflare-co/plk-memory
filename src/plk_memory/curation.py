"""月次キュレーションレポート（設計書 §9・§11）。

矛盾・重複検出はコーパス 100 件到達まで無効（小コーパス期の誤検知抑止）。
運用期キル基準の数値を毎回印字する。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from plk_memory.usage_records import parse_ts as _parse_ts
from plk_memory.usage_records import read_usage as read_usage
from plk_memory.usage_records import referenced_fact_ids


def aggregate(posts, usage, *, corpus_conflict_threshold: int = 100) -> dict:
    active = [(p, rel) for p, rel in posts if p.get("status") == "active"]
    invalidated = [(p, rel) for p, rel in posts if p.get("status") == "invalidated"]

    searches = [u for u in usage if u.get("tool") == "plk_search"]
    auto = sum(1 for u in searches if u.get("reason") == "auto-guideline")
    manual = len(searches) - auto
    # 直近 7 日のヒットあり検索件数（ts が無い/壊れているレコードは対象外）
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    weekly_hits = sum(
        1 for u in searches
        if (u.get("hits") or 0) > 0
        and (ts := _parse_ts(u.get("ts"))) is not None
        and ts >= week_ago
    )

    # 「参照済み」= 利用ログに現れた fact_id（history/invalidate 等の明示対象）
    # ＋ plk_search のヒット結果として返された fact_ids
    referenced = referenced_fact_ids(usage)
    unreferenced = [
        {"id": p.get("id"), "namespace": p.get("namespace"), "statement": p.get("statement")}
        for p, _ in active
        if p.get("id") not in referenced
    ]

    if len(posts) < corpus_conflict_threshold:
        conflicts: dict = {
            "enabled": False,
            "reason": f"コーパス {len(posts)} 件 < {corpus_conflict_threshold} 件のため矛盾検出は無効（設計書 §9）",
        }
    else:
        dupes = [s for s, n in Counter(
            (p.get("namespace"), p.get("statement")) for p, _ in active
        ).items() if n > 1]
        conflicts = {"enabled": True, "duplicate_statements": [d[1] for d in dupes]}

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "total_facts": len(posts),
        "active_facts": len(active),
        "invalidated_facts": len(invalidated),
        "unreferenced": unreferenced,
        "search_stats": {
            "total_searches": len(searches),
            "auto_vs_manual": {"auto": auto, "manual": manual},
            "weekly_hit_counts": weekly_hits,
        },
        "conflicts": conflicts,
    }


def render_markdown(agg: dict, *, kill_criteria: str) -> str:
    lines = [
        "# plk-memory 月次キュレーションレポート",
        "",
        f"生成日時: {agg.get('generated_at', '')}",
        "",
        "## サマリ",
        f"- 総ファクト: {agg['total_facts']}（active {agg['active_facts']} / invalidated {agg['invalidated_facts']}）",
        f"- plk_search 総数: {agg['search_stats']['total_searches']}"
        f"（auto {agg['search_stats']['auto_vs_manual']['auto']} /"
        f" manual {agg['search_stats']['auto_vs_manual']['manual']}）",
        f"- ヒットありの検索（直近7日）: {agg['search_stats']['weekly_hit_counts']}",
        "",
        "## 未参照ファクト（棚卸し候補）",
    ]
    if agg["unreferenced"]:
        lines += [f"- `{u['id']}` [{u['namespace']}] {u['statement']}" for u in agg["unreferenced"]]
    else:
        lines.append("- なし")
    lines += ["", "## 矛盾・重複検出"]
    if agg["conflicts"].get("enabled"):
        dups = agg["conflicts"].get("duplicate_statements", [])
        lines += [f"- 重複 statement: {d}" for d in dups] or ["- 重複なし"]
    else:
        lines.append(f"- 無効: {agg['conflicts']['reason']}")
    lines += [
        "",
        "## 運用期キル基準（設計書 §11・毎回印字）",
        f"- {kill_criteria}",
        "",
    ]
    return "\n".join(lines)
