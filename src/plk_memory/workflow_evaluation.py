"""Human-reviewed workflow cases and immutable episode records."""

from __future__ import annotations

import fcntl
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

import frontmatter
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from plk_memory.rendering import content_hash
from plk_memory.settings import Settings

StageResult = Literal["pass", "fail", "unknown", "not_applicable"]
FailureStage = Literal[
    "trigger", "retrieval", "knowledge", "application", "action", "evidence"
]
FactId = Annotated[str, Field(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")]


class CaseSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["user_reported_failure", "human_review", "production_incident"]
    reported_on: date
    review_status: Literal["user_reported", "reviewed"]
    evidence_ref: str = Field(min_length=1)


class ExpectedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: FactId
    content_hash: str = Field(pattern=r"^[0-9a-f]{16}$")


class RetrievalRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["all_of", "any_of"]
    facts: list[ExpectedFact] = Field(min_length=1)


class CaseVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    evaluator_input: dict[str, str | list[str]]
    expected_result: str = Field(min_length=1)
    required_evidence_tier: Literal["A"]


class WorkflowCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1)
    status: Literal["pilot", "active", "retired"]
    source: CaseSource
    situation: str = Field(min_length=1)
    memory_expected: bool
    retrieval: RetrievalRequirement | None
    expected_actions: list[str] = Field(min_length=1)
    forbidden_actions: list[str]
    required_evidence: list[str] = Field(min_length=1)
    variants: list[CaseVariant] = Field(min_length=1)
    failure_routing: dict[FailureStage, str]

    @model_validator(mode="after")
    def validate_case(self) -> "WorkflowCase":
        if self.memory_expected and self.retrieval is None:
            raise ValueError("memory_expected=true requires retrieval")
        if not self.memory_expected and self.retrieval is not None:
            raise ValueError("memory_expected=false forbids retrieval")
        if self.retrieval is not None:
            ids = [fact.id for fact in self.retrieval.facts]
            if len(set(ids)) != len(ids):
                raise ValueError("expected fact ids must be unique")
        variant_ids = [variant.id for variant in self.variants]
        if len(set(variant_ids)) != len(variant_ids):
            raise ValueError("variant ids must be unique")
        expected_stages = {
            "trigger",
            "retrieval",
            "knowledge",
            "application",
            "action",
            "evidence",
        }
        if set(self.failure_routing) != expected_stages:
            raise ValueError("failure_routing must define every evaluation stage")
        return self


class WorkflowSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    cases: list[WorkflowCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ids(self) -> "WorkflowSuite":
        ids = [case.id for case in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("workflow case ids must be unique")
        return self


class StageRatings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: StageResult
    retrieval: StageResult
    application: StageResult
    action: StageResult


class EvaluationRevisions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client: str = Field(min_length=1)
    model: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    retriever: str = Field(min_length=1)
    corpus: str = Field(min_length=1)


class WorkflowReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1, max_length=64)
    case_id: str = Field(min_length=1)
    variant_id: str = Field(min_length=1)
    reviewed_at: datetime
    reviewer: str = Field(min_length=1)
    trace_id: str | None = Field(default=None, max_length=64)
    search_ids: list[str] = Field(default_factory=list)
    action_ids: list[str] = Field(default_factory=list)
    ratings: StageRatings
    evidence_tier: Literal["A", "B", "C"]
    evidence_refs: list[str] = Field(min_length=1)
    failure_stage: FailureStage | None = None
    improvement_target: str | None = None
    change_id: str | None = None
    replay_of: str | None = None
    revisions: EvaluationRevisions

    @model_validator(mode="after")
    def validate_review(self) -> "WorkflowReview":
        values = self.ratings.model_dump().values()
        if "fail" in values and self.failure_stage is None:
            raise ValueError("a failed review requires failure_stage")
        if "fail" in values and self.improvement_target is None:
            raise ValueError("a failed review requires improvement_target")
        if "fail" not in values and self.failure_stage is not None:
            raise ValueError("failure_stage is allowed only for a failed review")
        if self.ratings.action == "pass" and self.evidence_tier != "A":
            raise ValueError("action=pass requires Tier A evidence")
        if self.replay_of is not None and self.change_id is None:
            raise ValueError("a replay requires change_id")
        return self


def load_suite(path: Path, *, settings: Settings | None = None) -> WorkflowSuite:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    suite = WorkflowSuite.model_validate(payload)
    validate_suite_corpus(suite, settings=settings or Settings())
    return suite


def validate_suite_corpus(suite: WorkflowSuite, *, settings: Settings) -> None:
    facts: dict[str, tuple[str, str]] = {}
    domains = settings.knowledge_dir / "domains"
    for path in sorted(domains.rglob("*.md")):
        if path.name in {"CONVENTIONS.md", "README.md"}:
            continue
        post = frontmatter.load(path)
        fact_id = post.get("id")
        status = post.get("status", "active")
        if isinstance(fact_id, str) and isinstance(status, str):
            facts[fact_id] = (status, content_hash(post))
    errors: list[str] = []
    for case in suite.cases:
        if case.retrieval is None:
            continue
        for expected in case.retrieval.facts:
            actual = facts.get(expected.id)
            if actual is None:
                errors.append(f"{case.id}: missing expected fact {expected.id}")
            elif actual[0] != "active":
                errors.append(f"{case.id}: invalidated expected fact {expected.id}")
            elif actual[1] != expected.content_hash:
                errors.append(
                    f"{case.id}: changed expected fact {expected.id} "
                    f"({expected.content_hash} != {actual[1]})"
                )
    if errors:
        raise ValueError(
            "workflow cases do not match active corpus:\n- " + "\n- ".join(errors)
        )


def read_reviews(path: Path) -> list[WorkflowReview]:
    if not path.exists():
        return []
    reviews: list[WorkflowReview] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            reviews.append(WorkflowReview.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"invalid workflow review at line {line_number}") from exc
    return reviews


def validate_review_against_suite(review: WorkflowReview, suite: WorkflowSuite) -> None:
    case = next((row for row in suite.cases if row.id == review.case_id), None)
    if case is None:
        raise ValueError(f"unknown workflow case: {review.case_id}")
    if not any(variant.id == review.variant_id for variant in case.variants):
        raise ValueError(
            f"unknown workflow variant: {review.case_id}/{review.variant_id}"
        )


def append_review(
    path: Path,
    review: WorkflowReview,
    *,
    suite: WorkflowSuite | None = None,
) -> None:
    if suite is not None:
        validate_review_against_suite(review, suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        os.chmod(path, 0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        existing = [
            WorkflowReview.model_validate_json(line)
            for line in handle.read().splitlines()
            if line.strip()
        ]
        if any(row.review_id == review.review_id for row in existing):
            raise ValueError(f"duplicate review_id: {review.review_id}")
        if review.replay_of is not None:
            original = next(
                (row for row in existing if row.review_id == review.replay_of), None
            )
            if original is None:
                raise ValueError(f"unknown replay_of: {review.replay_of}")
            if (original.case_id, original.variant_id) != (
                review.case_id,
                review.variant_id,
            ):
                raise ValueError("replay must use the same case and variant")
            if review.reviewed_at <= original.reviewed_at:
                raise ValueError("replay must be reviewed after the original")
            if any(row.replay_of == original.review_id for row in existing):
                raise ValueError(f"review already has a replay: {original.review_id}")
        handle.seek(0, os.SEEK_END)
        handle.write(review.model_dump_json() + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def summarize_reviews(reviews: list[WorkflowReview]) -> dict:
    stage_names = ("trigger", "retrieval", "application", "action")
    stages = {
        name: {
            result: sum(getattr(review.ratings, name) == result for review in reviews)
            for result in ("pass", "fail", "unknown", "not_applicable")
        }
        for name in stage_names
    }

    def is_success(review: WorkflowReview) -> bool:
        return all(
            getattr(review.ratings, name) in {"pass", "not_applicable"}
            for name in stage_names
        )

    def is_evaluable(review: WorkflowReview) -> bool:
        return is_success(review) or any(
            getattr(review.ratings, name) == "fail" for name in stage_names
        )

    def cohort(rows: list[WorkflowReview]) -> dict:
        judged = [review for review in rows if is_evaluable(review)]
        passed = [review for review in judged if is_success(review)]
        return {
            "reviews": len(rows),
            "evaluable": len(judged),
            "unknown": len(rows) - len(judged),
            "successes": len(passed),
            "success_rate": len(passed) / len(judged) if judged else None,
        }

    evaluable = [review for review in reviews if is_evaluable(review)]
    succeeded = [review for review in evaluable if is_success(review)]
    failures: dict[str, int] = {}
    for review in reviews:
        if review.failure_stage is not None:
            failures[review.failure_stage] = failures.get(review.failure_stage, 0) + 1
    originals = {review.review_id: review for review in reviews}
    improvement_pairs = []
    for replay in reviews:
        if replay.replay_of is None or replay.replay_of not in originals:
            continue
        original = originals[replay.replay_of]
        improvement_pairs.append(
            {
                "change_id": replay.change_id,
                "case_id": replay.case_id,
                "variant_id": replay.variant_id,
                "before_review_id": original.review_id,
                "after_review_id": replay.review_id,
                "before_success": is_success(original),
                "after_success": is_success(replay),
                "before_failure_stage": original.failure_stage,
                "after_failure_stage": replay.failure_stage,
                "same_failure_recurred": original.failure_stage is not None
                and original.failure_stage == replay.failure_stage,
                "lead_time_hours": (
                    replay.reviewed_at - original.reviewed_at
                ).total_seconds()
                / 3600,
            }
        )
    failed_pairs = [
        pair for pair in improvement_pairs if pair["before_failure_stage"] is not None
    ]

    def grouped(key):
        values: dict[str, list[WorkflowReview]] = {}
        for review in reviews:
            values.setdefault(str(key(review)), []).append(review)
        return {name: cohort(rows) for name, rows in sorted(values.items())}

    return {
        "reviews": len(reviews),
        "evaluable": len(evaluable),
        "unknown": len(reviews) - len(evaluable),
        "e2e_successes": len(succeeded),
        "e2e_success_rate": len(succeeded) / len(evaluable) if evaluable else None,
        "stages": stages,
        "failure_stages": dict(sorted(failures.items())),
        "by_case": grouped(lambda review: review.case_id),
        "by_client": grouped(lambda review: review.revisions.client),
        "by_week": grouped(
            lambda review: (
                review.reviewed_at.date()
                - timedelta(days=review.reviewed_at.date().weekday())
            )
        ),
        "improvements": {
            "pairs": improvement_pairs,
            "failed_before": len(failed_pairs),
            "same_failure_recurrences": sum(
                bool(pair["same_failure_recurred"]) for pair in failed_pairs
            ),
            "recurrence_rate": (
                sum(bool(pair["same_failure_recurred"]) for pair in failed_pairs)
                / len(failed_pairs)
                if failed_pairs
                else None
            ),
        },
    }
