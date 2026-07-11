from datetime import datetime, timezone
from typing import Any, cast

import frontmatter
import pytest

from plk_memory.facts import (
    FactError,
    FactService,
    require_metadata_datetime,
    require_metadata_str,
    require_metadata_str_list,
)


def test_required_string_rejects_non_string_without_coercion():
    post = frontmatter.Post("", id=123)

    with pytest.raises(FactError, match="frontmatter.id"):
        require_metadata_str(post, "id")


def test_fact_index_keeps_healthy_facts_available_when_one_id_is_malformed(monkeypatch):
    service = FactService(cast(Any, None), cast(Any, None))
    posts = [
        (frontmatter.Post("", id=123), "knowledge/domains/dev/bad.md"),
        (frontmatter.Post("", id="GOOD"), "knowledge/domains/dev/good.md"),
    ]
    monkeypatch.setattr(service, "list_posts", lambda: posts)

    assert service.index() == {"GOOD": "knowledge/domains/dev/good.md"}


@pytest.mark.parametrize("value", ["tag", ["valid", 123], None])
def test_string_list_rejects_scalar_and_mixed_values(value):
    post = frontmatter.Post("", tags=value)

    with pytest.raises(FactError, match="frontmatter.tags"):
        require_metadata_str_list(post, "tags")


def test_datetime_accepts_yaml_datetime_and_iso_string():
    expected = datetime(2026, 7, 11, 12, 30, tzinfo=timezone.utc)

    assert require_metadata_datetime(
        frontmatter.Post("", created_at=expected), "created_at"
    ) == expected
    assert require_metadata_datetime(
        frontmatter.Post("", created_at=expected.isoformat()), "created_at"
    ) == expected


@pytest.mark.parametrize("value", [123, "not-a-date", None])
def test_datetime_rejects_invalid_values_without_coercion(value):
    post = frontmatter.Post("", created_at=value)

    with pytest.raises(FactError, match="frontmatter.created_at"):
        require_metadata_datetime(post, "created_at")
