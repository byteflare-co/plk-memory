"""検索評価ハーネス（Phase 1 Task 14）。

3 種のランナーで日本語評価セット（scripts/eval/queries.yaml）を回し、
hit@5 と MRR（Mean Reciprocal Rank）を per-query / 集計で出力する。

ランナー:
  1. graph  — GraphIndex.search（graphiti-core 0.29.2 経由）。--graph-mode で
              episode / triplet を選ぶ。uuid_to_fact は reindex 直後の
              ~/.plk/state.json（facts セクション）から構築する。評価前に
              その mode で reindex 済みであること（state とグラフの整合性が前提）。
  2. embed  — knowledge/ の active ファクトを render_episode でテキスト化し、
              Ollama /v1/embeddings（bge-m3）で埋め込んで cosine 類似度で
              ランキングする素の埋め込み検索（graphiti を一切介さない）。
  3. rg     — クエリを空白区切りトークンに分割し、各トークンで knowledge/ を
              ripgrep（無ければ Python re）検索、ファイルごとのマッチトークン数で
              ランキングして fact id に変換する素の字句検索。

LLM/embedder は完全ローカル（Ollama）。Anthropic API は一切使わない。

    uv run python scripts/eval/run_eval.py --runners rg,embed --out /tmp/eval-baselines.md
    uv run python scripts/eval/run_eval.py --runners graph --graph-mode triplet --out /tmp/eval-graph-triplet.md
    uv run python scripts/eval/run_eval.py --runners graph --graph-mode episode --out /tmp/eval-graph-episode.md
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import frontmatter
import httpx
import yaml
from ulid import ULID

from plk_memory.rendering import render_episode
from plk_memory.settings import Settings
from plk_memory.state import StateStore

LIMIT = 5  # hit@5 / top5


# --------------------------------------------------------------------------
# コーパス読み込み
# --------------------------------------------------------------------------

class Fact:
    __slots__ = ("fact_id", "path", "status", "post")

    def __init__(self, fact_id: str, path: Path, status: str, post: frontmatter.Post):
        self.fact_id = fact_id
        self.path = path
        self.status = status
        self.post = post


def load_facts(settings: Settings) -> list[Fact]:
    """knowledge/domains/**/*.md の全ファクトを読み込む（active/invalidated 両方）。"""
    domains_dir = settings.knowledge_dir / "domains"
    facts: list[Fact] = []
    for path in sorted(domains_dir.rglob("*.md")):
        if path.name in {"CONVENTIONS.md", "README.md"}:
            continue
        post = frontmatter.load(str(path))
        fid = post.get("id")
        status = post.get("status", "active")
        if not isinstance(fid, str) or not isinstance(status, str):
            continue
        facts.append(Fact(fid, path, status, post))
    return facts


def load_queries(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"queries.yaml はクエリのリストであるべき: {path}")
    return data


# --------------------------------------------------------------------------
# 指標
# --------------------------------------------------------------------------

def rank_of_first_expected(ranked_ids: list[str], expected: list[str]) -> int | None:
    """ranked_ids（順位順）で最初に expected に一致した 1-based 順位。無ければ None。"""
    exp = set(expected)
    for i, fid in enumerate(ranked_ids, start=1):
        if fid in exp:
            return i
    return None


def reciprocal_rank(rank: int | None) -> float:
    return (1.0 / rank) if rank else 0.0


def compute_summary(
    queries: list[dict],
    runner_results: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, int | float]]:
    """ランナーごとの hit@5 数・率・平均 MRR を返す。"""
    summary: dict[str, dict[str, int | float]] = {}
    n = len(queries)
    for runner, results in runner_results.items():
        hits = 0
        rr = 0.0
        for item in queries:
            rank = rank_of_first_expected(
                results.get(item["query"], []),
                item["expected"],
            )
            if rank is not None:
                hits += 1
                rr += reciprocal_rank(rank)
        summary[runner] = {
            "hit5": hits,
            "hit5_rate": hits / n if n else 0.0,
            "mrr": rr / n if n else 0.0,
        }
    return summary


# --------------------------------------------------------------------------
# ランナー: rg（字句検索）
# --------------------------------------------------------------------------

def tokenize(query: str) -> list[str]:
    """空白区切りトークン化（brief 準拠）。空トークンは除去。"""
    return [t for t in re.split(r"\s+", query.strip()) if t]


def run_rg(query: str, facts: list[Fact], settings: Settings, use_rg: bool) -> list[str]:
    """空白区切り各トークンでファイル検索し、マッチトークン数降順に fact id を返す。"""
    domains_dir = settings.knowledge_dir / "domains"
    path_to_fact = {str(f.path): f.fact_id for f in facts}
    tokens = tokenize(query)
    counts: dict[str, int] = {}  # path -> マッチしたトークン数
    for tok in tokens:
        if use_rg:
            proc = subprocess.run(
                ["rg", "-l", "-i", "--fixed-strings", tok, str(domains_dir)],
                capture_output=True, text=True,
            )
            matched_paths = [ln for ln in proc.stdout.splitlines() if ln]
        else:
            matched_paths = []
            pat = re.compile(re.escape(tok), re.IGNORECASE)
            for f in facts:
                if pat.search(f.path.read_text(encoding="utf-8")):
                    matched_paths.append(str(f.path))
        for p in matched_paths:
            if p in path_to_fact:
                counts[p] = counts.get(p, 0) + 1
    ranked_paths = sorted(counts, key=lambda p: counts[p], reverse=True)
    return [path_to_fact[p] for p in ranked_paths[:LIMIT]]


# --------------------------------------------------------------------------
# ランナー: embed（素の埋め込み検索）
# --------------------------------------------------------------------------

def embed_text(client: httpx.Client, settings: Settings, text: str) -> list[float]:
    resp = client.post(
        f"{settings.embedder_base_url}/embeddings",
        json={"model": settings.embedder_model, "input": text},
        headers={"Authorization": f"Bearer {settings.embedder_api_key}"},
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def build_embed_index(settings: Settings, facts: list[Fact]) -> list[tuple[str, list[float]]]:
    """active ファクトのみを render_episode → 埋め込み。graphiti 索引と同条件。"""
    active = [f for f in facts if f.status == "active"]
    index: list[tuple[str, list[float]]] = []
    with httpx.Client() as client:
        for f in active:
            vec = embed_text(client, settings, render_episode(f.post))
            index.append((f.fact_id, vec))
    return index


def run_embed(query: str, settings: Settings, index: list[tuple[str, list[float]]]) -> list[str]:
    with httpx.Client() as client:
        qvec = embed_text(client, settings, query)
    scored = [(fid, cosine(qvec, vec)) for fid, vec in index]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [fid for fid, _ in scored[:LIMIT]]


# --------------------------------------------------------------------------
# ランナー: graph（GraphIndex.search）
# --------------------------------------------------------------------------

async def run_graph_all(
    queries: list[dict], settings: Settings
) -> tuple[dict[str, list[str]], int, int]:
    """全クエリを 1 つの GraphIndex インスタンスで検索して {query: ranked_ids} を返す。"""
    from plk_memory.graphindex import GraphIndex

    state = StateStore(settings.state_path).load()
    uuid_to_fact = {
        uuid: fact_id
        for fact_id, entry in state.facts.items()
        for uuid in entry.episode_uuids
    }

    graph = GraphIndex(settings)
    await graph.start()
    results: dict[str, list[str]] = {}
    for q in queries:
        query = q["query"]
        hits = await graph.search(
            query,
            group_ids=[settings.main_group],
            uuid_to_fact=uuid_to_fact,
            limit=LIMIT,
        )
        results[query] = [h.fact_id for h in hits]
    return results, len(uuid_to_fact), len(state.facts)


# --------------------------------------------------------------------------
# 出力
# --------------------------------------------------------------------------

def render_markdown(
    queries: list[dict],
    runner_results: dict[str, dict[str, list[str]]],
    meta: dict,
) -> str:
    """runner_results: {runner_label: {query: ranked_ids}}。"""
    runners = list(runner_results.keys())
    lines: list[str] = []
    lines.append("# 検索評価結果")
    lines.append("")
    for k, v in meta.items():
        lines.append(f"- {k}: {v}")
    lines.append("")

    # per-query 表
    lines.append("## per-query（hit@5 と rank）")
    lines.append("")
    header = "| # | クエリ | expected | " + " | ".join(runners) + " |"
    sep = "|---|---|---|" + "|".join(["---"] * len(runners)) + "|"
    lines.append(header)
    lines.append(sep)

    for i, q in enumerate(queries, start=1):
        query = q["query"]
        expected = q["expected"]
        cells: list[str] = []
        for r in runners:
            ranked = runner_results[r].get(query, [])
            rank = rank_of_first_expected(ranked, expected)
            if rank is not None:
                cells.append(f"hit@{rank}")
            else:
                cells.append("miss")
        exp_short = ",".join(e[-6:] for e in expected)
        qshort = query if len(query) <= 34 else query[:33] + "…"
        lines.append(f"| {i} | {qshort} | …{exp_short} | " + " | ".join(cells) + " |")

    # 集計
    n = len(queries)
    lines.append("")
    lines.append("## 集計")
    lines.append("")
    lines.append("| ランナー | hit@5 | hit@5 率 | 平均MRR |")
    lines.append("|---|---|---|---|")
    summary = compute_summary(queries, runner_results)
    for r in runners:
        hits = int(summary[r]["hit5"])
        rate = float(summary[r]["hit5_rate"])
        mrr = float(summary[r]["mrr"])
        lines.append(f"| {r} | {hits}/{n} | {rate:.2f} | {mrr:.3f} |")
    lines.append("")
    return "\n".join(lines)


def queries_hash(queries: list[dict]) -> str:
    """YAML の表記揺れに依存しないクエリセットの sha256。"""
    canonical = json.dumps(
        queries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def corpus_revision(data_repo_path: Path) -> str:
    """評価対象データリポジトリの短縮 Git revision を返す。"""
    proc = subprocess.run(
        ["git", "-C", str(data_repo_path), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    revision = proc.stdout.strip()
    if not revision:
        raise RuntimeError("git rev-parse が空の revision を返しました")
    return revision


def build_history_records(
    *,
    settings: Settings,
    queries: list[dict],
    facts: list[Fact],
    runner_results: dict[str, dict[str, list[str]]],
) -> list[dict]:
    """1 回の評価結果を、ランナーごとの provenance 付き履歴へ変換する。"""
    summary = compute_summary(queries, runner_results)
    if not summary:
        return []
    timestamp = datetime.now().astimezone().isoformat()
    run_id = str(ULID())
    query_set_hash = queries_hash(queries)
    revision = corpus_revision(settings.data_repo_path)
    active = sum(1 for fact in facts if fact.status == "active")
    records: list[dict] = []
    for runner, values in summary.items():
        is_embed = runner == "embed"
        is_graph = runner.startswith("graph(")
        graph_mode = runner.removeprefix("graph(").removesuffix(")") if is_graph else None
        records.append({
            "ts": timestamp,
            "run_id": run_id,
            "runner": runner,
            "queries": len(queries),
            "queries_hash": query_set_hash,
            "hit5": values["hit5"],
            "hit5_rate": values["hit5_rate"],
            "mrr": values["mrr"],
            "corpus_active": active,
            "corpus_total": len(facts),
            "corpus_revision": revision,
            "corpus_scope": "domains",
            "embed_model": settings.embedder_model if is_embed else None,
            "llm_model": settings.llm_model if is_graph else None,
            "graph_mode": graph_mode,
        })
    return records


def append_history(path: Path, records: list[dict]) -> None:
    """履歴を JSON Lines として追記する。"""
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="plk-memory 検索評価")
    parser.add_argument("--queries", type=Path,
                        default=Path(__file__).parent / "queries.yaml")
    parser.add_argument("--runners", default="rg,embed",
                        help="カンマ区切り: rg,embed,graph")
    parser.add_argument("--graph-mode", choices=["episode", "triplet"], default=None,
                        help="graph ランナー使用時の ingest_mode（reindex 済みのモードと一致させる）")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-history", action="store_true",
                        help="eval-history.jsonl への追記を無効にする")
    args = parser.parse_args()

    settings = Settings()
    queries = load_queries(args.queries)
    facts = load_facts(settings)
    runners = [r.strip() for r in args.runners.split(",") if r.strip()]

    runner_results: dict[str, dict[str, list[str]]] = {}
    meta: dict[str, str] = {
        "queries": str(len(queries)),
        "corpus_active": str(sum(1 for f in facts if f.status == "active")),
        "corpus_total": str(len(facts)),
        "limit": str(LIMIT),
    }

    if "rg" in runners:
        use_rg = shutil.which("rg") is not None
        meta["rg_backend"] = "ripgrep" if use_rg else "python-re"
        rg_res = {q["query"]: run_rg(q["query"], facts, settings, use_rg) for q in queries}
        runner_results["rg"] = rg_res

    if "embed" in runners:
        meta["embed_model"] = settings.embedder_model
        index = build_embed_index(settings, facts)
        embed_res = {q["query"]: run_embed(q["query"], settings, index) for q in queries}
        runner_results["embed"] = embed_res

    if "graph" in runners:
        if args.graph_mode is None:
            raise SystemExit("graph ランナーには --graph-mode episode|triplet が必要")
        settings.ingest_mode = args.graph_mode
        meta["graph_mode"] = args.graph_mode
        meta["llm_model"] = settings.llm_model
        results, n_uuids, n_state_facts = asyncio.run(run_graph_all(queries, settings))
        meta["state_facts"] = str(n_state_facts)
        meta["state_uuid_mappings"] = str(n_uuids)
        runner_results[f"graph({args.graph_mode})"] = results

    text = render_markdown(queries, runner_results, meta)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")

    if not args.no_history:
        try:
            records = build_history_records(
                settings=settings,
                queries=queries,
                facts=facts,
                runner_results=runner_results,
            )
            append_history(settings.eval_history_path, records)
        except Exception as exc:
            print(f"warning: eval-history の追記に失敗しました: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
