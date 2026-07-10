import frontmatter

from plk_memory.curation import aggregate, read_usage, render_markdown


def _post(fid, ns="plk.domain.tax", status="active", statement="x" * 25):
    return frontmatter.Post("body", id=fid, namespace=ns, status=status, kind="knowhow",
                            statement=statement, why="y" * 25, how_to_apply="h" * 20,
                            source="https://e.co", source_type="agent", written_by="t",
                            created_at="2026-07-01T00:00:00+09:00")


def test_read_usage_skips_broken_lines(tmp_path):
    p = tmp_path / "u.jsonl"
    p.write_text('{"tool":"plk_search","hits":2,"reason":"auto-guideline"}\nnot-json\n', encoding="utf-8")
    assert len(read_usage(p)) == 1


def test_aggregate_counts_and_unreferenced():
    posts = [(_post("01A"), "knowledge/domains/tax/a.md"),
             (_post("01B", status="invalidated"), "knowledge/domains/tax/b.md")]
    usage = [{"tool": "plk_search", "hits": 1, "reason": "auto-guideline"},
             {"tool": "plk_search", "hits": 0, "reason": "manual"}]
    agg = aggregate(posts, usage)
    assert agg["total_facts"] == 2 and agg["active_facts"] == 1
    assert agg["search_stats"]["total_searches"] == 2
    assert agg["search_stats"]["auto_vs_manual"] == {"auto": 1, "manual": 1}
    assert "01A" in [u["id"] for u in agg["unreferenced"]]


def test_search_hit_fact_ids_count_as_referenced():
    posts = [(_post("01A"), "knowledge/domains/tax/a.md"),
             (_post("01B"), "knowledge/domains/tax/b.md")]
    usage = [{"tool": "plk_search", "hits": 1, "reason": "manual", "fact_ids": ["01A"]}]
    agg = aggregate(posts, usage)
    ids = [u["id"] for u in agg["unreferenced"]]
    assert "01A" not in ids and "01B" in ids


def test_weekly_hit_counts_only_last_7_days():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=8)).isoformat(timespec="seconds")
    recent = (now - timedelta(days=1)).isoformat(timespec="seconds")
    usage = [{"tool": "plk_search", "hits": 3, "ts": old},
             {"tool": "plk_search", "hits": 2, "ts": recent},
             {"tool": "plk_search", "hits": 1},  # ts なしは対象外
             {"tool": "plk_search", "hits": 0, "ts": recent}]
    agg = aggregate([], usage)
    assert agg["search_stats"]["weekly_hit_counts"] == 1


def test_conflict_detection_disabled_below_threshold():
    posts = [(_post(f"{i:026X}"), f"knowledge/domains/tax/{i}.md") for i in range(5)]
    agg = aggregate(posts, [])
    assert agg["conflicts"]["enabled"] is False


def test_render_prints_kill_criteria():
    md = render_markdown(aggregate([], []), kill_criteria="週3回未満で撤退")
    assert "週3回未満で撤退" in md and "#" in md
