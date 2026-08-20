#!/usr/bin/env python3
"""Record or summarize local human workflow reviews."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from plk_memory.settings import Settings
from plk_memory.workflow_evaluation import (
    WorkflowReview,
    append_review,
    load_suite,
    read_reviews,
    summarize_reviews,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("record", "report"))
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("--store", type=Path, default=Settings().workflow_review_path)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).with_name("workflow_cases.yaml"),
    )
    args = parser.parse_args()
    if args.command == "record":
        if args.input is None:
            parser.error("record requires an input JSON file")
        review = WorkflowReview.model_validate_json(
            args.input.read_text(encoding="utf-8")
        )
        append_review(args.store, review, suite=load_suite(args.cases))
        print(f"recorded: {review.review_id}")
    else:
        print(
            json.dumps(
                summarize_reviews(read_reviews(args.store)),
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
