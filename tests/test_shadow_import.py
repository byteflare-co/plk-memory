import os
import subprocess
from uuid import uuid4

import frontmatter
import pytest
from ulid import ULID

from plk_memory.settings import Settings
from scripts.migration.shadow_import_git import (
    plan_import,
    shadow_import,
    supersedes_map,
)


def post(*, superseded_by=None):
    return frontmatter.Post("", superseded_by=superseded_by)


def test_plan_import_orders_replacement_chain_oldest_first():
    posts = {
        "new": post(),
        "old": post(superseded_by="middle"),
        "middle": post(superseded_by="new"),
    }

    assert plan_import(posts) == ("old", "middle", "new")
    assert supersedes_map(posts) == {"middle": ("old",), "new": ("middle",)}


def test_plan_import_rejects_missing_target():
    with pytest.raises(ValueError, match="target is missing"):
        plan_import({"old": post(superseded_by="missing")})


def test_plan_import_rejects_cycle():
    with pytest.raises(ValueError, match="cycle"):
        plan_import(
            {
                "first": post(superseded_by="second"),
                "second": post(superseded_by="first"),
            }
        )


@pytest.mark.postgres
async def test_shadow_import_is_replayable_and_preserves_current_parity(tmp_path):
    database_url = os.environ.get("PLK_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PLK_TEST_DATABASE_URL is not configured")
    old_id, new_id = str(ULID()), str(ULID())
    knowledge = tmp_path / "knowledge" / "domains" / "dev"
    knowledge.mkdir(parents=True)
    common = {
        "kind": "knowhow",
        "why": "同時書き込み時の競合をデータベース制約で防止するために必要である",
        "how_to_apply": "複数サービスが書く環境では必ずこの更新方式を利用する",
        "source": "session 00000000-0000-0000-0000-000000000001",
        "source_type": "agent",
        "namespace": "plk.domain.dev",
        "tags": ["migration"],
    }
    (knowledge / "old.md").write_text(
        frontmatter.dumps(
            frontmatter.Post(
                "old body",
                **common,
                id=old_id,
                statement="旧方式ではGit pushを正本更新として扱っていた",
                status="invalidated",
                invalidation_reason=f"後継ファクト {new_id} により置換",
                superseded_by=new_id,
            )
        ),
        encoding="utf-8",
    )
    (knowledge / "new.md").write_text(
        frontmatter.dumps(
            frontmatter.Post(
                "new body",
                **common,
                id=new_id,
                statement="複数writerではPostgreSQLを更新可能な正本として扱う",
                status="active",
                invalidation_reason=None,
                superseded_by=None,
            )
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "knowledge"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=PLK Test",
            "-c",
            "user.email=plk-test@example.com",
            "commit",
            "-m",
            "snapshot",
        ],
        check=True,
        capture_output=True,
    )
    settings = Settings(data_repo_path=tmp_path, database_url=database_url)
    organization_id = uuid4()

    first = await shadow_import(settings, organization_id)
    replay = await shadow_import(settings, organization_id)

    assert first["parity"] is True
    assert first["facts"] == 2
    assert first["relations"] == 1
    assert replay == first
