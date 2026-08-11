from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from plk_memory.postgres.telemetry import PostgresTelemetryStore
from plk_memory.telemetry import (
    ActionCommand,
    IntentCommand,
    TelemetryConflict,
    TelemetryError,
)


class _Result:
    def __init__(self, row=None):
        self._row = row

    def one_or_none(self):
        return self._row


class _Session:
    def __init__(self, outcomes):
        self._outcomes = iter(outcomes)

    async def execute(self, _statement, _params=None):
        outcome = next(self._outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return _Result(outcome)


class _Database:
    def __init__(self, sessions):
        self._sessions = iter(sessions)

    @asynccontextmanager
    async def transaction(self, _organization_id):
        yield next(self._sessions)


def _command():
    return IntentCommand(
        trace_id="T1",
        operation_type="browser_read",
        intent="read page",
        side_effect="read",
        plk_requirement="optional",
    )


def _action(**updates):
    values = {
        "event_id": "E1",
        "action_id": "A1",
        "trace_id": "T1",
        "phase": "attempted",
        "action_type": "browser_navigate",
        "side_effect": "read",
        "outcome": "pending",
    }
    values.update(updates)
    return ActionCommand.model_validate(values)


async def test_postgres_intent_concurrent_exact_retry_is_replay():
    command = _command()
    database = _Database(
        [
            _Session(
                [
                    None,
                    IntegrityError("insert intent", {}, RuntimeError("duplicate")),
                ]
            ),
            _Session(
                [SimpleNamespace(request_hash=command.request_hash(), client="codex")]
            ),
        ]
    )
    store = PostgresTelemetryStore(cast(Any, database), organization_provider=uuid4)

    result = await store.record_intent(client="codex", command=command)

    assert result == {"recorded": True, "replayed": True, "trace_id": "T1"}


async def test_postgres_intent_concurrent_mismatch_is_conflict():
    command = _command()
    database = _Database(
        [
            _Session(
                [
                    None,
                    IntegrityError("insert intent", {}, RuntimeError("duplicate")),
                ]
            ),
            _Session([SimpleNamespace(request_hash="different", client="codex")]),
        ]
    )
    store = PostgresTelemetryStore(cast(Any, database), organization_provider=uuid4)

    with pytest.raises(TelemetryConflict, match="created concurrently"):
        await store.record_intent(client="codex", command=command)


async def test_postgres_action_records_attempt_then_completion():
    attempted = _action()
    completed = _action(event_id="E2", phase="completed", outcome="succeeded")
    database = _Database(
        [
            _Session(
                [
                    None,
                    SimpleNamespace(trace_id="T1", side_effect="read"),
                    None,
                ]
            ),
            _Session(
                [
                    None,
                    SimpleNamespace(trace_id="T1", side_effect="read"),
                    SimpleNamespace(event_id="E1"),
                    None,
                ]
            ),
        ]
    )
    store = PostgresTelemetryStore(cast(Any, database), organization_provider=uuid4)

    assert await store.record_action(client="codex", command=attempted) == {
        "recorded": True,
        "replayed": False,
        "event_id": "E1",
    }
    assert await store.record_action(client="codex", command=completed) == {
        "recorded": True,
        "replayed": False,
        "event_id": "E2",
    }


async def test_postgres_action_replays_matching_concurrent_event():
    command = _action()
    database = _Database(
        [
            _Session(
                [
                    None,
                    SimpleNamespace(trace_id="T1", side_effect="read"),
                    IntegrityError("insert action", {}, RuntimeError("duplicate")),
                ]
            ),
            _Session(
                [SimpleNamespace(request_hash=command.request_hash(), client="codex")]
            ),
        ]
    )
    store = PostgresTelemetryStore(cast(Any, database), organization_provider=uuid4)

    assert await store.record_action(client="codex", command=command) == {
        "recorded": True,
        "replayed": True,
        "event_id": "E1",
    }


async def test_postgres_action_rejects_concurrent_event_with_different_content():
    command = _action()
    database = _Database(
        [
            _Session(
                [
                    None,
                    SimpleNamespace(trace_id="T1", side_effect="read"),
                    IntegrityError("insert action", {}, RuntimeError("duplicate")),
                ]
            ),
            _Session([SimpleNamespace(request_hash="different", client="codex")]),
        ]
    )
    store = PostgresTelemetryStore(cast(Any, database), organization_provider=uuid4)

    with pytest.raises(TelemetryConflict, match="created concurrently"):
        await store.record_action(client="codex", command=command)


async def test_postgres_action_rejects_side_effect_and_trace_client_boundaries():
    side_effect_store = PostgresTelemetryStore(
        cast(
            Any,
            _Database(
                [
                    _Session(
                        [
                            None,
                            SimpleNamespace(trace_id="T1", side_effect="local_write"),
                        ]
                    )
                ]
            ),
        ),
        organization_provider=uuid4,
    )
    with pytest.raises(TelemetryError, match="side_effect must match"):
        await side_effect_store.record_action(client="codex", command=_action())

    foreign_trace_store = PostgresTelemetryStore(
        cast(Any, _Database([_Session([None, None])])),
        organization_provider=uuid4,
    )
    with pytest.raises(TelemetryError, match="unknown trace_id"):
        await foreign_trace_store.record_action(client="codex", command=_action())
