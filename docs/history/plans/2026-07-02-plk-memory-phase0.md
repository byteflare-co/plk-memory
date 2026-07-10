# plk-memory Phase 0（規約とデータ基盤）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PLK データリポジトリ（`agent-organization/knowledge/`）の構造・frontmatter 規約 v1・規約を強制する CI バリデータを整備し、規約準拠の実ノウハウ 20 件以上（人工矛盾系列込み）をシードする。

**Architecture:** 1ファクト1ファイルの markdown+frontmatter を Git 管理し、規約は「お願い」でなくバリデータ（pydantic スキーマ＋リポジトリ横断チェック＋シークレットスキャン＋git 差分チェック）で強制する。バリデータは `tools/validator/` の小さな uv プロジェクトで、Phase 1 の plk-memory-api が同一バリデータを import して使う前提の配置。

**Tech Stack:** Python 3.12+ / uv / pytest / pydantic v2 / python-frontmatter / detect-secrets / python-ulid / GitHub Actions / gitleaks

**設計書（SoT）:** `agent-memory/specs/2026-07-02-plk-memory-design.md` §4（規約）・§11 Phase 0

## Global Constraints

- Python `requires-python = ">=3.12"`
- `statement`: 20〜200 字。本文: 2,000 字以内
- `kind` ∈ {philosophy, logic, knowhow} / `source_type` ∈ {user, agent, external-untrusted} / `status` ∈ {active, invalidated}
- `id`: ULID（Crockford Base32 26 文字）。repo 全体で一意。既存ファイルの `id`/`created_at` は変更不可
- `namespace` はディレクトリと一致: `knowledge/shared/**`→`plk.shared`、`knowledge/domains/<d>/**`→`plk.domain.<d>`、`knowledge/quarantine/**`→`plk.quarantine`
- ドメインは `{tax, legal, shaho, dev, backoffice, biz}`
- `status: invalidated` なら `invalidation_reason`・`invalidated_at` 必須
- `source_type: external-untrusted` のファイルは `quarantine/` 配下のみ
- tax/legal/shaho namespace のファクトは一次情報 source（https URL）を 1 件以上含む
- 昇格 PR: `shared/` に触れる PR は「`domains/*`→`shared/*` の rename 100%・1 ファイルのみ・内容変更なし・source_type ≠ external-untrusted」
- 作業ディレクトリ: `/Users/masahiro/dev/byteflare-co/agent-organization`（Task 1 で git repo 化）
- コミットは各タスク末尾で必ず行う

---

### Task 1: agent-organization リポジトリ初期化と knowledge/ 構造

**Files:**
- Create: `.gitignore`
- Create: `knowledge/CONVENTIONS.md`
- Create: `knowledge/shared/.gitkeep`, `knowledge/domains/{tax,legal,shaho,dev,backoffice,biz}/.gitkeep`, `knowledge/quarantine/.gitkeep`

**Interfaces:**
- Consumes: なし（最初のタスク）
- Produces: `knowledge/` ディレクトリ構造と規約ドキュメント。以降の全タスクはこの構造とパス規則に依存する

- [ ] **Step 1: git 初期化と .gitignore**

`agent-organization/` には個人書類の PDF が入った `tmp/` が既にある。**コミットに含めない**。

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
git init
cat > .gitignore <<'EOF'
tmp/
.DS_Store
__pycache__/
.venv/
.pytest_cache/
EOF
```

- [ ] **Step 2: ディレクトリ構造を作成**

```bash
mkdir -p knowledge/shared knowledge/quarantine \
  knowledge/domains/tax knowledge/domains/legal knowledge/domains/shaho \
  knowledge/domains/dev knowledge/domains/backoffice knowledge/domains/biz
touch knowledge/shared/.gitkeep knowledge/quarantine/.gitkeep \
  knowledge/domains/tax/.gitkeep knowledge/domains/legal/.gitkeep \
  knowledge/domains/shaho/.gitkeep knowledge/domains/dev/.gitkeep \
  knowledge/domains/backoffice/.gitkeep knowledge/domains/biz/.gitkeep
```

- [ ] **Step 3: CONVENTIONS.md（規約 v1）を作成**

`knowledge/CONVENTIONS.md` に以下の内容を書く:

````markdown
# PLK 知識ベース規約 v1

> SoT: agent-memory/specs/2026-07-02-plk-memory-design.md §4。本書はその運用版。
> 規約はバリデータ（tools/validator）と CI が強制する。プロンプトへのお願いでは済ませない。

## 基本原則

- **1ファクト1ファイル**。markdown + YAML frontmatter。
- 生データはコピーしない。`source` に参照（URL / Notion ID / セッション ID）を書く。
- ディレクトリ = namespace。`shared/` は昇格済みのみ（直接追加禁止、昇格 PR 経由）。
- `quarantine/` は外部由来の未検証情報（`source_type: external-untrusted`）専用。

## frontmatter スキーマ

```yaml
---
id: 01JZC2V7E8B3F4G5H6J7K8M9N0   # ULID。scripts/new_fact.py が採番。変更不可
kind: knowhow                     # philosophy / logic / knowhow
statement: "..."                  # 要旨。20〜200 字
why: "..."                        # 根拠・経緯。20 字以上・定型文不可
how_to_apply: "..."               # 適用条件。15 字以上・定型文不可
source: "https://... / Notion ID / セッション ID"  # 形式検証あり。複数可（文字列内に併記）
source_type: agent                # user / agent / external-untrusted
namespace: plk.domain.tax         # ディレクトリと一致（CI 検証）
status: active                    # active / invalidated
invalidation_reason: null         # invalidated 時は必須
written_by: claude-code           # 書いた主体。API 経由ではサーバーが導出（Phase 1〜）
created_at: 2026-07-02T10:00:00+09:00  # 変更不可
invalidated_at: null
superseded_by: null               # 後継ファクトの id
tags: []
---
（本文: 詳細・経緯・具体例。2,000 字以内）
```

## 追加ルール

- `kind: philosophy` は原則 PR 直編集で管理（Phase 1 以降、API 書き込みは警告）。
- tax / legal / shaho のファクトは一次情報 source（https URL、条文・公式手引き等）を 1 件以上含める。
- 無効化は削除でなく `status: invalidated` + `invalidation_reason` + `superseded_by`。履歴は git log に残る。
- 秘密情報（API キー・トークン等）は書き込み禁止。バリデータと gitleaks が検知する。
  漏れた場合のハードデリート手順は設計書 §7 の runbook。

## 新規ファクトの作り方

```bash
cd tools/validator && uv run python scripts/new_fact.py domains/tax "ファイル名スラッグ"
# 生成された雛形を埋める → バリデータで確認:
uv run plk-validate ../../knowledge
```
````

- [ ] **Step 4: 構造を確認**

Run: `find knowledge -type d | sort`
Expected:
```
knowledge
knowledge/domains
knowledge/domains/backoffice
knowledge/domains/biz
knowledge/domains/dev
knowledge/domains/legal
knowledge/domains/shaho
knowledge/domains/tax
knowledge/quarantine
knowledge/shared
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore knowledge/
git commit -m "feat: knowledge/ ディレクトリ構造と PLK 規約 v1 を追加"
```

---

### Task 2: バリデータ プロジェクト雛形と Fact スキーマ（基本検証）

**Files:**
- Create: `tools/validator/pyproject.toml`
- Create: `tools/validator/src/plk_validator/__init__.py`
- Create: `tools/validator/src/plk_validator/schema.py`
- Test: `tools/validator/tests/__init__.py`
- Test: `tools/validator/tests/test_schema.py`
- Test: `tools/validator/tests/conftest.py`

**Interfaces:**
- Consumes: なし
- Produces: `plk_validator.schema.Fact`（pydantic BaseModel。`Fact(**metadata)` で検証、失敗時 `pydantic.ValidationError`）、定数 `DOMAINS: set[str]`、`NAMESPACE_RE`

- [ ] **Step 1: プロジェクト雛形**

`tools/validator/pyproject.toml`:

```toml
[project]
name = "plk-validator"
version = "0.1.0"
description = "PLK 知識ベースの規約バリデータ"
requires-python = ">=3.12"
dependencies = [
    "python-frontmatter>=1.1",
    "pydantic>=2.7",
    "detect-secrets>=1.5",
    "python-ulid>=2.7",
]

[project.scripts]
plk-validate = "plk_validator.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/plk_validator"]
```

`tools/validator/src/plk_validator/__init__.py` と `tools/validator/tests/__init__.py` は空ファイル（tests/ は他テストから `from tests.conftest import VALID_META` と import するため package 化が必須）。

- [ ] **Step 2: テストfixture（conftest.py）を書く**

`tools/validator/tests/conftest.py`:

```python
from datetime import datetime, timezone

import pytest

VALID_META = {
    "id": "01JZC2V7E8B3F4G5H6J7K8M9N0",
    "kind": "knowhow",
    "statement": "小規模企業共済の掛金は法人成り後も個人契約のまま継続できる",
    "why": "中小機構の公式FAQで、個人事業から法人役員になった場合の継続条件が明記されているため",
    "how_to_apply": "法人成り時に解約せず、加入資格の変更届を中小機構に提出する",
    "source": "https://www.smrj.go.jp/kyosai/skyosai/faq/",
    "source_type": "user",
    "namespace": "plk.domain.tax",
    "status": "active",
    "invalidation_reason": None,
    "written_by": "masahiro",
    "created_at": datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
    "invalidated_at": None,
    "superseded_by": None,
    "tags": ["小規模企業共済"],
}


@pytest.fixture
def valid_meta():
    return dict(VALID_META)
```

- [ ] **Step 3: 失敗するテストを書く**

`tools/validator/tests/test_schema.py`:

```python
import pytest
from pydantic import ValidationError

from plk_validator.schema import Fact


def test_valid_fact_passes(valid_meta):
    fact = Fact(**valid_meta)
    assert fact.id == valid_meta["id"]


def test_missing_required_field_fails(valid_meta):
    del valid_meta["why"]
    with pytest.raises(ValidationError):
        Fact(**valid_meta)


def test_invalid_kind_fails(valid_meta):
    valid_meta["kind"] = "wisdom"
    with pytest.raises(ValidationError):
        Fact(**valid_meta)


def test_invalid_ulid_fails(valid_meta):
    valid_meta["id"] = "not-a-ulid"
    with pytest.raises(ValidationError):
        Fact(**valid_meta)


def test_statement_too_short_fails(valid_meta):
    valid_meta["statement"] = "短すぎる"
    with pytest.raises(ValidationError):
        Fact(**valid_meta)


def test_statement_too_long_fails(valid_meta):
    valid_meta["statement"] = "あ" * 201
    with pytest.raises(ValidationError):
        Fact(**valid_meta)


def test_invalid_namespace_format_fails(valid_meta):
    valid_meta["namespace"] = "plk.domain.unknown"
    with pytest.raises(ValidationError):
        Fact(**valid_meta)
```

- [ ] **Step 4: テストが失敗することを確認**

Run: `cd tools/validator && uv run pytest tests/test_schema.py -v`
Expected: 全テスト FAIL / ERROR（`ModuleNotFoundError: No module named 'plk_validator.schema'`）

- [ ] **Step 5: schema.py（基本検証のみ）を実装**

`tools/validator/src/plk_validator/schema.py`:

```python
"""PLK ファクトの frontmatter スキーマ（規約 v1）。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
DOMAINS = {"tax", "legal", "shaho", "dev", "backoffice", "biz"}
NAMESPACE_RE = re.compile(
    r"^plk\.(shared|quarantine|domain\.(" + "|".join(sorted(DOMAINS)) + r"))$"
)


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["philosophy", "logic", "knowhow"]
    statement: str
    why: str
    how_to_apply: str
    source: str
    source_type: Literal["user", "agent", "external-untrusted"]
    namespace: str
    status: Literal["active", "invalidated"]
    invalidation_reason: str | None = None
    written_by: str
    created_at: datetime
    invalidated_at: datetime | None = None
    superseded_by: str | None = None
    tags: list[str] = []

    @field_validator("id", "superseded_by")
    @classmethod
    def _ulid(cls, v: str | None) -> str | None:
        if v is not None and not ULID_RE.fullmatch(v):
            raise ValueError("ULID（Crockford Base32 26文字）ではない")
        return v

    @field_validator("statement")
    @classmethod
    def _statement_len(cls, v: str) -> str:
        if not (20 <= len(v) <= 200):
            raise ValueError("statement は 20〜200 字")
        return v

    @field_validator("namespace")
    @classmethod
    def _namespace(cls, v: str) -> str:
        if not NAMESPACE_RE.fullmatch(v):
            raise ValueError(f"namespace の形式が不正: {v}")
        return v
```

- [ ] **Step 6: テストが通ることを確認**

Run: `cd tools/validator && uv run pytest tests/test_schema.py -v`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
git add tools/validator
git commit -m "feat: plk-validator 雛形と Fact スキーマ（基本検証）"
```

---

### Task 3: 内容ヒューリスティック（形骸化・source 形式・invalidated 整合）

**Files:**
- Modify: `tools/validator/src/plk_validator/schema.py`
- Test: `tools/validator/tests/test_schema_content.py`

**Interfaces:**
- Consumes: Task 2 の `Fact`
- Produces: `Fact` に内容検証が追加される（外部シグネチャ変更なし）。定数 `BOILERPLATE: set[str]`、`PRIMARY_SOURCE_NS: set[str]`

- [ ] **Step 1: 失敗するテストを書く**

`tools/validator/tests/test_schema_content.py`:

```python
import pytest
from pydantic import ValidationError

from plk_validator.schema import Fact


def test_boilerplate_why_fails(valid_meta):
    valid_meta["why"] = "経験から得られた"
    with pytest.raises(ValidationError, match="定型文"):
        Fact(**valid_meta)


def test_boilerplate_how_to_apply_fails(valid_meta):
    valid_meta["how_to_apply"] = "状況に応じて適用"
    with pytest.raises(ValidationError, match="定型文"):
        Fact(**valid_meta)


def test_short_why_fails(valid_meta):
    valid_meta["why"] = "だから。"
    with pytest.raises(ValidationError):
        Fact(**valid_meta)


def test_source_without_reference_fails(valid_meta):
    valid_meta["source"] = "だいたいネットで見た"
    with pytest.raises(ValidationError, match="source"):
        Fact(**valid_meta)


def test_source_with_notion_id_passes(valid_meta):
    valid_meta["namespace"] = "plk.domain.dev"  # 一次情報必須の ns から外す
    valid_meta["source"] = "Notion <notion-page-id>"
    Fact(**valid_meta)


def test_source_with_session_uuid_passes(valid_meta):
    valid_meta["namespace"] = "plk.domain.dev"
    valid_meta["source"] = "セッション 2ea8548a-c2ee-4c04-b5a2-d3049037219e"
    Fact(**valid_meta)


def test_tax_requires_primary_source_url(valid_meta):
    valid_meta["namespace"] = "plk.domain.tax"
    valid_meta["source"] = "Notion <notion-page-id>"  # URL なし
    with pytest.raises(ValidationError, match="一次情報"):
        Fact(**valid_meta)


def test_invalidated_requires_reason_and_timestamp(valid_meta):
    valid_meta["status"] = "invalidated"
    with pytest.raises(ValidationError, match="invalidation_reason"):
        Fact(**valid_meta)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd tools/validator && uv run pytest tests/test_schema_content.py -v`
Expected: 大半が FAIL（検証がまだ無いため `ValidationError` が発生しない）

- [ ] **Step 3: schema.py に内容検証を追加**

`tools/validator/src/plk_validator/schema.py` に以下を追加（既存 import に `model_validator` を追加）:

```python
from pydantic import BaseModel, ConfigDict, field_validator, model_validator  # 差し替え

URL_RE = re.compile(r"https?://\S+")
NOTION_ID_RE = re.compile(r"\b[0-9a-f]{32}\b")
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
BOILERPLATE = {
    "状況に応じて", "状況に応じて適用", "必要に応じて",
    "経験から得られた", "ケースバイケース", "適宜判断",
}
PRIMARY_SOURCE_NS = {"plk.domain.tax", "plk.domain.legal", "plk.domain.shaho"}


def _stripped(text: str) -> str:
    return re.sub(r"[\s。、.,]", "", text)
```

`Fact` クラス内に以下の validator を追加:

```python
    @field_validator("why")
    @classmethod
    def _why(cls, v: str) -> str:
        s = _stripped(v)
        if s in BOILERPLATE:
            raise ValueError("why が定型文（根拠を具体的に書く）")
        if len(s) < 20:
            raise ValueError("why は 20 字以上（根拠・経緯を具体的に）")
        return v

    @field_validator("how_to_apply")
    @classmethod
    def _how(cls, v: str) -> str:
        s = _stripped(v)
        if s in BOILERPLATE:
            raise ValueError("how_to_apply が定型文（適用条件を具体的に書く）")
        if len(s) < 15:
            raise ValueError("how_to_apply は 15 字以上")
        return v

    @model_validator(mode="after")
    def _cross_field(self) -> "Fact":
        has_ref = bool(
            URL_RE.search(self.source)
            or NOTION_ID_RE.search(self.source)
            or UUID_RE.search(self.source)
        )
        if not has_ref:
            raise ValueError("source に参照（URL / Notion ID / セッション ID）が必要")
        if self.namespace in PRIMARY_SOURCE_NS and not URL_RE.search(self.source):
            raise ValueError(f"{self.namespace} は一次情報 source（https URL）が 1 件以上必要")
        if self.status == "invalidated":
            if not self.invalidation_reason:
                raise ValueError("invalidated には invalidation_reason が必須")
            if self.invalidated_at is None:
                raise ValueError("invalidated には invalidated_at が必須")
        return self
```

- [ ] **Step 4: 全テストが通ることを確認**

Run: `cd tools/validator && uv run pytest tests/ -v`
Expected: test_schema.py 7 passed + test_schema_content.py 8 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
git add tools/validator
git commit -m "feat: 内容ヒューリスティック（定型文拒否・source 形式・invalidated 整合）"
```

---

### Task 4: リポジトリ横断チェック（namespace↔パス・quarantine・id 一意性・本文上限）

**Files:**
- Create: `tools/validator/src/plk_validator/repo_checks.py`
- Test: `tools/validator/tests/test_repo_checks.py`

**Interfaces:**
- Consumes: Task 2-3 の `Fact`
- Produces: `repo_checks.validate_repo(knowledge_dir: Path) -> list[str]`（エラーメッセージのリスト。空 = 合格）、`repo_checks.expected_namespace(rel_parts: tuple[str, ...]) -> str | None`

- [ ] **Step 1: 失敗するテストを書く**

`tools/validator/tests/test_repo_checks.py`:

```python
from pathlib import Path

import frontmatter

from plk_validator.repo_checks import validate_repo
from tests.conftest import VALID_META


def write_fact(path: Path, **overrides):
    meta = {**VALID_META, **overrides}
    meta["created_at"] = meta["created_at"].isoformat()
    post = frontmatter.Post("本文です。", **meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def test_clean_repo_passes(tmp_path):
    write_fact(tmp_path / "domains/tax/fact1.md")
    assert validate_repo(tmp_path) == []


def test_namespace_path_mismatch_fails(tmp_path):
    write_fact(tmp_path / "domains/dev/fact1.md", namespace="plk.domain.tax")
    errors = validate_repo(tmp_path)
    assert any("namespace" in e for e in errors)


def test_untrusted_outside_quarantine_fails(tmp_path):
    write_fact(
        tmp_path / "domains/dev/fact1.md",
        namespace="plk.domain.dev",
        source_type="external-untrusted",
    )
    errors = validate_repo(tmp_path)
    assert any("quarantine" in e for e in errors)


def test_duplicate_id_fails(tmp_path):
    write_fact(tmp_path / "domains/tax/fact1.md")
    write_fact(tmp_path / "domains/dev/fact2.md", namespace="plk.domain.dev")
    errors = validate_repo(tmp_path)
    assert any("重複" in e for e in errors)


def test_body_too_long_fails(tmp_path):
    write_fact(tmp_path / "domains/tax/fact1.md")
    p = tmp_path / "domains/tax/fact1.md"
    post = frontmatter.load(p)
    post.content = "あ" * 2001
    p.write_text(frontmatter.dumps(post), encoding="utf-8")
    errors = validate_repo(tmp_path)
    assert any("2,000" in e or "2000" in e for e in errors)


def test_schema_violation_reported_with_path(tmp_path):
    write_fact(tmp_path / "domains/tax/fact1.md", statement="短い")
    errors = validate_repo(tmp_path)
    assert any("fact1.md" in e for e in errors)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd tools/validator && uv run pytest tests/test_repo_checks.py -v`
Expected: ERROR（`No module named 'plk_validator.repo_checks'`）

- [ ] **Step 3: repo_checks.py を実装**

`tools/validator/src/plk_validator/repo_checks.py`:

```python
"""knowledge/ ディレクトリ全体の横断チェック。"""

from __future__ import annotations

from pathlib import Path

import frontmatter
from pydantic import ValidationError

from plk_validator.schema import Fact

BODY_LIMIT = 2000
SKIP_NAMES = {"CONVENTIONS.md", "README.md"}


def expected_namespace(rel_parts: tuple[str, ...]) -> str | None:
    if not rel_parts:
        return None
    head = rel_parts[0]
    if head == "shared":
        return "plk.shared"
    if head == "quarantine":
        return "plk.quarantine"
    if head == "domains" and len(rel_parts) >= 3:
        return f"plk.domain.{rel_parts[1]}"
    return None


def iter_fact_files(knowledge_dir: Path):
    for p in sorted(knowledge_dir.rglob("*.md")):
        if p.name not in SKIP_NAMES:
            yield p


def validate_repo(knowledge_dir: Path) -> list[str]:
    errors: list[str] = []
    seen_ids: dict[str, Path] = {}

    for path in iter_fact_files(knowledge_dir):
        rel = path.relative_to(knowledge_dir)
        try:
            post = frontmatter.load(path)
        except Exception as e:  # YAML 破損など
            errors.append(f"{rel}: frontmatter を読めない: {e}")
            continue

        try:
            fact = Fact(**post.metadata)
        except ValidationError as e:
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"]) or "(model)"
                errors.append(f"{rel}: {loc}: {err['msg']}")
            continue

        exp_ns = expected_namespace(rel.parts)
        if exp_ns is None:
            errors.append(f"{rel}: 規定外の配置（shared/ domains/<d>/ quarantine/ のみ）")
        elif fact.namespace != exp_ns:
            errors.append(f"{rel}: namespace {fact.namespace} がパス（期待 {exp_ns}）と不一致")

        if fact.source_type == "external-untrusted" and rel.parts[0] != "quarantine":
            errors.append(f"{rel}: external-untrusted は quarantine/ 配下のみ")

        if len(post.content) > BODY_LIMIT:
            errors.append(f"{rel}: 本文が 2,000 字を超過（{len(post.content)} 字）")

        if fact.id in seen_ids:
            errors.append(f"{rel}: id が {seen_ids[fact.id]} と重複")
        else:
            seen_ids[fact.id] = rel

    return errors
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd tools/validator && uv run pytest tests/ -v`
Expected: 全テスト passed（累計 21）

- [ ] **Step 5: Commit**

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
git add tools/validator
git commit -m "feat: リポジトリ横断チェック（namespace 一致・quarantine・id 一意性・本文上限）"
```

---

### Task 5: シークレットスキャン（detect-secrets + 自前パターン）

**Files:**
- Create: `tools/validator/src/plk_validator/secrets.py`
- Test: `tools/validator/tests/test_secrets.py`

**Interfaces:**
- Consumes: なし（独立モジュール）
- Produces: `secrets.scan_file(path: Path) -> list[str]`（検知名のリスト。空 = クリーン）

- [ ] **Step 1: 失敗するテストを書く**

`tools/validator/tests/test_secrets.py`（**テスト用の疑似キーは文字列連結で構成**し、このファイル自体が gitleaks に検知されないようにする）:

```python
from plk_validator.secrets import scan_file

FAKE_ANTHROPIC = "sk-ant-" + "api03-" + "x" * 24
FAKE_TAILSCALE = "tskey-" + "auth-" + "k" * 16
FAKE_GITHUB = "ghp_" + "A" * 36
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"


def _write(tmp_path, text):
    p = tmp_path / "fact.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_clean_file_passes(tmp_path):
    p = _write(tmp_path, "これは普通のノウハウ本文です。秘密情報は含まれません。")
    assert scan_file(p) == []


def test_anthropic_key_detected(tmp_path):
    p = _write(tmp_path, f"APIキーは {FAKE_ANTHROPIC} です")
    assert any("Anthropic" in f for f in scan_file(p))


def test_tailscale_key_detected(tmp_path):
    p = _write(tmp_path, f"tailscale up --authkey={FAKE_TAILSCALE}")
    assert any("Tailscale" in f for f in scan_file(p))


def test_github_token_detected(tmp_path):
    p = _write(tmp_path, f"export GH_TOKEN={FAKE_GITHUB}")
    assert any("GitHub" in f for f in scan_file(p))


def test_aws_key_detected(tmp_path):
    p = _write(tmp_path, f"aws_access_key_id = {FAKE_AWS}")
    assert scan_file(p) != []
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd tools/validator && uv run pytest tests/test_secrets.py -v`
Expected: ERROR（`No module named 'plk_validator.secrets'`）

- [ ] **Step 3: secrets.py を実装**

`tools/validator/src/plk_validator/secrets.py`:

```python
"""書き込み前シークレット検知。in-process の一次ゲート（二次は CI の gitleaks）。

detect-secrets はルール更新が停滞しているため（2024-05 以降）、
新しめのトークン形式は CUSTOM_PATTERNS で自前検知する（設計書 §3 技術選定）。
"""

from __future__ import annotations

import re
from pathlib import Path

from detect_secrets import SecretsCollection
from detect_secrets.settings import default_settings

CUSTOM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")),
    ("Tailscale key", re.compile(r"tskey-[A-Za-z0-9_-]{8,}")),
    ("GitHub token", re.compile(r"(?:ghp_|gho_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("OpenAI 系 key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
]


def scan_file(path: Path) -> list[str]:
    findings: list[str] = []
    text = path.read_text(encoding="utf-8")
    for name, rx in CUSTOM_PATTERNS:
        if rx.search(text):
            findings.append(f"custom:{name}")
    collection = SecretsCollection()
    with default_settings():
        collection.scan_file(str(path))
    for _, secret in collection:
        findings.append(f"detect-secrets:{secret.type}")
    return findings
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd tools/validator && uv run pytest tests/test_secrets.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
git add tools/validator
git commit -m "feat: シークレットスキャン（detect-secrets + 自前パターン）"
```

---

### Task 6: git 差分チェック（昇格 PR ルール・id/created_at 不変性）

**Files:**
- Create: `tools/validator/src/plk_validator/gitchecks.py`
- Test: `tools/validator/tests/test_gitchecks.py`

**Interfaces:**
- Consumes: Task 4 の `write_fact` テストヘルパーの流儀（frontmatter 生成）
- Produces: `gitchecks.check_promotion(repo_dir: Path, base_ref: str) -> list[str]`、`gitchecks.check_id_immutability(repo_dir: Path, base_ref: str) -> list[str]`

- [ ] **Step 1: 失敗するテストを書く**

`tools/validator/tests/test_gitchecks.py`:

```python
import subprocess
from pathlib import Path

import pytest

from plk_validator.gitchecks import check_id_immutability, check_promotion
from tests.test_repo_checks import write_fact


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return r.stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "test@test")
    git(tmp_path, "config", "user.name", "test")
    write_fact(tmp_path / "knowledge/domains/tax/fact1.md")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "init")
    git(tmp_path, "checkout", "-b", "feature")
    return tmp_path


def test_promotion_valid_rename_passes(repo):
    git(repo, "mv", "knowledge/domains/tax/fact1.md", "knowledge/shared/fact1.md")
    git(repo, "commit", "-m", "promote")
    assert check_promotion(repo, "main") == []


def test_promotion_new_file_in_shared_fails(repo):
    write_fact(
        repo / "knowledge/shared/new.md",
        id="01JZC2V7E8B3F4G5H6J7K8M9N1",
        namespace="plk.shared",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "direct add to shared")
    errors = check_promotion(repo, "main")
    assert any("rename" in e for e in errors)


def test_promotion_with_extra_file_fails(repo):
    git(repo, "mv", "knowledge/domains/tax/fact1.md", "knowledge/shared/fact1.md")
    write_fact(
        repo / "knowledge/domains/dev/extra.md",
        id="01JZC2V7E8B3F4G5H6J7K8M9N2",
        namespace="plk.domain.dev",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "promote + extra")
    errors = check_promotion(repo, "main")
    assert any("1 ファイル" in e for e in errors)


def test_no_shared_changes_passes(repo):
    write_fact(
        repo / "knowledge/domains/dev/extra.md",
        id="01JZC2V7E8B3F4G5H6J7K8M9N2",
        namespace="plk.domain.dev",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "normal add")
    assert check_promotion(repo, "main") == []


def test_id_change_fails(repo):
    p = repo / "knowledge/domains/tax/fact1.md"
    text = p.read_text(encoding="utf-8")
    p.write_text(
        text.replace("01JZC2V7E8B3F4G5H6J7K8M9N0", "01JZC2V7E8B3F4G5H6J7K8M9N9"),
        encoding="utf-8",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "mutate id")
    errors = check_id_immutability(repo, "main")
    assert any("id" in e for e in errors)


def test_content_edit_keeps_id_passes(repo):
    p = repo / "knowledge/domains/tax/fact1.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n追記です。", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "edit body")
    assert check_id_immutability(repo, "main") == []
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd tools/validator && uv run pytest tests/test_gitchecks.py -v`
Expected: ERROR（`No module named 'plk_validator.gitchecks'`）

- [ ] **Step 3: gitchecks.py を実装**

`tools/validator/src/plk_validator/gitchecks.py`:

```python
"""git 差分ベースのチェック（昇格 PR ルール・id/created_at 不変性）。

git 操作は subprocess 直叩き（GitPython は常駐プロセス非推奨のため。設計書 §3）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import frontmatter


def _git(repo_dir: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True, text=True, check=True,
    )
    return r.stdout


def _diff_entries(repo_dir: Path, base_ref: str) -> list[list[str]]:
    out = _git(repo_dir, "diff", "--name-status", "-M100%", f"{base_ref}...HEAD")
    return [line.split("\t") for line in out.splitlines() if line.strip()]


def check_promotion(repo_dir: Path, base_ref: str) -> list[str]:
    """shared/ に触れる変更は「domains/→shared/ の rename 100%・1 ファイルのみ」。"""
    entries = _diff_entries(repo_dir, base_ref)
    shared = [e for e in entries if any(p.startswith("knowledge/shared/") for p in e[1:])]
    if not shared:
        return []
    errors: list[str] = []
    if len(entries) != 1:
        errors.append("昇格 PR は 1 ファイルのみの変更でなければならない")
    for e in shared:
        status, paths = e[0], e[1:]
        ok = (
            status == "R100"
            and len(paths) == 2
            and paths[0].startswith("knowledge/domains/")
            and paths[1].startswith("knowledge/shared/")
        )
        if not ok:
            errors.append(
                f"{paths[-1]}: shared/ への変更は domains/ からの rename 100%（内容変更なし）のみ許可"
            )
            continue
        post = frontmatter.load(repo_dir / paths[1])
        if post.get("source_type") == "external-untrusted":
            errors.append(f"{paths[1]}: external-untrusted は昇格不可")
    return errors


def check_id_immutability(repo_dir: Path, base_ref: str) -> list[str]:
    """変更されたファクトの id / created_at が base から変わっていないこと。"""
    errors: list[str] = []
    for e in _diff_entries(repo_dir, base_ref):
        if e[0] != "M" or not e[1].startswith("knowledge/") or not e[1].endswith(".md"):
            continue
        old = frontmatter.loads(_git(repo_dir, "show", f"{base_ref}:{e[1]}"))
        new = frontmatter.load(repo_dir / e[1])
        for field in ("id", "created_at"):
            if str(old.get(field)) != str(new.get(field)):
                errors.append(f"{e[1]}: {field} は変更不可（{old.get(field)} → {new.get(field)}）")
    return errors
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd tools/validator && uv run pytest tests/ -v`
Expected: 全テスト passed（累計 32）

- [ ] **Step 5: Commit**

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
git add tools/validator
git commit -m "feat: git 差分チェック（昇格 PR ルール・id 不変性）"
```

---

### Task 7: CLI エントリポイント

**Files:**
- Create: `tools/validator/src/plk_validator/cli.py`
- Test: `tools/validator/tests/test_cli.py`

**Interfaces:**
- Consumes: `validate_repo`（Task 4）、`scan_file`（Task 5）、`check_promotion`/`check_id_immutability`（Task 6）
- Produces: コンソールコマンド `plk-validate <knowledge_dir> [--base <ref>]`（exit 0 = 合格 / 1 = 違反あり）。CI と人間の両方が使う唯一の入口

- [ ] **Step 1: 失敗するテストを書く**

`tools/validator/tests/test_cli.py`:

```python
from plk_validator.cli import main
from tests.test_repo_checks import write_fact


def test_clean_dir_returns_zero(tmp_path, capsys):
    write_fact(tmp_path / "domains/tax/fact1.md")
    assert main([str(tmp_path)]) == 0
    assert "OK" in capsys.readouterr().out


def test_violation_returns_one(tmp_path, capsys):
    write_fact(tmp_path / "domains/tax/fact1.md", statement="短い")
    assert main([str(tmp_path)]) == 1
    assert "statement" in capsys.readouterr().out


def test_secret_in_fact_returns_one(tmp_path, capsys):
    write_fact(tmp_path / "domains/dev/fact1.md", namespace="plk.domain.dev")
    p = tmp_path / "domains/dev/fact1.md"
    fake_key = "sk-ant-" + "api03-" + "x" * 24
    p.write_text(p.read_text(encoding="utf-8") + f"\nキー: {fake_key}", encoding="utf-8")
    assert main([str(tmp_path)]) == 1
    assert "Anthropic" in capsys.readouterr().out
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd tools/validator && uv run pytest tests/test_cli.py -v`
Expected: ERROR（`No module named 'plk_validator.cli'`）

- [ ] **Step 3: cli.py を実装**

`tools/validator/src/plk_validator/cli.py`:

```python
"""plk-validate: PLK 知識ベースの規約バリデータ CLI。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from plk_validator.gitchecks import check_id_immutability, check_promotion
from plk_validator.repo_checks import iter_fact_files, validate_repo
from plk_validator.secrets import scan_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PLK 知識ベースの規約検証")
    parser.add_argument("knowledge_dir", help="knowledge/ ディレクトリのパス")
    parser.add_argument(
        "--base",
        help="git 差分チェックの基準 ref（PR CI で origin/<base_branch> を渡す）",
    )
    args = parser.parse_args(argv)

    knowledge = Path(args.knowledge_dir)
    errors = validate_repo(knowledge)

    for path in iter_fact_files(knowledge):
        for finding in scan_file(path):
            errors.append(f"{path.relative_to(knowledge)}: シークレット検知 [{finding}]")

    if args.base:
        repo_dir = knowledge.parent  # knowledge/ の親 = リポジトリルート
        errors += check_promotion(repo_dir, args.base)
        errors += check_id_immutability(repo_dir, args.base)

    if errors:
        for e in errors:
            print(f"NG {e}")
        print(f"\n{len(errors)} 件の規約違反")
        return 1
    print("OK 全ファイル規約準拠")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: テストが通り、実リポジトリでも動くことを確認**

Run: `cd tools/validator && uv run pytest tests/ -v`
Expected: 全テスト passed（累計 35）

Run: `cd tools/validator && uv run plk-validate ../../knowledge`
Expected: `OK 全ファイル規約準拠`（まだファクト 0 件なので素通り）

- [ ] **Step 5: Commit**

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
git add tools/validator
git commit -m "feat: plk-validate CLI（スキーマ+横断+シークレット+git チェック統合）"
```

---

### Task 8: GitHub リポジトリ作成と CI ワークフロー

**Files:**
- Create: `.github/workflows/validate.yml`

**Interfaces:**
- Consumes: `plk-validate` CLI（Task 7）
- Produces: push/PR で自動実行される規約 CI。昇格 PR ルールは `--base` 付き実行で検証される

- [ ] **Step 1: CI ワークフローを作成**

`.github/workflows/validate.yml`:

```yaml
name: validate-knowledge
on:
  push:
    branches: [main]
  pull_request:

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v5
      - name: 規約バリデーション
        run: cd tools/validator && uv run plk-validate ../../knowledge
      - name: 昇格 PR・id 不変性チェック
        if: github.event_name == 'pull_request'
        run: cd tools/validator && uv run plk-validate ../../knowledge --base "origin/${{ github.base_ref }}"
      - name: バリデータ自体のテスト
        run: cd tools/validator && uv run pytest tests/ -q

  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
git add .github
git commit -m "ci: 規約バリデーション + gitleaks の GitHub Actions"
```

- [ ] **Step 3: GitHub リポジトリ作成（⚠️ 外部書き込み — ユーザーの明示承認を得てから実行）**

実行前にユーザーへ「private リポジトリ `agent-organization` を GitHub に作成して push してよいか」を確認する。承認後:

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
gh repo create agent-organization --private --source . --push
```

Expected: リポジトリ URL が表示され、main が push される

- [ ] **Step 4: CI が green になることを確認**

Run: `gh run watch --exit-status` （または `gh run list --limit 1`）
Expected: `validate-knowledge` ワークフローが success

---

### Task 9: new_fact 雛形スクリプトとシード知見 20 件+

**Files:**
- Create: `tools/validator/scripts/new_fact.py`
- Create: `knowledge/domains/**/*.md`（20 件以上）、うち同一トピックの人工矛盾系列 1 組（2〜3 件）

**Interfaces:**
- Consumes: `plk-validate` CLI（Task 7）
- Produces: Phase 0 完了条件を満たすシードコーパス。Phase 1 の検索評価・ingest 実測の入力データ

- [ ] **Step 1: 雛形スクリプトを作成**

`tools/validator/scripts/new_fact.py`:

```python
"""新規ファクトの雛形を生成する。

usage: uv run python scripts/new_fact.py domains/tax slug-name
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from ulid import ULID

TEMPLATE = """---
id: {id}
kind: knowhow
statement: ""
why: ""
how_to_apply: ""
source: ""
source_type: user
namespace: {namespace}
status: active
invalidation_reason: null
written_by: masahiro
created_at: {created_at}
invalidated_at: null
superseded_by: null
tags: []
---

"""


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    subdir, slug = sys.argv[1], sys.argv[2]
    knowledge = Path(__file__).resolve().parents[3] / "knowledge"
    parts = subdir.strip("/").split("/")
    if parts[0] == "shared":
        ns = "plk.shared"
    elif parts[0] == "quarantine":
        ns = "plk.quarantine"
    elif parts[0] == "domains" and len(parts) == 2:
        ns = f"plk.domain.{parts[1]}"
    else:
        print(f"不正な配置先: {subdir}")
        return 1
    path = knowledge / subdir / f"{slug}.md"
    if path.exists():
        print(f"既に存在: {path}")
        return 1
    path.write_text(
        TEMPLATE.format(
            id=str(ULID()),
            namespace=ns,
            created_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        ),
        encoding="utf-8",
    )
    print(f"作成: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 動作確認（生成 → バリデータで空フィールドが弾かれること）**

```bash
cd tools/validator
uv run python scripts/new_fact.py domains/dev test-scaffold
uv run plk-validate ../../knowledge; echo "exit=$?"
```
Expected: `NG ...test-scaffold.md: statement: ...` を含む違反が出て exit=1（雛形は空なので**弾かれるのが正しい**）

確認後に削除: `rm ../../knowledge/domains/dev/test-scaffold.md`

- [ ] **Step 3: シード知見の棚卸し・執筆（20 件以上）**

ソース候補から実ノウハウを抽出し、`new_fact.py` で 1 件ずつ作成して埋める:

- Claude Code メモリ（`~/.claude/projects/-Users-masahiro-dev-byteflare-co/memory/`）— 持続化補助金・freee 事業所切替・領収書ブラックリスト等
- `~/Documents/personal-records/`（minshaho / nenkin 等）→ shaho ドメイン
- backoffice-automation リポジトリの運用知見 → backoffice ドメイン
- 過去セッションで得た開発ノウハウ（例: 本設計プロセスで検証済みの技術ファクト）→ dev ドメイン

執筆時のルール（規約準拠のため）:
- `statement` は 20〜200 字で「何が言えるか」を一文で
- `why` に根拠（一次情報・実体験の経緯）、`how_to_apply` に適用条件
- tax/legal/shaho は必ず https URL の一次情報 source を含める
- 会社ファクト（Notion にあるもの）は複製せず `source` に Notion 参照を書き、知見（判断ルール）だけを書く

- [ ] **Step 4: 人工矛盾系列を 1 組作成（Phase 1 の矛盾検出評価用シード）**

同一トピックで方針が変遷した系列を 2〜3 件で表現する。例（トピックは実情に合わせて差し替え可。ただし**構造は以下と同一に**）:

1. ファクト A（旧方針）: `status: invalidated`、`invalidation_reason` に変更理由、`superseded_by` にファクト B の id、`invalidated_at` 設定
2. ファクト B（現方針）: `status: active`、`why` に「A から変更した経緯」を記載

例: 「freee の事業所は 5 月末までコトサーチを使う」（invalidated）→「6 月以降は株式会社 Byteflare に切替」（active）

- [ ] **Step 5: 全件バリデーション**

```bash
cd tools/validator && uv run plk-validate ../../knowledge
```
Expected: `OK 全ファイル規約準拠`

```bash
find ../../knowledge -name "*.md" ! -name "CONVENTIONS.md" | wc -l
```
Expected: 20 以上

- [ ] **Step 6: Commit & push**

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
git add tools/validator/scripts knowledge/
git commit -m "feat: new_fact 雛形スクリプトとシード知見（人工矛盾系列込み）"
git push
gh run watch --exit-status
```
Expected: CI success

---

## Phase 0 完了条件（設計書 §11）

- [ ] `knowledge/` 構造＋規約 v1（CONVENTIONS.md）が存在する
- [ ] CI バリデータ（id 一意性・namespace 一致・シークレット・昇格 PR チェック）が green
- [ ] 実ノウハウ 20 件以上が規約準拠で存在し、人工矛盾系列（update 連鎖）を含む
