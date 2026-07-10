"""月次キュレーションレポートを生成し agent-organization/reports/curation/ に commit する。

usage: uv run python scripts/curation/run_report.py [--no-commit]
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime

from plk_memory.curation import aggregate, read_usage, render_markdown
from plk_memory.facts import FactService
from plk_memory.gitstore import GitStore
from plk_memory.settings import Settings

KILL = ("4 週連続で動線経由 plk_search の引用が週 3 回未満、または保守が週 30 分超過 →"
        " グラフ層凍結・常駐解除（設計書 §11）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-commit", action="store_true")
    args = ap.parse_args()

    settings = Settings()
    store = GitStore(settings)
    store.ensure_repo()
    facts = FactService(store, settings)
    agg = aggregate(facts.list_posts(), read_usage(settings.usage_log_path))
    md = render_markdown(agg, kill_criteria=KILL)

    month = datetime.now().strftime("%Y-%m")
    rel = f"reports/curation/{month}.md"
    out = settings.data_repo_path / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"wrote {out}")

    if not args.no_commit:
        repo = str(settings.data_repo_path)
        subprocess.run(["git", "-C", repo, "add", rel], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-m", f"docs: {month} キュレーションレポート"], check=True)
        subprocess.run(["git", "-C", repo, "push", "origin", "main"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
