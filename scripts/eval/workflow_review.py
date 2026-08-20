#!/usr/bin/env python3
"""Record or summarize local human workflow reviews."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from plk_memory.settings import Settings
from plk_memory.workflow_evaluation import (
    CHROME_PROFILE_PILOT_CASE_ID,
    WorkflowReview,
    append_review,
    load_review_suite,
    load_suite,
    read_reviews,
    summarize_pilot_status,
    summarize_reviews,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("record", "report", "pilot-status"))
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("--store", type=Path, default=Settings().workflow_review_path)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).with_name("workflow_cases.yaml"),
    )
    parser.add_argument(
        "--case-id",
        default=CHROME_PROFILE_PILOT_CASE_ID,
        help="workflow case to evaluate as a pilot",
    )
    parser.add_argument(
        "--aggregate-api-status",
        choices=("healthy", "unavailable"),
        default="healthy",
        help="independent aggregate API health observation",
    )
    parser.add_argument(
        "--private-data-exposure",
        action="store_true",
        help="declare an independently confirmed private-data exposure",
    )
    parser.add_argument(
        "--baseline-unknown-rate",
        type=float,
        help="previous pilot unknown rate; a higher current rate triggers rollback",
    )
    args = parser.parse_args()
    if args.command == "record":
        if args.input is None:
            parser.error("record requires an input JSON file")
        # The evaluator supplies a pre-signed envelope. This runtime has only
        # the public verifier and never signs a human review itself.
        review = WorkflowReview.model_validate_json(
            args.input.read_text(encoding="utf-8")
        )
        settings = Settings()
        append_review(
            args.store, review, suite=load_suite(args.cases), settings=settings
        )
        print(f"recorded: {review.review_id}")
    elif args.command == "report":
        settings = Settings()
        suite = load_review_suite(args.cases)
        print(
            json.dumps(
                summarize_reviews(
                    read_reviews(args.store, suite=suite, settings=settings),
                    suite=suite,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        settings = Settings()
        suite = load_review_suite(args.cases)
        status = summarize_pilot_status(
            read_reviews(args.store, suite=suite, settings=settings),
            suite=suite,
            case_id=args.case_id,
            aggregate_api_status=args.aggregate_api_status,
            private_data_exposure=args.private_data_exposure,
            baseline_unknown_rate=args.baseline_unknown_rate,
        )
        print(json.dumps(status, ensure_ascii=False, indent=2))
        if status["status"] == "ready_for_human_decision":
            return 0
        return 2 if status["status"] == "rollback" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
