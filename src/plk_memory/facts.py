"""FactService: 書き込みパス（設計書 §6-1〜2）とポリシー強制（§7）。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

import frontmatter
from pydantic import ValidationError
from ulid import ULID

from plk_validator.schema import Fact
from plk_validator.secrets import scan_file

from plk_memory.gitstore import GitStore
from plk_memory.policy import scan_text
from plk_memory.settings import Settings

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SKIP_NAMES = {"CONVENTIONS.md", "README.md"}


class FactError(ValueError):
    pass


class FactNotFound(KeyError):
    pass


def require_metadata_str(post: frontmatter.Post, key: str) -> str:
    """frontmatter の必須文字列を型変換せずに検証する。"""
    value: Any = post.get(key)
    if not isinstance(value, str) or not value:
        raise FactError(f"frontmatter.{key} は空でない文字列である必要があります")
    return value


def require_metadata_datetime(post: frontmatter.Post, key: str) -> datetime:
    """YAML が datetime または ISO 文字列として読んだ日時を検証する。"""
    value: Any = post.get(key)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise FactError(f"frontmatter.{key} は ISO 8601 日時である必要があります") from exc
    raise FactError(f"frontmatter.{key} は日時である必要があります")


def require_metadata_str_list(post: frontmatter.Post, key: str) -> list[str]:
    """frontmatter の文字列配列を検証し、scalar 等を暗黙変換しない。"""
    value: Any = post.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise FactError(f"frontmatter.{key} は文字列の配列である必要があります")
    return value


class FactService:
    def __init__(self, store: GitStore, settings: Settings):
        self.store = store
        self.settings = settings

    # --- 読み取り ---

    def list_posts(self) -> list[tuple[frontmatter.Post, str]]:
        out = []
        root = self.settings.data_repo_path
        for p in sorted(self.settings.knowledge_dir.rglob("*.md")):
            if p.name in SKIP_NAMES:
                continue
            out.append((frontmatter.load(p), str(p.relative_to(root))))
        return out

    def index(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for post, rel in self.list_posts():
            if post.get("id") is not None:
                try:
                    result[require_metadata_str(post, "id")] = rel
                except FactError:
                    # SyncEngine records malformed facts as dead letters. Reads must
                    # keep healthy facts available instead of letting one bad file
                    # make every get/history/invalidate operation fail.
                    continue
        return result

    def get(self, fact_id: str) -> tuple[frontmatter.Post, str]:
        rel = self.index().get(fact_id)
        if rel is None:
            raise FactNotFound(fact_id)
        return frontmatter.load(self.settings.data_repo_path / rel), rel

    # --- 書き込み ---

    async def add(
        self, *, client: str, namespace: str, kind: str, statement: str, why: str,
        how_to_apply: str, source: str, tags: list[str] | None = None, body: str = "",
        slug: str | None = None, source_type: str = "agent",
        supersedes: list[str] | None = None,
        expected_superseded_hashes: dict[str, str] | None = None,
        change_ref: str | None = None,
    ) -> str:
        if source_type == "user":
            raise FactError("API 経由では source_type: user を指定できない（人間の PR 直編集のみ）")
        if kind == "philosophy":
            raise FactError("kind: philosophy は API 経由で追加できない（人間の PR 直編集のみ）")
        if namespace == "plk.shared":
            raise FactError("plk.shared への直接書き込みは禁止（昇格フロー経由のみ）")
        if source_type == "external-untrusted" and namespace != "plk.quarantine":
            raise FactError("external-untrusted は plk.quarantine（quarantine/）のみ")

        fact_id = str(ULID())
        async with self.store.write_lock():
            now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            meta = {
                "id": fact_id, "kind": kind, "statement": statement, "why": why,
                "how_to_apply": how_to_apply, "source": source, "source_type": source_type,
                "namespace": namespace, "status": "active", "invalidation_reason": None,
                "written_by": client, "created_at": now, "invalidated_at": None,
                "superseded_by": None, "tags": tags or [],
            }
            try:
                Fact(**meta)
            except ValidationError as e:
                raise FactError(f"規約違反: {e}") from e
            if len(body) > 2000:
                raise FactError("本文が 2,000 字を超過")

            name = slug if slug and SLUG_RE.fullmatch(slug) else fact_id.lower()
            rel = f"{self.settings.path_for_namespace(namespace)}/{name}.md"
            path = self.settings.data_repo_path / rel
            if path.exists():
                raise FactError(f"既に存在: {rel}")
            rendered = frontmatter.dumps(frontmatter.Post(body, **meta))
            findings = scan_text(rendered)
            if findings:
                raise FactError(f"シークレット検知のため拒否: {findings}")

            # 変更前に全 supersedes 対象を解決し、部分書き換えを防ぐ。
            targets: list[tuple[frontmatter.Post, str]] = []
            for old_id in supersedes or []:
                try:
                    target = self.get(old_id)
                except FactNotFound:
                    raise FactError(f"supersedes 対象が存在しない: {old_id}") from None
                if expected_superseded_hashes and old_id in expected_superseded_hashes:
                    target_path = self.settings.data_repo_path / target[1]
                    actual_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
                    if actual_hash != expected_superseded_hashes[old_id]:
                        raise FactError(f"supersedes 対象が変更されています: {old_id}")
                targets.append(target)

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
            file_findings = scan_file(path)
            if file_findings:
                path.unlink()
                raise FactError(f"シークレット検知のため拒否: {file_findings}")

            changed = [rel]
            for old_post, old_rel in targets:
                old_post["status"] = "invalidated"
                old_post["invalidation_reason"] = f"後継ファクト {fact_id} により置換"
                old_post["superseded_by"] = fact_id
                old_post["invalidated_at"] = now
                (self.settings.data_repo_path / old_rel).write_text(
                    frontmatter.dumps(old_post), encoding="utf-8"
                )
                changed.append(old_rel)

            message = f"plk_add: {statement[:40]} ({client})"
            if change_ref:
                message += f"\n\nPLK-Change-Ref: {change_ref}"
            await self.store.commit_and_push_locked(changed, message)
            return fact_id

    async def invalidate(
        self,
        fact_id: str,
        reason: str,
        *,
        client: str,
        expected_hash: str | None = None,
    ) -> None:
        if not reason or len(reason.strip()) < 5:
            raise FactError("invalidation_reason は必須（5 字以上）")
        async with self.store.write_lock():
            post, rel = self.get(fact_id)
            if post.get("status") != "active":
                raise FactError(f"active ではないfactは無効化できません: {fact_id}")
            if expected_hash:
                actual_hash = hashlib.sha256(
                    (self.settings.data_repo_path / rel).read_bytes()
                ).hexdigest()
                if actual_hash != expected_hash:
                    raise FactError(f"無効化対象が変更されています: {fact_id}")
            now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            post["status"] = "invalidated"
            post["invalidation_reason"] = reason
            post["invalidated_at"] = now
            (self.settings.data_repo_path / rel).write_text(
                frontmatter.dumps(post), encoding="utf-8"
            )
            await self.store.commit_and_push_locked(
                [rel], f"plk_invalidate: {fact_id} ({client})"
            )

    # --- 履歴 ---

    def history(self, fact_id: str) -> dict:
        post, rel = self.get(fact_id)
        log = self.store.git(
            "log", "--follow", "--format=%h|%aI|%s", "--", rel
        ).strip().splitlines()
        commits = [
            dict(zip(("sha", "date", "subject"), line.split("|", 2))) for line in log
        ]
        supersedes_chain = [
            other["id"] for other, _ in self.list_posts() if other.get("superseded_by") == fact_id
        ]
        return {
            "id": fact_id, "path": rel, "status": post["status"],
            "superseded_by": post.get("superseded_by"),
            "supersedes_chain": supersedes_chain, "commits": commits,
        }
