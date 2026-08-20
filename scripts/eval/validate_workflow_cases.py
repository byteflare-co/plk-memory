#!/usr/bin/env python3
"""Validate the human-reviewed workflow evaluation case contract."""

from __future__ import annotations

import argparse
from pathlib import Path
from plk_memory.workflow_evaluation import load_suite


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=Path(__file__).with_name("workflow_cases.yaml"),
    )
    args = parser.parse_args()
    suite = load_suite(args.path)
    active = sum(case.status in {"pilot", "active"} for case in suite.cases)
    variants = sum(len(case.variants) for case in suite.cases)
    print(f"OK: {len(suite.cases)} cases / {variants} variants ({active} active/pilot)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
