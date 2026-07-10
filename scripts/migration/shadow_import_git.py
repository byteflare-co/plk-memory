"""Import one immutable Git snapshot for PostgreSQL parity verification.

This is deliberately a shadow importer: it preserves current content, status,
and supersedes relations, but does not reconstruct historical Git timestamps.
It must not be used as the final production cutover importer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import frontmatter

from plk_memory.domain import (
    ActorContext,
    CreateFact,
    FactPayload,
    InvalidateFact,
    QueryScope,
)
from plk_memory.facts import FactService
from plk_memory.gitstore import GitStore
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.repository import PostgresFactRepository
from plk_memory.settings import Settings


def required_str(post: frontmatter.Post, key: str) -> str:
    value = post.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def post_payload(post: frontmatter.Post) -> FactPayload:
    tags = post.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError("tags must be a list of strings")
    return FactPayload.model_validate(
        {
            "kind": required_str(post, "kind"),
            "statement": required_str(post, "statement"),
            "why": required_str(post, "why"),
            "how_to_apply": required_str(post, "how_to_apply"),
            "source": required_str(post, "source"),
            "source_type": required_str(post, "source_type"),
            "namespace": required_str(post, "namespace"),
            "tags": tuple(tags),
            "body": post.content,
        }
    )


def plan_import(posts: Mapping[str, frontmatter.Post]) -> tuple[str, ...]:
    """Return old-to-new order so superseded facts exist before replacements."""

    dependencies: dict[str, set[str]] = {fact_id: set() for fact_id in posts}
    dependants: dict[str, set[str]] = defaultdict(set)
    for old_id, post in posts.items():
        raw_new_id = post.get("superseded_by")
        if raw_new_id is None:
            continue
        if not isinstance(raw_new_id, str):
            raise ValueError(f"superseded_by must be a string: {old_id}")
        new_id = raw_new_id
        if new_id not in posts:
            raise ValueError(f"superseded_by target is missing: {old_id} -> {new_id}")
        if new_id == old_id:
            raise ValueError(f"fact supersedes itself: {old_id}")
        dependencies[new_id].add(old_id)
        dependants[old_id].add(new_id)

    ready = sorted(fact_id for fact_id, deps in dependencies.items() if not deps)
    ordered: list[str] = []
    while ready:
        fact_id = ready.pop(0)
        ordered.append(fact_id)
        for dependant in sorted(dependants[fact_id]):
            dependencies[dependant].remove(fact_id)
            if not dependencies[dependant]:
                ready.append(dependant)
                ready.sort()
    if len(ordered) != len(posts):
        cycle = sorted(fact_id for fact_id, deps in dependencies.items() if deps)
        raise ValueError(f"supersedes cycle detected: {cycle}")
    return tuple(ordered)


def supersedes_map(posts: Mapping[str, frontmatter.Post]) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = defaultdict(list)
    for old_id, post in posts.items():
        if raw_new_id := post.get("superseded_by"):
            if not isinstance(raw_new_id, str):
                raise ValueError(f"superseded_by must be a string: {old_id}")
            result[raw_new_id].append(old_id)
    return {fact_id: tuple(sorted(old_ids)) for fact_id, old_ids in result.items()}


async def shadow_import(settings: Settings, organization_id: UUID) -> dict[str, Any]:
    if not settings.database_url:
        raise ValueError("PLK_DATABASE_URL is required")
    if not (settings.data_repo_path / ".git").exists():
        raise ValueError("PLK_DATA_REPO_PATH must point to an existing Git snapshot")

    store = GitStore(settings)
    facts = FactService(store, settings)
    snapshot_commit = store.head()
    posts: dict[str, frontmatter.Post] = {}
    for post, _ in facts.list_posts():
        fact_id = str(post["id"])
        if fact_id in posts:
            raise ValueError(f"duplicate fact id: {fact_id}")
        posts[fact_id] = post

    order = plan_import(posts)
    replacements = supersedes_map(posts)
    actor = ActorContext(
        organization_id=organization_id,
        actor_id=f"git-shadow-import:{snapshot_commit[:12]}",
        actor_type="service",
        roles=frozenset(
            {"writer", "philosophy:write", "human-authored:write", "shared:write"}
        ),
    )
    database = PostgresDatabase(
        settings.database_url, pool_size=settings.database_pool_size
    )
    repository = PostgresFactRepository(database)
    try:
        for fact_id in order:
            post = posts[fact_id]
            old_ids = replacements.get(fact_id, ())
            await repository.create(
                actor,
                CreateFact(
                    fact_id=fact_id,
                    payload=post_payload(post),
                    change_reason=f"shadow import from Git {snapshot_commit}",
                    supersedes=old_ids,
                ),
                expected_superseded_revisions={old_id: 1 for old_id in old_ids},
                idempotency_key=f"git-shadow:{snapshot_commit}:{fact_id}:create",
            )

        for fact_id, post in posts.items():
            if post["status"] == "invalidated" and not post.get("superseded_by"):
                await repository.invalidate(
                    actor,
                    InvalidateFact(
                        fact_id=fact_id,
                        reason=(
                            str(post.get("invalidation_reason"))
                            if post.get("invalidation_reason")
                            else "invalidated in Git snapshot"
                        ),
                    ),
                    expected_revision=1,
                    idempotency_key=f"git-shadow:{snapshot_commit}:{fact_id}:invalidate",
                )

        scope = QueryScope(organization_id=organization_id, actor_id=actor.actor_id)
        mismatches: list[dict[str, str]] = []
        for fact_id, post in posts.items():
            record = await repository.get(scope, fact_id)
            expected = {
                "statement": str(post["statement"]),
                "namespace": str(post["namespace"]),
                "kind": str(post["kind"]),
                "status": str(post["status"]),
            }
            actual = {
                "statement": record.payload.statement,
                "namespace": record.payload.namespace,
                "kind": record.payload.kind,
                "status": record.status,
            }
            for field, expected_value in expected.items():
                if actual[field] != expected_value:
                    mismatches.append(
                        {
                            "fact_id": fact_id,
                            "field": field,
                            "git": expected_value,
                            "postgres": actual[field],
                        }
                    )
        return {
            "snapshot_commit": snapshot_commit,
            "organization_id": str(organization_id),
            "facts": len(posts),
            "relations": sum(len(ids) for ids in replacements.values()),
            "mismatches": mismatches,
            "parity": not mismatches,
        }
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-id", required=True, type=UUID)
    args = parser.parse_args()
    report = asyncio.run(shadow_import(Settings(), args.organization_id))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
