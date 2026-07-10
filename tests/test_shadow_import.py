import frontmatter
import pytest

from scripts.migration.shadow_import_git import plan_import, supersedes_map


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
