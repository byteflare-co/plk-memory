from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
import base64
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plk_memory.settings import Settings
from plk_memory.workflow_evaluation import (
    EvaluationRevisions,
    StageRatings,
    WorkflowReviewSubmission,
    WorkflowReview,
    WorkflowSuite,
    append_review,
    load_review_suite,
    load_suite,
    read_reviews,
    summarize_reviews,
    attestation_payload,
    review_record_hash,
    validate_suite_corpus,
    validate_review_against_suite,
)


def _case_path() -> Path:
    return Path(__file__).parents[1] / "scripts" / "eval" / "workflow_cases.yaml"


def _fixture_case_path() -> Path:
    return (
        Path(__file__).parent
        / "fixtures"
        / "workflow_evaluation"
        / "workflow_cases.yaml"
    )


def _fixture_corpus_path() -> Path:
    return Path(__file__).parent / "fixtures" / "workflow_evaluation" / "corpus"


def _repository_suite() -> WorkflowSuite:
    return WorkflowSuite.model_validate(
        yaml.safe_load(_case_path().read_text(encoding="utf-8"))
    )


def _fixture_suite():
    return load_suite(
        _fixture_case_path(), settings=Settings(data_repo_path=_fixture_corpus_path())
    )


_TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
_TEST_PUBLIC_KEY = base64.b64encode(
    _TEST_PRIVATE_KEY.public_key().public_bytes_raw()
).decode("ascii")


def _review_settings(*, head: str = "0" * 64) -> Settings:
    return Settings(
        workflow_reviewer_id="test-human-reviewer",
        workflow_reviewer_public_key=_TEST_PUBLIC_KEY,
        workflow_review_trusted_head=head,
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


def _review(**updates) -> WorkflowReviewSubmission:
    values = {
        "review_id": "R1",
        "case_id": "browser-byteflare-profile-selection",
        "variant_id": "unique-match",
        "reviewed_at": datetime.now(timezone.utc),
        "reviewer": "human",
        "ratings": StageRatings(
            trigger="pass", retrieval="pass", application="pass", action="pass"
        ),
        "evidence_tier": "A",
        "evidence_refs": ["trace:T1", "browser-readback:E1"],
        "revisions": EvaluationRevisions(
            client="codex@1",
            model="gpt@1",
            instruction="agents@1",
            retriever="graph@1",
            corpus="git@1",
        ),
    }
    values.update(updates)
    return WorkflowReviewSubmission.model_validate(values)


def _signed_review(
    review: WorkflowReviewSubmission, *, previous_hash: str = "0" * 64
) -> WorkflowReview:
    unsigned = WorkflowReview.model_validate(
        {
            **review.model_dump(),
            "recorded_by": "test-human-reviewer",
            "previous_hash": previous_hash,
            "record_hash": "0" * 64,
            "attestation": "placeholder",
        }
    )
    signed = unsigned.model_copy(
        update={
            "attestation": base64.b64encode(
                _TEST_PRIVATE_KEY.sign(attestation_payload(unsigned))
            ).decode("ascii")
        }
    )
    return signed.model_copy(update={"record_hash": review_record_hash(signed)})


def _append(
    path: Path,
    review: WorkflowReviewSubmission,
    *,
    suite: WorkflowSuite,
    settings: Settings,
) -> WorkflowReview:
    envelope = _signed_review(
        review, previous_hash=settings.workflow_review_trusted_head
    )
    append_review(path, envelope, suite=suite, settings=settings)
    # The trusted checkpoint is deliberately outside the JSONL store. Tests
    # emulate the human-controlled evaluator advancing it after acceptance.
    settings.workflow_review_trusted_head = envelope.record_hash
    return envelope


def test_repository_workflow_cases_are_structurally_valid():
    suite = _repository_suite()

    assert suite.version == 1
    assert suite.cases[0].id == "browser-byteflare-profile-selection"
    assert suite.cases[0].retrieval is not None
    assert suite.cases[0].retrieval.mode == "all_of"
    assert len(suite.cases[0].variants) == 4


def test_workflow_cases_fail_closed_for_duplicate_case_id():
    payload = yaml.safe_load(_case_path().read_text(encoding="utf-8"))
    payload["cases"].append(deepcopy(payload["cases"][0]))

    with pytest.raises(ValidationError, match="workflow case ids must be unique"):
        WorkflowSuite.model_validate(payload)


def test_workflow_cases_fail_closed_for_duplicate_variant_id():
    payload = yaml.safe_load(_case_path().read_text(encoding="utf-8"))
    payload["cases"][0]["variants"].append(deepcopy(payload["cases"][0]["variants"][0]))

    with pytest.raises(ValidationError, match="variant ids must be unique"):
        WorkflowSuite.model_validate(payload)


def test_workflow_cases_fail_closed_for_missing_fact(tmp_path):
    suite = _fixture_suite()

    with pytest.raises(ValueError, match="missing expected fact"):
        validate_suite_corpus(suite, settings=Settings(data_repo_path=tmp_path))


def _write_minimal_fact(root: Path, fact_id: str, status: str) -> None:
    path = root / "knowledge" / "domains" / "agent" / f"{fact_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: {fact_id}\n"
        f"status: {status}\n"
        "statement: test\n"
        "why: test\n"
        "how_to_apply: test\n"
        "---\n",
        encoding="utf-8",
    )


def test_workflow_cases_fail_closed_for_invalidated_fact(tmp_path):
    suite = _fixture_suite()
    assert suite.cases[0].retrieval is not None
    _write_minimal_fact(tmp_path, suite.cases[0].retrieval.facts[0].id, "invalidated")

    with pytest.raises(ValueError, match="invalidated expected fact"):
        validate_suite_corpus(suite, settings=Settings(data_repo_path=tmp_path))


def test_workflow_cases_fail_closed_for_changed_fact(tmp_path):
    suite = _fixture_suite()
    assert suite.cases[0].retrieval is not None
    for fact in suite.cases[0].retrieval.facts:
        _write_minimal_fact(tmp_path, fact.id, "active")

    with pytest.raises(ValueError, match="changed expected fact"):
        validate_suite_corpus(suite, settings=Settings(data_repo_path=tmp_path))


def test_action_pass_requires_tier_a_evidence():
    with pytest.raises(ValidationError, match="Tier A"):
        _review(evidence_tier="B")


def test_failed_review_requires_failure_stage():
    with pytest.raises(ValidationError, match="requires failure_stage"):
        _review(
            ratings=StageRatings(
                trigger="pass",
                retrieval="fail",
                application="unknown",
                action="unknown",
            )
        )


def test_failed_review_requires_improvement_target():
    with pytest.raises(ValidationError, match="requires improvement_target"):
        _review(
            ratings=StageRatings(
                trigger="pass",
                retrieval="fail",
                application="unknown",
                action="unknown",
            ),
            failure_stage="retrieval",
        )


def test_review_must_reference_a_known_case_and_variant(tmp_path):
    suite = _repository_suite()
    settings = _review_settings()

    with pytest.raises(ValueError, match="unknown workflow variant"):
        validate_review_against_suite(_review(variant_id="missing"), suite)

    with pytest.raises(ValueError, match="unknown workflow variant"):
        append_review(
            tmp_path / "reviews.jsonl",
            _signed_review(_review(variant_id="missing")),
            suite=suite,
            settings=settings,
        )


def test_review_store_is_append_only_and_summarized(tmp_path):
    path = tmp_path / "reviews.jsonl"
    suite = _repository_suite()
    settings = _review_settings()
    _append(path, _review(), suite=suite, settings=settings)

    with pytest.raises(ValueError, match="duplicate review_id"):
        _append(path, _review(), suite=suite, settings=settings)

    reviews = read_reviews(path, settings=settings)
    assert path.stat().st_mode & 0o777 == 0o600
    summary = summarize_reviews(reviews, suite=suite)
    assert summary["reviews"] == 1
    assert summary["e2e_success_rate"] == 1.0
    assert summary["by_case"]["browser-byteflare-profile-selection"]["evaluable"] == 1
    assert summary["by_client"]["codex@1"]["success_rate"] == 1.0
    assert summary["improvements"]["reviewed_replays"] == 0
    assert summary["improvements"]["lead_time_hours"] == {
        "count": 0,
        "average": None,
    }


def test_review_recording_requires_configured_human_reviewer(tmp_path):
    with pytest.raises(ValueError, match="verifier or trusted head is not configured"):
        append_review(
            tmp_path / "reviews.jsonl",
            _signed_review(_review()),
            suite=_repository_suite(),
            settings=Settings(_env_file=None),  # pyright: ignore[reportCallIssue]
        )


def test_runtime_rejects_unsigned_review_submission(tmp_path):
    with pytest.raises(ValueError, match="pre-signed envelope"):
        append_review(
            tmp_path / "reviews.jsonl",
            _review(),  # type: ignore[arg-type]
            suite=_repository_suite(),
            settings=_review_settings(),
        )


def test_untrusted_append_and_tampered_review_cannot_be_aggregated(tmp_path):
    path = tmp_path / "reviews.jsonl"
    suite = _repository_suite()
    trusted = _review_settings()
    foreign = _review_settings()
    foreign.workflow_reviewer_public_key = base64.b64encode(b"x" * 32).decode("ascii")
    with pytest.raises(ValueError, match="attestation is invalid"):
        append_review(path, _signed_review(_review()), suite=suite, settings=foreign)
    _append(path, _review(), suite=suite, settings=trusted)
    assert len(read_reviews(path, suite=suite, settings=trusted)) == 1

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["reviewer"] = "tampered"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="attestation is invalid"):
        read_reviews(path, suite=suite, settings=trusted)


def test_no_reviews_is_insufficient_data_not_zero_percent():
    summary = summarize_reviews([], suite=_repository_suite())
    assert summary["status"] == "insufficient_data"
    assert summary["e2e_success_rate"] is None


def test_required_action_not_applicable_is_not_an_e2e_success():
    with pytest.raises(ValueError, match="required stage cannot be not_applicable"):
        summarize_reviews(
            [
                _review(
                    ratings=StageRatings(
                        trigger="pass",
                        retrieval="pass",
                        application="pass",
                        action="not_applicable",
                    )
                )
            ],
            suite=_repository_suite(),
        )


def test_optional_stage_not_applicable_does_not_block_e2e_success():
    payload = _repository_suite().model_dump()
    payload["cases"][0]["memory_expected"] = False
    payload["cases"][0]["retrieval"] = None
    payload["cases"][0]["required_stages"] = ["action"]
    suite = WorkflowSuite.model_validate(payload)

    summary = summarize_reviews(
        [
            _review(
                ratings=StageRatings(
                    trigger="pass",
                    retrieval="not_applicable",
                    application="pass",
                    action="pass",
                )
            )
        ],
        suite=suite,
    )

    assert summary["evaluable"] == 1
    assert summary["e2e_successes"] == 1
    assert summary["e2e_success_rate"] == 1.0


def test_workflow_case_requires_action_and_memory_stages_when_expected():
    payload = _repository_suite().model_dump()
    payload["cases"][0]["required_stages"] = ["trigger", "retrieval", "application"]

    with pytest.raises(ValidationError, match="action must be required"):
        WorkflowSuite.model_validate(payload)

    payload = _repository_suite().model_dump()
    payload["cases"][0]["required_stages"] = ["trigger", "application", "action"]

    with pytest.raises(
        ValidationError, match="requires trigger, retrieval, and application"
    ):
        WorkflowSuite.model_validate(payload)


def test_review_ratings_must_match_the_case_contract():
    suite = _repository_suite()

    with pytest.raises(ValueError, match="required stage cannot be not_applicable"):
        validate_review_against_suite(
            _review(
                ratings=StageRatings(
                    trigger="pass",
                    retrieval="not_applicable",
                    application="pass",
                    action="pass",
                )
            ),
            suite,
        )

    with pytest.raises(ValueError, match="failure_stage must match a failed rating"):
        validate_review_against_suite(
            _review(
                ratings=StageRatings(
                    trigger="pass", retrieval="fail", application="pass", action="pass"
                ),
                failure_stage="action",
                improvement_target="retriever",
            ),
            suite,
        )


def test_optional_stage_failure_is_evaluable_e2e_failure():
    payload = _repository_suite().model_dump()
    payload["cases"][0]["memory_expected"] = False
    payload["cases"][0]["retrieval"] = None
    payload["cases"][0]["required_stages"] = ["action"]
    suite = WorkflowSuite.model_validate(payload)

    summary = summarize_reviews(
        [
            _review(
                ratings=StageRatings(
                    trigger="fail",
                    retrieval="not_applicable",
                    application="not_applicable",
                    action="pass",
                ),
                failure_stage="trigger",
                improvement_target="preflight",
            )
        ],
        suite=suite,
    )

    assert summary["status"] == "ok"
    assert summary["evaluable"] == 1
    assert summary["unknown"] == 0
    assert summary["e2e_successes"] == 0
    assert summary["e2e_success_rate"] == 0.0


def test_unknown_only_review_is_insufficient_data():
    payload = _repository_suite().model_dump()
    payload["cases"][0]["memory_expected"] = False
    payload["cases"][0]["retrieval"] = None
    payload["cases"][0]["required_stages"] = ["action"]
    suite = WorkflowSuite.model_validate(payload)

    summary = summarize_reviews(
        [
            _review(
                ratings=StageRatings(
                    trigger="not_applicable",
                    retrieval="not_applicable",
                    application="not_applicable",
                    action="unknown",
                )
            )
        ],
        suite=suite,
    )

    assert summary["status"] == "insufficient_data"
    assert summary["evaluable"] == 0
    assert summary["unknown"] == 1


def test_replay_requires_existing_same_case_variant_and_is_summarized(tmp_path):
    path = tmp_path / "reviews.jsonl"
    suite = _repository_suite()
    settings = _review_settings()
    before = _review(
        ratings=StageRatings(
            trigger="fail", retrieval="unknown", application="unknown", action="unknown"
        ),
        failure_stage="trigger",
        improvement_target="browser preflight",
    )
    _append(path, before, suite=suite, settings=settings)
    after = _review(
        review_id="R2",
        reviewed_at=before.reviewed_at + timedelta(hours=4),
        replay_of="R1",
        change_id="change-1",
    )
    _append(path, after, suite=suite, settings=settings)

    summary = summarize_reviews(
        read_reviews(path, settings=settings), suite=_repository_suite()
    )
    assert summary["improvements"]["recurrence_rate"] == 0.0
    assert summary["improvements"]["reviewed_replays"] == 1
    assert summary["improvements"]["lead_time_hours"] == {
        "count": 1,
        "average": 4.0,
    }


def test_replay_rejects_unknown_or_duplicate_original(tmp_path):
    path = tmp_path / "reviews.jsonl"
    suite = _repository_suite()
    settings = _review_settings()
    unknown = _review(review_id="R2", replay_of="missing", change_id="change-1")
    with pytest.raises(ValueError, match="unknown replay_of"):
        _append(path, unknown, suite=suite, settings=settings)

    original = _review()
    _append(path, original, suite=suite, settings=settings)
    replay = _review(
        review_id="R2",
        reviewed_at=original.reviewed_at + timedelta(hours=1),
        replay_of="R1",
        change_id="change-1",
    )
    _append(path, replay, suite=suite, settings=settings)
    with pytest.raises(ValueError, match="already has a replay"):
        _append(
            path,
            _review(
                review_id="R3",
                reviewed_at=original.reviewed_at + timedelta(hours=2),
                replay_of="R1",
                change_id="change-2",
            ),
            suite=suite,
            settings=settings,
        )


def test_read_review_store_rejects_unsafe_files_and_malformed_history(tmp_path):
    settings = _review_settings()
    store = tmp_path / "reviews.jsonl"
    store.write_text("not-json\n", encoding="utf-8")
    os.chmod(store, 0o600)
    with pytest.raises(ValueError, match="invalid workflow review"):
        read_reviews(store, settings=settings)

    store.write_text(
        _signed_review(_review()).model_dump_json() + "\n",
        encoding="utf-8",
    )
    os.chmod(store, 0o644)
    with pytest.raises(ValueError, match="mode 0600"):
        read_reviews(store, settings=settings)

    regular = tmp_path / "regular.jsonl"
    regular.write_text(
        _signed_review(_review()).model_dump_json() + "\n",
        encoding="utf-8",
    )
    os.chmod(regular, 0o600)
    link = tmp_path / "link.jsonl"
    link.symlink_to(regular)
    with pytest.raises(ValueError, match="safe regular file"):
        read_reviews(link, settings=settings)

    directory = tmp_path / "directory.jsonl"
    directory.mkdir()
    with pytest.raises(ValueError, match="safe regular file|regular file"):
        read_reviews(directory, settings=settings)


def test_read_review_store_rejects_duplicate_and_invalid_replay_history(tmp_path):
    settings = _review_settings()
    store = tmp_path / "reviews.jsonl"
    first = _review()
    duplicate = _review()
    first_envelope = _signed_review(first)
    duplicate_envelope = _signed_review(
        duplicate, previous_hash=first_envelope.record_hash
    )
    settings.workflow_review_trusted_head = duplicate_envelope.record_hash
    store.write_text(
        first_envelope.model_dump_json()
        + "\n"
        + duplicate_envelope.model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    os.chmod(store, 0o600)
    with pytest.raises(ValueError, match="duplicate review_id"):
        read_reviews(store, settings=settings)

    backwards = _review(
        review_id="R2",
        replay_of="R1",
        change_id="change-1",
        reviewed_at=first.reviewed_at - timedelta(hours=1),
    )
    backwards_envelope = _signed_review(
        backwards, previous_hash=first_envelope.record_hash
    )
    settings.workflow_review_trusted_head = backwards_envelope.record_hash
    store.write_text(
        first_envelope.model_dump_json()
        + "\n"
        + backwards_envelope.model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    os.chmod(store, 0o600)
    with pytest.raises(ValueError, match="replay must be reviewed after"):
        read_reviews(store, settings=settings)


def test_reader_rejects_deleted_or_rolled_back_trusted_chain_head(tmp_path):
    store = tmp_path / "reviews.jsonl"
    first = _signed_review(_review())
    second = _signed_review(_review(review_id="R2"), previous_hash=first.record_hash)
    store.write_text(
        first.model_dump_json() + "\n" + second.model_dump_json() + "\n",
        encoding="utf-8",
    )
    os.chmod(store, 0o600)
    trusted = _review_settings(head=second.record_hash)
    assert len(read_reviews(store, settings=trusted)) == 2

    # A store rollback/deletion cannot satisfy the separately held expected head.
    store.write_text(first.model_dump_json() + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="trusted head does not match store"):
        read_reviews(store, settings=trusted)

    store.unlink()
    with pytest.raises(ValueError, match="trusted head does not match store"):
        read_reviews(store, settings=trusted)


def test_review_suite_contract_can_load_without_live_corpus_access():
    suite = load_review_suite(_case_path())
    assert suite.cases[0].id == "browser-byteflare-profile-selection"
