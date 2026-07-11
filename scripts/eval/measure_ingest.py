"""ingest 実測スクリプト（Phase 1 Task 13）。

実データリポジトリ（~/.plk/data-repo の 23 ファクト）に対して
`SyncEngine.reindex()` を実行し、壁時計時間・upsert 件数・dead letter を計測して
JSON に出力する。episode / triplet の両モードを --mode で切り替える。

    uv run python scripts/eval/measure_ingest.py --mode episode --out /tmp/ingest-episode.json
    uv run python scripts/eval/measure_ingest.py --mode triplet --out /tmp/ingest-triplet.json

Anthropic API は一切使わない（settings 既定の openai-compatible / ローカル Ollama）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from plk_memory.app import AppServices, _build_services
from plk_memory.settings import Settings


async def _run(mode: str | None) -> dict:
    settings = Settings()
    if mode:
        settings.ingest_mode = mode

    services = _build_services(settings, graph=None)
    if not isinstance(services, AppServices):
        raise RuntimeError("measure_ingest requires the Git storage backend")

    services.store.ensure_repo()
    await services.graph.start()

    total_facts = len(services.facts.list_posts())

    start = time.monotonic()
    result = await services.sync.reindex()
    elapsed = time.monotonic() - start

    upserted = result.get("upserted", 0)
    dead_letters = result.get("dead_letters", {}) or {}
    attempted = upserted + len(dead_letters)
    seconds_per_fact = (elapsed / attempted) if attempted else None

    return {
        "mode": settings.ingest_mode,
        "total_facts": total_facts,
        "upserted": upserted,
        "deleted": result.get("deleted", 0),
        "dead_letters": dead_letters,
        "dead_letter_count": len(dead_letters),
        "degraded": result.get("degraded"),
        "head": result.get("head"),
        "total_seconds": round(elapsed, 2),
        "seconds_per_fact": round(seconds_per_fact, 2) if seconds_per_fact else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="plk-memory ingest 実測")
    parser.add_argument("--mode", choices=["episode", "triplet"], default=None,
                        help="ingest_mode を上書き（未指定なら settings 既定）")
    parser.add_argument("--out", type=Path, default=None,
                        help="計測結果 JSON の出力先")
    args = parser.parse_args()

    report = asyncio.run(_run(args.mode))

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
