"""ファクト → Graphiti エピソードのレンダリングと正規化ハッシュ（設計書 §4）。"""

from __future__ import annotations

import hashlib
import json

import frontmatter

# 意味フィールドのみ hash 対象（created_at/written_by/invalidated_at は表記・帰属であり意味でない）
SEMANTIC_FIELDS = (
    "id", "kind", "statement", "why", "how_to_apply", "source",
    "source_type", "namespace", "status", "invalidation_reason",
    "superseded_by", "tags",
)


def render_episode(post: frontmatter.Post) -> str:
    m = post.metadata
    parts = [
        f"知見: {m['statement']}",
        f"根拠: {m['why']}",
        f"適用条件: {m['how_to_apply']}",
    ]
    body = post.content.strip()
    if body:
        parts.append(body)
    return "\n".join(parts)


def content_hash(post: frontmatter.Post) -> str:
    canon = {k: post.metadata.get(k) for k in SEMANTIC_FIELDS}
    payload = json.dumps(canon, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256((payload + "\n" + post.content.strip()).encode("utf-8"))
    return digest.hexdigest()[:16]


def episode_name(post: frontmatter.Post) -> str:
    return f"{post.metadata['id']}@{content_hash(post)}"
