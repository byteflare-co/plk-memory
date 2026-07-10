"""FactService: 書き込みパス（設計書 §6-1〜2）とポリシー強制（§7）。"""

from __future__ import annotations

import re
from datetime import datetime, timezone

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
        return {
            post["id"]: rel for post, rel in self.list_posts() if post.get("id")
        }

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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        file_findings = scan_file(path)
        if file_findings:
            path.unlink()
            raise FactError(f"シークレット検知のため拒否: {file_findings}")

        # 書き換えループに入る前に全 supersedes 対象を解決する（部分書き換えを防ぐ）
        targets: list[tuple[frontmatter.Post, str]] = []
        for old_id in supersedes or []:
            try:
                targets.append(self.get(old_id))
            except FactNotFound:
                path.unlink()
                raise FactError(f"supersedes 対象が存在しない: {old_id}") from None

        # 不変条件: ここから commit_and_push までの間に await を挟まないこと
        # （挟むと作業ディレクトリの競合が再発する）
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

        await self.store.commit_and_push(changed, f"plk_add: {statement[:40]} ({client})")
        return fact_id

    async def invalidate(self, fact_id: str, reason: str, *, client: str) -> None:
        if not reason or len(reason.strip()) < 5:
            raise FactError("invalidation_reason は必須（5 字以上）")
        post, rel = self.get(fact_id)
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        # 不変条件: ファイル書き込みから commit_and_push までの間に await を挟まないこと
        # （挟むと作業ディレクトリの競合が再発する）
        post["status"] = "invalidated"
        post["invalidation_reason"] = reason
        post["invalidated_at"] = now
        (self.settings.data_repo_path / rel).write_text(frontmatter.dumps(post), encoding="utf-8")
        await self.store.commit_and_push([rel], f"plk_invalidate: {fact_id} ({client})")

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
