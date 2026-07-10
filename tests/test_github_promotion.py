import subprocess

import pytest

from plk_memory.github_promotion import (
    GitHubPromotionBackend,
    PromotionBackendError,
    parse_pr_view,
    promotion_pr_body,
)
from plk_memory.promotions import new_promotion


def _pr():
    return new_promotion(
        fact_id="01JZC2V7E8B3F4G5H6J7K8M9N0", from_namespace="plk.domain.tax",
        old_path="knowledge/domains/tax/x.md", new_path="knowledge/shared/x.md",
        branch="promote/01JZC2V7E8B3F4G5H6J7K8M9N0",
    )


def test_pr_body_is_fixed_template_without_raw_html():
    body = promotion_pr_body(_pr())
    assert "plk.domain.tax" in body and "plk.shared" in body
    assert "01JZC2V7E8B3F4G5H6J7K8M9N0" in body
    # 生 HTML / HTML コメントを含まない（タグの組のみ除去。平文の -> は壊さない）
    assert "<script" not in body and "<!--" not in body


def test_pr_body_preserves_plain_arrow_and_strips_html_tags():
    """回帰: `[<>]` 一括除去が平文の `->` を `-` に潰していたバグ（P2 Task 10）。"""
    pr = new_promotion(
        fact_id="01JZC2V7E8B3F4G5H6J7K8M9N0",
        from_namespace="plk.domain.tax",
        old_path="knowledge/domains/tax/<b>x</b><!-- c -->.md",
        new_path="knowledge/shared/x.md",
        branch="promote/01JZC2V7E8B3F4G5H6J7K8M9N0",
    )
    body = promotion_pr_body(pr)
    # テンプレートの rename 行の矢印がそのまま出る（`old - new` に化けない）
    assert "knowledge/domains/tax/x.md -> knowledge/shared/x.md" in body
    # HTML タグ・HTML コメントは除去される
    assert "<b>" not in body and "</b>" not in body and "<!--" not in body and "-->" not in body


def test_parse_pr_view_maps_states():
    assert parse_pr_view('{"state":"MERGED","mergedAt":"2026-07-03T00:00:00Z"}') == "MERGED"
    assert parse_pr_view('{"state":"CLOSED","mergedAt":null}') == "CLOSED"
    assert parse_pr_view('{"state":"OPEN","mergedAt":null}') == "OPEN"


class _FakeStore:
    """build_promotion_branch を no-op にした GitStore の代役（実 git/gh に触れない）。"""

    def __init__(self):
        self.build_calls: list[dict] = []

    async def build_promotion_branch(self, *, old_rel, new_rel, branch, message):
        self.build_calls.append(
            {"old_rel": old_rel, "new_rel": new_rel, "branch": branch, "message": message}
        )


class _FakeSettings:
    repo_slug = "cutsome/agent-organization"


def _backend():
    return GitHubPromotionBackend(_FakeStore(), _FakeSettings())


async def test_create_pr_builds_args_and_extracts_number_from_url(monkeypatch):
    backend = _backend()
    calls: list[tuple] = []

    def fake_gh(self, *args):
        calls.append(args)
        return "https://github.com/cutsome/agent-organization/pull/123\n"

    monkeypatch.setattr(GitHubPromotionBackend, "_gh", fake_gh)
    number, url = await backend.create_pr(_pr())

    assert number == 123
    assert url == "https://github.com/cutsome/agent-organization/pull/123"
    assert len(backend.store.build_calls) == 1
    assert backend.store.build_calls[0]["branch"] == "promote/01JZC2V7E8B3F4G5H6J7K8M9N0"

    (args,) = calls
    assert args[:2] == ("pr", "create")
    assert "--repo" in args and "cutsome/agent-organization" in args
    assert "--base" in args and "main" in args
    assert "--head" in args and "promote/01JZC2V7E8B3F4G5H6J7K8M9N0" in args
    assert "--title" in args
    assert "--body" in args


async def test_create_pr_raises_when_url_has_no_pull_number(monkeypatch):
    backend = _backend()

    def fake_gh(self, *args):
        return "not a pr url\n"

    monkeypatch.setattr(GitHubPromotionBackend, "_gh", fake_gh)
    with pytest.raises(PromotionBackendError):
        await backend.create_pr(_pr())


async def test_create_pr_reuses_existing_open_pr_when_already_exists(monkeypatch):
    backend = _backend()
    calls: list[tuple] = []

    def fake_gh(self, *args):
        calls.append(args)
        if args[:2] == ("pr", "create"):
            raise subprocess.CalledProcessError(
                1, ["gh", *args],
                output="",
                stderr='a pull request for branch "promote/x" into branch "main" already exists:\n'
                       "https://github.com/cutsome/agent-organization/pull/99",
            )
        assert args[:2] == ("pr", "view")
        return '{"number": 99, "url": "https://github.com/cutsome/agent-organization/pull/99"}'

    monkeypatch.setattr(GitHubPromotionBackend, "_gh", fake_gh)
    number, url = await backend.create_pr(_pr())

    assert number == 99
    assert url == "https://github.com/cutsome/agent-organization/pull/99"
    assert calls[0][:2] == ("pr", "create")
    assert calls[1][:2] == ("pr", "view")
    assert calls[1][2] == "promote/01JZC2V7E8B3F4G5H6J7K8M9N0"


async def test_create_pr_raises_on_other_gh_failures(monkeypatch):
    backend = _backend()

    def fake_gh(self, *args):
        raise subprocess.CalledProcessError(1, ["gh", *args], output="", stderr="rate limited")

    monkeypatch.setattr(GitHubPromotionBackend, "_gh", fake_gh)
    with pytest.raises(PromotionBackendError):
        await backend.create_pr(_pr())


async def test_merged_state_parses_gh_json_output(monkeypatch):
    backend = _backend()
    calls: list[tuple] = []

    def fake_gh(self, *args):
        calls.append(args)
        return '{"state":"MERGED","mergedAt":"2026-07-03T00:00:00Z"}'

    monkeypatch.setattr(GitHubPromotionBackend, "_gh", fake_gh)
    state = await backend.merged_state(123)

    assert state == "MERGED"
    (args,) = calls
    assert args[:2] == ("pr", "view")
    assert args[2] == "123"
    assert "--json" in args and "state,mergedAt" in args
