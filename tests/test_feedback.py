import asyncio
import json
import os

import pytest

from plk_memory.feedback import (
    CodexFeedbackRunner,
    FeedbackCoordinator,
    FeedbackProposal,
    FeedbackState,
    FeedbackStore,
)


class FakeRunner(CodexFeedbackRunner):
    def __init__(self, proposal: FeedbackProposal):
        self.proposal = proposal

    async def propose(self, *, original: dict, feedback: str) -> FeedbackProposal:
        assert original["statement"]
        assert feedback
        await asyncio.sleep(0)
        return self.proposal


def proposal() -> FeedbackProposal:
    return FeedbackProposal(
        statement="改善後の主張",
        why="改善後の理由",
        how_to_apply="改善後の適用方法",
        tags=["reviewed"],
        body="改善後の本文",
        rationale="条件を明確にした",
    )


async def wait_for_state(
    coordinator: FeedbackCoordinator,
    request_id: str,
    expected: FeedbackState,
) -> None:
    for _ in range(100):
        if coordinator.store.get(request_id).state is expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"feedback request did not reach {expected.value}")


async def test_coordinator_persists_proposal(tmp_path):
    coordinator = FeedbackCoordinator(
        FeedbackStore(tmp_path / "feedback.json"), FakeRunner(proposal())
    )
    request = await coordinator.submit(
        fact_id="fact-1",
        base_content_hash="abc",
        namespace="plk.domain.dev",
        kind="logic",
        source="https://example.com/source",
        original={"statement": "元の主張"},
        feedback="条件を明確にして",
    )
    await wait_for_state(coordinator, request.id, FeedbackState.proposed)
    saved = coordinator.store.get(request.id)
    assert saved.proposal is not None
    assert saved.proposal.statement == "改善後の主張"
    await coordinator.close()


async def test_resume_requeues_running_request(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.json")
    first = FeedbackCoordinator(store, FakeRunner(proposal()))
    request = await first.submit(
        fact_id="fact-1",
        base_content_hash="abc",
        namespace="plk.domain.dev",
        kind="logic",
        source="https://example.com/source",
        original={"statement": "元の主張"},
        feedback="条件を明確にして",
    )
    await first.close()
    stored = store.get(request.id).model_copy(update={"state": FeedbackState.running})
    store.upsert(stored)

    resumed = FeedbackCoordinator(store, FakeRunner(proposal()))
    await resumed.resume_pending()
    await wait_for_state(resumed, request.id, FeedbackState.proposed)
    await resumed.close()


async def test_apply_claim_is_single_winner(tmp_path):
    coordinator = FeedbackCoordinator(
        FeedbackStore(tmp_path / "feedback.json"), FakeRunner(proposal())
    )
    request = await coordinator.submit(
        fact_id="fact-1",
        base_content_hash="abc",
        namespace="plk.domain.dev",
        kind="logic",
        source="https://example.com/source",
        original={"statement": "元の主張"},
        feedback="条件を明確にして",
    )
    await wait_for_state(coordinator, request.id, FeedbackState.proposed)
    claimed = await coordinator.claim_apply(request.id)
    assert claimed.state is FeedbackState.applying
    with pytest.raises(ValueError, match="反映できない状態"):
        await coordinator.claim_apply(request.id)
    await coordinator.close()


async def test_submit_limits_feedback_and_one_active_request_per_fact(tmp_path):
    coordinator = FeedbackCoordinator(
        FeedbackStore(tmp_path / "feedback.json"),
        FakeRunner(proposal()),
        max_feedback_chars=10,
    )
    with pytest.raises(ValueError, match="10文字以内"):
        await coordinator.submit(
            fact_id="fact-1",
            base_content_hash="abc",
            namespace="plk.domain.dev",
            kind="logic",
            source="https://example.com/source",
            original={"statement": "元の主張"},
            feedback="12345678901",
        )
    await coordinator.submit(
        fact_id="fact-1",
        base_content_hash="abc",
        namespace="plk.domain.dev",
        kind="logic",
        source="https://example.com/source",
        original={"statement": "元の主張"},
        feedback="直してください",
    )
    with pytest.raises(ValueError, match="未完了"):
        await coordinator.submit(
            fact_id="fact-1",
            base_content_hash="abc",
            namespace="plk.domain.dev",
            kind="logic",
            source="https://example.com/source",
            original={"statement": "元の主張"},
            feedback="別案もください",
        )
    await coordinator.close()


async def test_resume_returns_interrupted_apply_to_review(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.json")
    coordinator = FeedbackCoordinator(store, FakeRunner(proposal()))
    request = await coordinator.submit(
        fact_id="fact-1",
        base_content_hash="abc",
        namespace="plk.domain.dev",
        kind="logic",
        source="https://example.com/source",
        original={"statement": "元の主張"},
        feedback="条件を明確にして",
    )
    await wait_for_state(coordinator, request.id, FeedbackState.proposed)
    await coordinator.claim_apply(request.id)
    await coordinator.close()

    resumed = FeedbackCoordinator(store, FakeRunner(proposal()))
    await resumed.resume_pending()
    recovered = store.get(request.id)
    assert recovered.state is FeedbackState.proposed
    assert recovered.error is not None
    await resumed.close()


async def test_codex_runner_uses_stdin_and_schema_output(tmp_path):
    fake = tmp_path / "fake-codex"
    fake.write_text(
        """#!/usr/bin/env python3
import json, pathlib, sys
prompt = sys.stdin.read()
assert '<human_feedback>' in prompt
out = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])
out.write_text(json.dumps({
  'statement': 's', 'why': 'w', 'how_to_apply': 'h', 'tags': [],
  'body': '', 'rationale': 'r'
}), encoding='utf-8')
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    runner = CodexFeedbackRunner(
        working_dir=tmp_path, codex_bin=str(fake), timeout_seconds=10
    )
    result = await runner.propose(
        original={"statement": "元"}, feedback="直して; touch /tmp/should-not-run"
    )
    assert result.statement == "s"


async def test_codex_runner_rejects_invalid_schema_output(tmp_path):
    fake = tmp_path / "fake-codex"
    fake.write_text(
        """#!/usr/bin/env python3
import pathlib, sys
out = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])
out.write_text('{}', encoding='utf-8')
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    runner = CodexFeedbackRunner(
        working_dir=tmp_path, codex_bin=str(fake), timeout_seconds=10
    )
    with pytest.raises(Exception):
        await runner.propose(original={"statement": "元"}, feedback="直して")


async def test_codex_runner_cancellation_terminates_process_group(tmp_path):
    pid_path = tmp_path / "child.pid"
    fake = tmp_path / "fake-codex"
    fake.write_text(
        f"""#!/usr/bin/env python3
import os, pathlib, time
pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()), encoding='utf-8')
time.sleep(60)
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    runner = CodexFeedbackRunner(
        working_dir=tmp_path, codex_bin=str(fake), timeout_seconds=120
    )
    task = asyncio.create_task(
        runner.propose(original={"statement": "元"}, feedback="直して")
    )
    for _ in range(100):
        if pid_path.exists():
            break
        await asyncio.sleep(0.01)
    assert pid_path.exists()
    pid = int(pid_path.read_text(encoding="utf-8"))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_feedback_store_json_is_valid(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.json")
    assert store.load() == {}
    assert not store.path.exists()
    store.save({})
    assert json.loads(store.path.read_text(encoding="utf-8")) == {}
