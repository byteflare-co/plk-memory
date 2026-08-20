from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from plk_memory.settings import Settings
from plk_memory.workflow_evaluation import (
    EvaluationRevisions,
    StageRatings,
    WorkflowReviewSubmission,
    attest_review,
    WorkflowSuite,
    append_review,
    load_review_suite,
    load_suite,
    read_reviews,
    summarize_reviews,
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


def _review_settings(*, token: str = "synthetic-review-token") -> Settings:
    return Settings(
        workflow_reviewer_id="test-human-reviewer",
        workflow_reviewer_token=token,
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
            _review(variant_id="missing"),
            suite=suite,
            settings=settings,
        )


def test_review_store_is_append_only_and_summarized(tmp_path):
    path = tmp_path / "reviews.jsonl"
    suite = _repository_suite()
    settings = _review_settings()
    append_review(path, _review(), suite=suite, settings=settings)

    with pytest.raises(ValueError, match="duplicate review_id"):
        append_review(path, _review(), suite=suite, settings=settings)

    reviews = read_reviews(path, settings=settings)
    assert path.stat().st_mode & 0o777 == 0o600
    summary = summarize_reviews(reviews)
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
    with pytest.raises(ValueError, match="credential is not configured"):
        append_review(
            tmp_path / "reviews.jsonl",
            _review(),
            suite=_repository_suite(),
            settings=Settings(_env_file=None),  # pyright: ignore[reportCallIssue]
        )


def test_untrusted_append_and_tampered_review_cannot_be_aggregated(tmp_path):
    path = tmp_path / "reviews.jsonl"
    suite = _repository_suite()
    trusted = _review_settings()
    append_review(
        path, _review(), suite=suite, settings=_review_settings(token="other")
    )
    with pytest.raises(ValueError, match="attestation is invalid"):
        read_reviews(path, suite=suite, settings=trusted)

    path.unlink()
    append_review(path, _review(), suite=suite, settings=trusted)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["reviewer"] = "tampered"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="attestation is invalid"):
        read_reviews(path, suite=suite, settings=trusted)


def test_no_reviews_is_insufficient_data_not_zero_percent():
    summary = summarize_reviews([])
    assert summary["status"] == "insufficient_data"
    assert summary["e2e_success_rate"] is None


def test_required_action_not_applicable_is_not_an_e2e_success():
    summary = summarize_reviews(
        [
            _review(
                ratings=StageRatings(
                    trigger="pass",
                    retrieval="pass",
                    application="pass",
                    action="not_applicable",
                )
            )
        ]
    )

    assert summary["status"] == "insufficient_data"
    assert summary["evaluable"] == 0
    assert summary["unknown"] == 1
    assert summary["e2e_successes"] == 0
    assert summary["e2e_success_rate"] is None
    assert summary["by_case"]["browser-byteflare-profile-selection"] == {
        "status": "insufficient_data",
        "reviews": 1,
        "evaluable": 0,
        "unknown": 1,
        "successes": 0,
        "success_rate": None,
    }


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
    append_review(path, before, suite=suite, settings=settings)
    after = _review(
        review_id="R2",
        reviewed_at=before.reviewed_at + timedelta(hours=4),
        replay_of="R1",
        change_id="change-1",
    )
    append_review(path, after, suite=suite, settings=settings)

    summary = summarize_reviews(read_reviews(path, settings=settings))
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
        append_review(path, unknown, suite=suite, settings=settings)

    original = _review()
    append_review(path, original, suite=suite, settings=settings)
    replay = _review(
        review_id="R2",
        reviewed_at=original.reviewed_at + timedelta(hours=1),
        replay_of="R1",
        change_id="change-1",
    )
    append_review(path, replay, suite=suite, settings=settings)
    with pytest.raises(ValueError, match="already has a replay"):
        append_review(
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
        attest_review(_review(), settings=settings).model_dump_json() + "\n",
        encoding="utf-8",
    )
    os.chmod(store, 0o644)
    with pytest.raises(ValueError, match="mode 0600"):
        read_reviews(store, settings=settings)

    regular = tmp_path / "regular.jsonl"
    regular.write_text(
        attest_review(_review(), settings=settings).model_dump_json() + "\n",
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
    store.write_text(
        attest_review(first, settings=settings).model_dump_json()
        + "\n"
        + attest_review(duplicate, settings=settings).model_dump_json()
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
    store.write_text(
        attest_review(first, settings=settings).model_dump_json()
        + "\n"
        + attest_review(backwards, settings=settings).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    os.chmod(store, 0o600)
    with pytest.raises(ValueError, match="replay must be reviewed after"):
        read_reviews(store, settings=settings)


def test_review_suite_contract_can_load_without_live_corpus_access():
    suite = load_review_suite(_case_path())
    assert suite.cases[0].id == "browser-byteflare-profile-selection"
