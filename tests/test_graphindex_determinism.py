from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

import frontmatter
from graphiti_core.errors import NodeNotFoundError
from graphiti_core.nodes import EpisodicNode

from plk_memory.graphindex import GraphIndex
from plk_memory.settings import Settings
from plk_memory.state import FactIndexEntry


async def test_episode_projection_precreates_deterministic_uuid(monkeypatch):
    seed = "org:fact:2"
    expected_uuid = str(uuid5(NAMESPACE_URL, f"{seed}:episode"))
    get_by_uuid = AsyncMock(side_effect=NodeNotFoundError(expected_uuid))
    save = AsyncMock()
    monkeypatch.setattr(EpisodicNode, "get_by_uuid", get_by_uuid)
    monkeypatch.setattr(EpisodicNode, "save", save)

    graphiti = SimpleNamespace(
        driver=object(),
        add_episode=AsyncMock(
            return_value=SimpleNamespace(
                episode=SimpleNamespace(uuid=expected_uuid)
            )
        ),
    )
    index = GraphIndex(Settings.model_construct())
    cast(Any, index)._graphiti = graphiti
    post = frontmatter.Post(
        "body",
        id="01JZC2V7E8B3F4G5H6J7K8M9N0",
        statement="deterministic episode projection",
        why="retry must address the same episode",
        how_to_apply="precreate before Graphiti update",
        namespace="plk.domain.dev",
        status="active",
        created_at=datetime(2026, 7, 11, tzinfo=UTC),
        tags=["graph"],
    )

    result = await index._upsert_episode(
        post, "org-test-plk-main", identity_seed=seed
    )

    get_by_uuid.assert_awaited_once_with(graphiti.driver, expected_uuid)
    save.assert_awaited_once()
    assert graphiti.add_episode.await_args.kwargs["uuid"] == expected_uuid
    assert result.episode_uuids == [expected_uuid]


async def test_upsert_creates_replacement_before_idempotent_old_delete(monkeypatch):
    index = GraphIndex(Settings.model_construct(ingest_mode="episode"))
    calls: list[str] = []
    replacement = FactIndexEntry(
        episode_uuids=["new"], content_hash="new-hash", group_id="group"
    )

    async def create_replacement(*_args, **_kwargs):
        calls.append("create")
        return replacement

    async def delete_old(*_args, **_kwargs):
        calls.append("delete")

    create = AsyncMock(side_effect=create_replacement)
    delete = AsyncMock(side_effect=delete_old)
    monkeypatch.setattr(index, "_upsert_episode", create)
    monkeypatch.setattr(index, "_delete_entry", delete)
    monkeypatch.setattr(index, "_route_group", lambda _group: None)
    post = frontmatter.Post(
        "body", namespace="plk.domain.dev", status="active"
    )
    old = FactIndexEntry(
        episode_uuids=["old"], content_hash="old-hash", group_id="group"
    )

    result = await index.upsert_fact(post, old, group_id_override="group")

    assert result == replacement
    assert calls == ["create", "delete"]
    assert create.await_count == 1
    delete.assert_awaited_once_with(old)
