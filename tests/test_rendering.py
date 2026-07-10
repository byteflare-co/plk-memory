import frontmatter

from plk_memory.rendering import content_hash, episode_name, render_episode

META = {
    "id": "01JZC2V7E8B3F4G5H6J7K8M9N0",
    "kind": "knowhow",
    "statement": "小規模企業共済は法人成り後も継続できる",
    "why": "中小機構の公式FAQに継続条件が明記されているため",
    "how_to_apply": "法人成り時に解約せず加入資格変更届を出す",
    "source": "https://example.com/faq",
    "source_type": "user",
    "namespace": "plk.domain.tax",
    "status": "active",
    "written_by": "masahiro",
    "created_at": "2026-07-02T10:00:00+09:00",
    "tags": ["共済"],
}


def post(**over):
    meta = {**META, **over}
    return frontmatter.Post("本文の詳細です。", **meta)


def test_render_contains_fields_but_not_identifiers():
    text = render_episode(post())
    assert "知見: 小規模企業共済は法人成り後も継続できる" in text
    assert "根拠:" in text and "適用条件:" in text and "本文の詳細です。" in text
    # 識別子・メタデータはエンティティ抽出ノイズになるので本文に入れない（設計書 §4）
    assert "01JZC2V7E8B3F4G5H6J7K8M9N0" not in text
    assert "plk.domain.tax" not in text
    assert "knowhow" not in text


def test_hash_stable_across_cosmetic_meta_changes():
    # created_at / written_by は意味フィールドでない → hash 不変（設計書 §4: 正規化 hash）
    assert content_hash(post()) == content_hash(
        post(created_at="2026-07-03T00:00:00+09:00", written_by="agent-x")
    )


def test_hash_changes_on_semantic_change():
    assert content_hash(post()) != content_hash(post(statement="別の知見の要旨に変わった内容"))
    assert content_hash(post()) != content_hash(post(status="invalidated"))
    p = post()
    p2 = post()
    p2.content = "本文が変わった。"
    assert content_hash(p) != content_hash(p2)


def test_episode_name_format():
    name = episode_name(post())
    fact_id, h = name.split("@")
    assert fact_id == META["id"] and len(h) == 16
