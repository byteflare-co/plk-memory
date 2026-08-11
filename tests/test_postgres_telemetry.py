from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from plk_memory.postgres.telemetry import PostgresTelemetryStore
from plk_memory.telemetry import IntentCommand, TelemetryConflict


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
