"""git-sync 統合テスト用のリポジトリ操作ヘルパー。

seed clone 上で frontmatter を編集し git add/commit/push する薄い関数群。
"""

from datetime import datetime, timezone
from pathlib import Path

import frontmatter
import pytest

from tests.conftest import sh

DEFAULT_FACT_ID = "01JZC2V7E8B3F4G5H6J7K8M9N0"

_VALID_FACT_DEFAULTS = dict(
    kind="knowhow",
    statement="法人税の中間申告は前期税額20万円超で必要になる制度である",
    why="国税庁タックスアンサーの中間申告の要件に明記されているため",
    how_to_apply="設立2期目以降、前期法人税額を確認して要否を判定する",
    source="https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5000.htm",
    source_type="agent",
    status="active",
    invalidation_reason=None,
    written_by="test",
    invalidated_at=None,
    superseded_by=None,
    tags=["中間申告"],
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@pytest.fixture
def write_valid_fact():
    """seed clone 上に plk_validator を通る frontmatter で md ファイルを書く（push はしない）。"""

    def _write(repo_dir: Path, rel: str, **over) -> str:
        meta = {
            "id": DEFAULT_FACT_ID,
            "namespace": "plk.domain.tax",
            "created_at": _now_iso(),
            **_VALID_FACT_DEFAULTS,
            **over,
        }
        path = repo_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(frontmatter.dumps(frontmatter.Post("詳細メモ。", **meta)), encoding="utf-8")
        return meta["id"]

    return _write


def push(repo_dir: Path, message: str = "sync test update") -> None:
    sh(repo_dir, "add", "-A")
    if sh(repo_dir, "status", "--porcelain").strip():
        sh(repo_dir, "commit", "-m", message)
    sh(repo_dir, "push", "origin", "main")


def modify_statement(repo_dir: Path, rel: str, new_statement: str) -> None:
    path = repo_dir / rel
    post = frontmatter.load(path)
    post["statement"] = new_statement
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def delete_file(repo_dir: Path, rel: str) -> None:
    (repo_dir / rel).unlink()


def rename_with_namespace(repo_dir: Path, old_rel: str, new_rel: str, new_namespace: str) -> None:
    """git mv ＋ frontmatter の namespace 書き換え＋commit（昇格 PR の実挙動を模倣。push はしない）。"""
    new_path = repo_dir / new_rel
    new_path.parent.mkdir(parents=True, exist_ok=True)
    sh(repo_dir, "mv", old_rel, new_rel)
    post = frontmatter.load(new_path)
    post["namespace"] = new_namespace
    new_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    sh(repo_dir, "add", "-A")
    sh(repo_dir, "commit", "-m", f"promote: {old_rel} -> {new_rel}")


def set_invalidated(repo_dir: Path, rel: str, reason: str = "テストによる無効化理由（十分な長さ）") -> None:
    path = repo_dir / rel
    post = frontmatter.load(path)
    post["status"] = "invalidated"
    post["invalidation_reason"] = reason
    post["invalidated_at"] = _now_iso()
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
