"""Human-reviewed workflow cases and immutable episode records."""

from __future__ import annotations

import fcntl
import base64
import hashlib
import json
import os
import stat
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Sequence

import frontmatter
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from plk_memory.rendering import content_hash
from plk_memory.settings import Settings

StageResult = Literal["pass", "fail", "unknown", "not_applicable"]
RatedStage = Literal["trigger", "retrieval", "application", "action"]
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
    required_stages: list[RatedStage] = Field(min_length=1)
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
        if len(set(self.required_stages)) != len(self.required_stages):
            raise ValueError("required stages must be unique")
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


class WorkflowReviewSubmission(BaseModel):
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
    def validate_review(self) -> "WorkflowReviewSubmission":
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
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


class WorkflowReview(WorkflowReviewSubmission):
    """A human-signed review envelope accepted by the runtime."""

    recorded_by: str = Field(min_length=1, max_length=128)
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    attestation: str = Field(min_length=1, max_length=128)


def _workflow_reviewer_verifier(
    settings: Settings,
) -> tuple[str, Ed25519PublicKey, str]:
    """Return the independent human-review trust anchor, or fail closed."""

    reviewer_id = settings.workflow_reviewer_id.strip()
    public_key_text = settings.workflow_reviewer_public_key.strip()
    trusted_head = settings.workflow_review_trusted_head.strip()
    if not reviewer_id or not public_key_text or not trusted_head:
        raise ValueError("workflow reviewer verifier or trusted head is not configured")
    if len(trusted_head) != 64 or any(
        char not in "0123456789abcdef" for char in trusted_head
    ):
        raise ValueError("workflow review trusted head is invalid")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key_text, validate=True)
        )
    except ValueError as exc:
        raise ValueError("workflow reviewer public key is invalid") from exc
    return reviewer_id, public_key, trusted_head


def attestation_payload(review: WorkflowReview) -> bytes:
    return json.dumps(
        review.model_dump(mode="json", exclude={"attestation", "record_hash"}),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def review_record_hash(review: WorkflowReview) -> str:
    return hashlib.sha256(
        json.dumps(
            review.model_dump(mode="json", exclude={"record_hash"}),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _validate_attestation(review: WorkflowReview, *, settings: Settings) -> None:
    reviewer_id, public_key, _ = _workflow_reviewer_verifier(settings)
    if review.recorded_by != reviewer_id or review.record_hash != review_record_hash(
        review
    ):
        raise ValueError("workflow review attestation is invalid")
    try:
        signature = base64.b64decode(review.attestation, validate=True)
        public_key.verify(signature, attestation_payload(review))
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("workflow review attestation is invalid") from exc


def load_suite(path: Path, *, settings: Settings | None = None) -> WorkflowSuite:
    suite = load_review_suite(path)
    validate_suite_corpus(suite, settings=settings or Settings())
    return suite


def load_review_suite(path: Path) -> WorkflowSuite:
    """Load only the case/variant contract; never inspect a live knowledge corpus."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return WorkflowSuite.model_validate(payload)


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


def _open_review_store(path: Path, *, write: bool) -> int | None:
    """Open the private JSONL store without following links or accepting devices.

    A review store is an append-only audit input.  Returning a partial result from
    an unexpected file type or permissive file would make the evaluation look
    healthier than its evidence allows, so every such condition is rejected.
    """

    flags = os.O_RDWR if write else os.O_RDONLY
    if write:
        flags |= os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("workflow review store is not a safe regular file") from exc

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("workflow review store must be a regular file")
        if metadata.st_mode & 0o077:
            raise ValueError("workflow review store must have mode 0600")
        if write:
            os.fchmod(descriptor, 0o600)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _parse_reviews(lines: list[str]) -> list[WorkflowReview]:
    reviews: list[WorkflowReview] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            reviews.append(WorkflowReview.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"invalid workflow review at line {line_number}") from exc
    return reviews


def _validate_review_history(
    reviews: list[WorkflowReview], *, trusted_head: str
) -> None:
    """Validate semantic history and the independently configured chain head."""
    seen: dict[str, WorkflowReview] = {}
    replayed: set[str] = set()
    previous_hash = "0" * 64
    for review in reviews:
        if review.previous_hash != previous_hash:
            raise ValueError("workflow review chain is broken")
        if review.review_id in seen:
            raise ValueError(f"duplicate review_id: {review.review_id}")
        if review.replay_of is not None:
            original = seen.get(review.replay_of)
            if original is None:
                raise ValueError(f"unknown replay_of: {review.replay_of}")
            if (original.case_id, original.variant_id) != (
                review.case_id,
                review.variant_id,
            ):
                raise ValueError("replay must use the same case and variant")
            if review.reviewed_at <= original.reviewed_at:
                raise ValueError("replay must be reviewed after the original")
            if original.review_id in replayed:
                raise ValueError(f"review already has a replay: {original.review_id}")
            replayed.add(original.review_id)
        seen[review.review_id] = review
        previous_hash = review.record_hash
    if previous_hash != trusted_head:
        raise ValueError("workflow review trusted head does not match store")


def read_reviews(
    path: Path, *, suite: WorkflowSuite | None = None, settings: Settings
) -> list[WorkflowReview]:
    _, _, trusted_head = _workflow_reviewer_verifier(settings)
    descriptor = _open_review_store(path, write=False)
    if descriptor is None:
        if trusted_head != "0" * 64:
            raise ValueError("workflow review trusted head does not match store")
        return []
    with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
        reviews = _parse_reviews(handle.read().splitlines())
    for review in reviews:
        _validate_attestation(review, settings=settings)
    _validate_review_history(reviews, trusted_head=trusted_head)
    if suite is not None:
        for review in reviews:
            validate_review_against_suite(review, suite)
    return reviews


def validate_review_against_suite(
    review: WorkflowReviewSubmission, suite: WorkflowSuite
) -> None:
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
    suite: WorkflowSuite,
    settings: Settings,
) -> None:
    """Append an envelope already signed by the human-controlled reviewer path.

    This process deliberately has no signing credential and does not manufacture
    review envelopes. The caller must provide the exact next chain link, and the
    separately configured trusted head must agree with the on-disk history.
    """
    if not isinstance(review, WorkflowReview):
        raise ValueError("workflow review must be a pre-signed envelope")
    validate_review_against_suite(review, suite)
    _validate_attestation(review, settings=settings)
    _, _, trusted_head = _workflow_reviewer_verifier(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = _open_review_store(path, write=True)
    if descriptor is None:  # pragma: no cover - write=True creates the file
        raise ValueError("workflow review store could not be created")
    with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        existing = _parse_reviews(handle.read().splitlines())
        for existing_review in existing:
            _validate_attestation(existing_review, settings=settings)
        _validate_review_history(existing, trusted_head=trusted_head)
        current_head = existing[-1].record_hash if existing else "0" * 64
        if review.previous_hash != current_head:
            raise ValueError("workflow review does not extend the current chain")
        _validate_review_history(existing + [review], trusted_head=review.record_hash)
        for existing_review in existing:
            validate_review_against_suite(existing_review, suite)
        handle.seek(0, os.SEEK_END)
        handle.write(review.model_dump_json() + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def summarize_reviews(
    reviews: Sequence[WorkflowReviewSubmission], *, suite: WorkflowSuite
) -> dict:
    stage_names = ("trigger", "retrieval", "application", "action")
    stages = {
        name: {
            result: sum(getattr(review.ratings, name) == result for review in reviews)
            for result in ("pass", "fail", "unknown", "not_applicable")
        }
        for name in stage_names
    }

    def required_stages(review: WorkflowReviewSubmission) -> list[RatedStage]:
        case = next((case for case in suite.cases if case.id == review.case_id), None)
        if case is None:
            raise ValueError(f"unknown workflow case: {review.case_id}")
        return case.required_stages

    def is_success(review: WorkflowReviewSubmission) -> bool:
        return all(
            getattr(review.ratings, name) == "pass" for name in required_stages(review)
        )

    def is_evaluable(review: WorkflowReviewSubmission) -> bool:
        return is_success(review) or any(
            getattr(review.ratings, name) == "fail" for name in required_stages(review)
        )

    def cohort(rows: Sequence[WorkflowReviewSubmission]) -> dict:
        judged = [review for review in rows if is_evaluable(review)]
        passed = [review for review in judged if is_success(review)]
        return {
            "status": "ok" if judged else "insufficient_data",
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
        values: dict[str, list[WorkflowReviewSubmission]] = {}
        for review in reviews:
            values.setdefault(str(key(review)), []).append(review)
        return {name: cohort(rows) for name, rows in sorted(values.items())}

    return {
        "status": "ok" if evaluable else "insufficient_data",
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
            "reviewed_replays": len(improvement_pairs),
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
            "lead_time_hours": {
                "count": len(improvement_pairs),
                "average": (
                    sum(pair["lead_time_hours"] for pair in improvement_pairs)
                    / len(improvement_pairs)
                    if improvement_pairs
                    else None
                ),
            },
        },
    }
