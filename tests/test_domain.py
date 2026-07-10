from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from plk_memory.domain import FactPayload, FactRecord
from plk_memory.ports import RevisionConflict


ORG_ID = UUID("11111111-1111-4111-8111-111111111111")


def test_fact_record_is_storage_neutral_and_immutable():
    now = datetime.now(timezone.utc)
    payload = FactPayload(
        kind="logic",
        statement="複数writerではtransactionalな正本を利用する",
        why="同時更新時のlost updateとtenant越境をDB制約で防止するため",
        how_to_apply="複数サービスから書き込む環境ではDB repositoryを選択する",
        source="https://example.com/adr",
        source_type="agent",
        namespace="plk.domain.dev",
    )
    record = FactRecord(
        id="01JZC2V7E8B3F4G5H6J7K8M9N0",
        organization_id=ORG_ID,
        revision=1,
        payload=payload,
        status="active",
        created_by="codex",
        created_at=now,
        updated_by="codex",
        updated_at=now,
    )

    assert record.organization_id == ORG_ID
    assert record.payload.namespace == "plk.domain.dev"
    with pytest.raises(ValidationError):
        record.revision = 2


def test_revision_conflict_exposes_expected_and_actual_values():
    error = RevisionConflict("fact-1", expected=2, actual=3)

    assert error.fact_id == "fact-1"
    assert error.expected == 2
    assert error.actual == 3
    assert "expected 2, actual 3" in str(error)
