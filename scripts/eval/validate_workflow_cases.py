#!/usr/bin/env python3
"""Validate the human-reviewed workflow evaluation case contract."""

from __future__ import annotations

import argparse
from pathlib import Path

from plk_memory.settings import Settings
from plk_memory.workflow_evaluation import load_suite


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "suite_path",
        type=Path,
        nargs="?",
        default=Path(__file__).with_name("workflow_cases.yaml"),
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        help="Root of a disposable corpus containing knowledge/. Defaults to Settings.",
    )
    args = parser.parse_args()
    settings = (
        Settings(data_repo_path=args.corpus_root)
        if args.corpus_root is not None
        else None
    )
    suite = load_suite(args.suite_path, settings=settings)
    active = sum(case.status in {"pilot", "active"} for case in suite.cases)
    variants = sum(len(case.variants) for case in suite.cases)
    print(f"OK: {len(suite.cases)} cases / {variants} variants ({active} active/pilot)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
