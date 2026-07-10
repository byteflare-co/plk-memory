# plk-memory Phase 1（PoC ローカル）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `plk-memory` リポジトリ（FastAPI + FastMCP + graphiti-core + FalkorDB）を新設し、agent-organization の knowledge/（SoT）を派生索引化して MCP ツール（plk_search/add/invalidate/history/status）で提供する。シード 23 件で日本語検索精度・ingest コストをベースライン対照付きで実測し、チェックポイント判断の材料を出す。

**Architecture:** Git=SoT・Graphiti=再構築可能な派生索引（設計書 v1.0 §3〜§6）。サーバーは専用 clone（~/.plk/data-repo、リモート=GitHub）を持ち、書き込みは validate→commit→push（単一 writer）、索引は level-triggered 同期（last_ingested_commit 起点の git diff）。Byteflare モードは group 畳み込み（plk.main + plk.quarantine）。graphiti は AnthropicClient（Haiku）＋ Ollama OpenAI 互換 embedder（bge-m3）＋ reranker なし。

**Tech Stack:** Python 3.12+ / uv / FastAPI / FastMCP 3.x（`mcp>=1.27,<2` ピン）/ graphiti-core[anthropic,falkordb] 0.29.x / FalkorDB（Docker）/ Ollama（bge-m3）/ python-frontmatter / pydantic-settings / pytest + pytest-asyncio

**設計書（SoT）:** `agent-memory/specs/2026-07-02-plk-memory-design.md` §3〜§9・§11 Phase 1
**データリポジトリ:** `/Users/masahiro/dev/byteflare-co/agent-organization`（GitHub: cutsome/agent-organization）— バリデータ `tools/validator`（plk-validator パッケージ）をパス依存で再利用

## Global Constraints

- 新規リポジトリ: `/Users/masahiro/dev/byteflare-co/plk-memory`（コードごと 組織展開 逆輸入する単位。Byteflare 固有値は環境変数へ）
- 依存ピン: `mcp>=1.27,<2` / `fastmcp>=3,<4` / `graphiti-core[anthropic,falkordb]>=0.29.2,<0.30` / `falkordb` は graphiti extras 経由
- Python `requires-python = ">=3.12"`
- **SoT = GitHub リモート main**。サーバーは専用 clone を使い、人間の編集ディレクトリ（~/dev/byteflare-co/agent-organization）には触れない
- 書き込みパス: バリデーション（plk_validator.schema.Fact）→ シークレットスキャン → commit → push（fetch→rebase→push リトライ、コンフリクトはエラー返却）→ 非同期 ingest
- **API 経由の source_type は `agent` 上限**（`user` 指定は拒否）。**written_by はトークンから導出**（申告無視）。**`plk.shared` への API 書き込みは拒否**
- group マッピング: Byteflare モード = 全 namespace→`plk.main`、`plk.quarantine` のみ分離。設定で per-namespace に切替可能
- エピソード名 = `{id}@{content_hash}`（hash は意味フィールドの canonical JSON + 本文で計算）。エピソード本文は日本語自然文テンプレート（識別子はエンティティ抽出対象から除外）
- `status: invalidated` のファクトはグラフから削除（検索デフォルトは active のみ。履歴は Git 側）
- **全 MCP ツールは 60 秒以内に応答**。reindex は REST の非同期ジョブ（実行中の書き込みは 503 = メンテナンスモード）
- 認証: クライアント別静的 Bearer（環境変数 `PLK_TOKENS` の JSON、token→client 名）。admin は別トークン。127.0.0.1 bind
- graceful degradation: グラフ/embedder 停止時、plk_search はエラーでなく「索引不可/縮退」を返す。/healthz は認証なし・即応
- **graphiti-core 0.29.x の API はコード例と異なる可能性がある**: GraphIndex（Task 6）のみ「インストール版のソース/ドキュメントで signature を確認して適応し、逸脱を report に記録する」ライセンスあり。他モジュールは計画どおり
- テスト: 単体（tests/）は外部 API・Docker 不要で完結。live 統合（tests_live/）は FalkorDB + Ollama + ANTHROPIC_API_KEY 前提で `-m live` マーカー、CI では skip
- コミットは各タスク末尾で必ず行う

## File Structure

```
plk-memory/
  pyproject.toml / .gitignore / README.md / docker-compose.yml / .env.example
  src/plk_memory/
    __init__.py
    settings.py      # 全設定（pydantic-settings、env prefix PLK_）と group マッピング
    rendering.py     # エピソード日本語テンプレート + content_hash
    state.py         # 同期状態（last_ingested_commit・fact→episode 対応・dead letters）
    gitstore.py      # 専用 clone・単一 writer（commit→push ループ）・単一インスタンスガード
    facts.py         # FactService（add/invalidate/get/list/history、バリデータ統合）
    graphindex.py    # graphiti-core ラッパー（upsert/delete/search/clear、triplet モード）
    sync.py          # level-triggered 同期エンジン + reindex
    auth.py          # Bearer 認証ミドルウェア + current_client contextvar
    usage_log.py     # 利用ログ JSONL
    mcp_tools.py     # MCP ツール定義（FastMCP）
    app.py           # FastAPI 組み立て（REST→MCP mount 順・lifespan）
  tests/             # 単体テスト（FakeGraphIndex・一時 git repo）
  tests_live/        # live 統合テスト（-m live）
  scripts/eval/      # queries.yaml + run_eval.py（ベースライン対照込み）
  clients/           # 接続テンプレート + 検索動線 snippet（CC/Codex/Hermes/Agent SDK）
```

---

### Task 1: リポジトリ雛形と settings

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`
- Create: `src/plk_memory/__init__.py`, `src/plk_memory/settings.py`
- Test: `tests/__init__.py`, `tests/test_settings.py`

**Interfaces:**
- Consumes: なし
- Produces: `Settings`（pydantic-settings、`get_settings()` シングルトン無しの素直なクラス）。`settings.group_for(namespace) -> str`、`settings.knowledge_dir -> Path`、`settings.path_for_namespace(namespace) -> str`（相対ディレクトリ）を後続全タスクが使う

- [ ] **Step 1: git init と雛形**

```bash
mkdir -p /Users/masahiro/dev/byteflare-co/plk-memory && cd /Users/masahiro/dev/byteflare-co/plk-memory
git init -b main
```

`.gitignore`:

```
__pycache__/
.venv/
.pytest_cache/
.env
.plk/
*.egg-info/
.superpowers/
.ruff_cache/
```

`pyproject.toml`:

```toml
[project]
name = "plk-memory"
version = "0.1.0"
description = "PLK メモリ基盤 — Git=SoT + Graphiti 派生索引の MCP メモリサーバー"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "fastmcp>=3,<4",
    "mcp>=1.27,<2",
    "graphiti-core[anthropic,falkordb]>=0.29.2,<0.30",
    "python-frontmatter>=1.1",
    "python-ulid>=2.7",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "httpx>=0.27",
    "pyyaml>=6",
    "plk-validator",
]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "ruff>=0.6", "pyright>=1.1"]

[tool.uv.sources]
plk-validator = { path = "../agent-organization/tools/validator", editable = true }

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = ["live: 外部サービス（FalkorDB/Ollama/Anthropic）が必要な統合テスト"]
addopts = "-m 'not live'"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/plk_memory"]
```

`.env.example`:

```
PLK_DATA_REPO_URL=git@github.com:cutsome/agent-organization.git
PLK_TOKENS={"dev-token-claude-code":"claude-code","dev-token-codex":"codex","dev-token-hermes":"hermes","dev-token-agent":"custom-agent"}
PLK_ADMIN_TOKEN=dev-admin-token
ANTHROPIC_API_KEY=（環境から継承）
```

`README.md` は表題と「起動方法は Task 10 で追記」の 2 行で開始。

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_settings.py`:

```python
from pathlib import Path

from plk_memory.settings import Settings


def make(**kw) -> Settings:
    base = dict(tokens={"t1": "claude-code"}, admin_token="adm", _env_file=None)
    base.update(kw)
    return Settings(**base)


def test_group_single_mode_folds_namespaces():
    s = make(group_mode="single")
    assert s.group_for("plk.domain.tax") == "plk.main"
    assert s.group_for("plk.shared") == "plk.main"
    assert s.group_for("plk.quarantine") == "plk.quarantine"


def test_group_per_namespace_mode():
    s = make(group_mode="per-namespace")
    assert s.group_for("plk.domain.tax") == "plk.domain.tax"
    assert s.group_for("plk.quarantine") == "plk.quarantine"


def test_all_groups_covers_both_modes():
    assert set(make(group_mode="single").all_groups()) == {"plk.main", "plk.quarantine"}
    per = make(group_mode="per-namespace").all_groups()
    assert "plk.domain.tax" in per and "plk.shared" in per and "plk.quarantine" in per


def test_path_for_namespace():
    s = make()
    assert s.path_for_namespace("plk.domain.tax") == "knowledge/domains/tax"
    assert s.path_for_namespace("plk.quarantine") == "knowledge/quarantine"
    assert s.path_for_namespace("plk.shared") == "knowledge/shared"


def test_knowledge_dir_derived_from_repo_path(tmp_path):
    s = make(data_repo_path=tmp_path / "repo")
    assert s.knowledge_dir == tmp_path / "repo" / "knowledge"
```

- [ ] **Step 3: RED 確認**

Run: `cd /Users/masahiro/dev/byteflare-co/plk-memory && uv run pytest tests/ -v`
Expected: ERROR（`No module named 'plk_memory.settings'`）

- [ ] **Step 4: settings.py を実装**

```python
"""plk-memory 全設定。環境変数 PLK_* で上書き（設計書 §3: Byteflare 固有値は設定へ）。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DOMAINS = ("tax", "legal", "shaho", "dev", "backoffice", "biz")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLK_", env_file=".env", extra="ignore")

    # データリポジトリ（SoT = リモート main）
    data_repo_url: str = ""
    data_repo_path: Path = Path.home() / ".plk" / "data-repo"
    knowledge_subdir: str = "knowledge"

    # ローカル状態
    state_path: Path = Path.home() / ".plk" / "state.json"
    usage_log_path: Path = Path.home() / ".plk" / "usage.jsonl"
    lock_path: Path = Path.home() / ".plk" / "writer.lock"

    # 認証（token -> client 名）
    tokens: dict[str, str] = {}
    admin_token: str = ""

    # group マッピング（Byteflare = single、組織展開 = per-namespace）
    group_mode: str = "single"
    main_group: str = "plk.main"
    quarantine_group: str = "plk.quarantine"

    # ingest
    ingest_mode: str = "episode"  # episode | triplet
    anthropic_model: str = "claude-haiku-4-5-latest"
    embedder_base_url: str = "http://localhost:11434/v1"  # Ollama OpenAI 互換
    embedder_model: str = "bge-m3"
    embedder_api_key: str = "ollama"
    embedding_dim: int = 1024

    # FalkorDB
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379

    # 同期
    sync_interval_seconds: int = 600

    # サーバー
    bind_host: str = "127.0.0.1"
    bind_port: int = 8735

    def group_for(self, namespace: str) -> str:
        if namespace == "plk.quarantine":
            return self.quarantine_group
        if self.group_mode == "per-namespace":
            return namespace
        return self.main_group

    def all_groups(self) -> list[str]:
        if self.group_mode == "per-namespace":
            return [f"plk.domain.{d}" for d in DOMAINS] + ["plk.shared", self.quarantine_group]
        return [self.main_group, self.quarantine_group]

    def path_for_namespace(self, namespace: str) -> str:
        if namespace == "plk.shared":
            return f"{self.knowledge_subdir}/shared"
        if namespace == "plk.quarantine":
            return f"{self.knowledge_subdir}/quarantine"
        domain = namespace.removeprefix("plk.domain.")
        return f"{self.knowledge_subdir}/domains/{domain}"

    @property
    def knowledge_dir(self) -> Path:
        return self.data_repo_path / self.knowledge_subdir
```

- [ ] **Step 5: GREEN 確認**

Run: `uv run pytest tests/ -v`
Expected: 5 passed（plk-validator のパス依存が解決されること自体も確認になる）

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: plk-memory 雛形と settings（group マッピング・パス規則）"
```

---

### Task 2: rendering（エピソード日本語テンプレート + content_hash）

**Files:**
- Create: `src/plk_memory/rendering.py`
- Test: `tests/test_rendering.py`

**Interfaces:**
- Consumes: `frontmatter.Post`
- Produces: `render_episode(post) -> str`、`content_hash(post) -> str`（16 hex）、`episode_name(post) -> str`（`{id}@{hash}`）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_rendering.py`:

```python
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
```

- [ ] **Step 2: RED 確認** — `uv run pytest tests/test_rendering.py -v` → ERROR（module not found）

- [ ] **Step 3: rendering.py を実装**

```python
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
```

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/ -v` → 9 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: エピソード日本語レンダリングと正規化 content_hash"
```

---

### Task 3: state（同期状態ストア）

**Files:**
- Create: `src/plk_memory/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: なし
- Produces: `SyncState`（dataclass 相当）と `StateStore.load() -> SyncState` / `StateStore.save(state)`。`SyncState.last_ingested_commit: str | None`、`SyncState.facts: dict[str, FactIndexEntry]`（fact_id → episode_uuids/content_hash/group_id）、`SyncState.dead_letters: dict[str, str]`（path → error）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_state.py`:

```python
from plk_memory.state import FactIndexEntry, StateStore, SyncState


def test_roundtrip(tmp_path):
    store = StateStore(tmp_path / "state.json")
    state = SyncState(
        last_ingested_commit="abc1234",
        facts={"01X": FactIndexEntry(episode_uuids=["u1"], content_hash="h" * 16, group_id="plk.main")},
        dead_letters={"knowledge/domains/tax/x.md": "boom"},
    )
    store.save(state)
    loaded = store.load()
    assert loaded == state


def test_load_missing_returns_empty(tmp_path):
    state = StateStore(tmp_path / "none.json").load()
    assert state.last_ingested_commit is None
    assert state.facts == {} and state.dead_letters == {}


def test_save_is_atomic_no_partial_file(tmp_path):
    # tmp ファイル経由の os.replace で書く（クラッシュで壊れた JSON を残さない）
    path = tmp_path / "state.json"
    store = StateStore(path)
    store.save(SyncState())
    assert path.exists()
    assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 2: RED 確認** — module not found

- [ ] **Step 3: state.py を実装**

```python
"""同期状態の永続化（設計書 §6-3: last_ingested_commit・fact→episode 対応・dead letters）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel


class FactIndexEntry(BaseModel):
    episode_uuids: list[str] = []
    content_hash: str = ""
    group_id: str = ""


class SyncState(BaseModel):
    last_ingested_commit: str | None = None
    facts: dict[str, FactIndexEntry] = {}
    dead_letters: dict[str, str] = {}


class StateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> SyncState:
        if not self.path.exists():
            return SyncState()
        return SyncState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, state: SyncState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(state.model_dump_json(indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
```

（テストの `*.tmp` glob は `.json.tmp` を拾う — `glob("*.tmp")` は suffix 一致で OK）

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/ -v` → 12 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: 同期状態ストア（atomic save）"
```

---

### Task 4: gitstore（専用 clone・単一 writer・push ループ）

**Files:**
- Create: `src/plk_memory/gitstore.py`
- Test: `tests/test_gitstore.py`

**Interfaces:**
- Consumes: `Settings`
- Produces:
  - `GitStore(settings)` — `ensure_repo()`（clone or fetch。プロセス生存期間の排他 flock 取得 = 単一インスタンスガード。取得失敗は `AnotherInstanceRunning`）
  - `head() -> str` / `git(*args) -> str`（subprocess ラッパー、後続タスクも使用）
  - `async commit_and_push(rel_paths: list[str], message: str) -> str`（asyncio.Lock 直列化。add→commit→push。push 拒否時は fetch→rebase→push を最大 3 回、rebase コンフリクトは `rebase --abort` して `WriteConflict`）
  - `fetch_and_ff() -> bool`（fetch して fast-forward。履歴書き換え検出時は `HistoryRewritten` を投げ自動 reset しない — 設計書 §6-6）
  - 例外: `WriteConflict` / `HistoryRewritten` / `AnotherInstanceRunning`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_gitstore.py`（bare リポジトリを「リモート」に見立てて実 git で検証）:

```python
import subprocess
from pathlib import Path

import pytest

from plk_memory.gitstore import GitStore, HistoryRewritten, WriteConflict
from plk_memory.settings import Settings


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def remote(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
    sh(seed, "config", "user.email", "t@t")
    sh(seed, "config", "user.name", "t")
    (seed / "knowledge").mkdir()
    (seed / "knowledge" / "a.md").write_text("a", encoding="utf-8")
    sh(seed, "add", "-A")
    sh(seed, "commit", "-m", "init")
    sh(seed, "push", "origin", "main")
    return origin, seed


def make_store(tmp_path, origin) -> GitStore:
    s = Settings(
        data_repo_url=str(origin),
        data_repo_path=tmp_path / "server-clone",
        lock_path=tmp_path / "writer.lock",
        tokens={"t": "c"}, admin_token="a", _env_file=None,
    )
    store = GitStore(s)
    store.ensure_repo()
    return store


def test_ensure_repo_clones(remote, tmp_path):
    origin, _ = remote
    store = make_store(tmp_path, origin)
    assert (store.settings.data_repo_path / "knowledge" / "a.md").exists()


def test_single_instance_guard(remote, tmp_path):
    origin, _ = remote
    store = make_store(tmp_path, origin)
    from plk_memory.gitstore import AnotherInstanceRunning
    second = GitStore(store.settings)
    with pytest.raises(AnotherInstanceRunning):
        second.ensure_repo()


async def test_commit_and_push_reaches_remote(remote, tmp_path):
    origin, seed = remote
    store = make_store(tmp_path, origin)
    (store.settings.data_repo_path / "knowledge" / "b.md").write_text("b", encoding="utf-8")
    sha = await store.commit_and_push(["knowledge/b.md"], "add b")
    sh(seed, "pull")
    assert (seed / "knowledge" / "b.md").exists()
    assert sha in sh(seed, "log", "--format=%H", "-1")


async def test_push_rejected_then_rebase_succeeds(remote, tmp_path):
    origin, seed = remote
    store = make_store(tmp_path, origin)
    # リモートに他者の commit を先行させる（non-conflicting）
    (seed / "knowledge" / "other.md").write_text("o", encoding="utf-8")
    sh(seed, "add", "-A"); sh(seed, "commit", "-m", "other"); sh(seed, "push")
    (store.settings.data_repo_path / "knowledge" / "b.md").write_text("b", encoding="utf-8")
    await store.commit_and_push(["knowledge/b.md"], "add b")
    log = sh(seed, "pull") + sh(seed, "log", "--oneline")
    assert "add b" in log and "other" in log


async def test_conflicting_push_raises_write_conflict(remote, tmp_path):
    origin, seed = remote
    store = make_store(tmp_path, origin)
    # 同一ファイルをリモートとローカルで別内容に
    (seed / "knowledge" / "a.md").write_text("remote version", encoding="utf-8")
    sh(seed, "add", "-A"); sh(seed, "commit", "-m", "remote edit"); sh(seed, "push")
    (store.settings.data_repo_path / "knowledge" / "a.md").write_text("local version", encoding="utf-8")
    with pytest.raises(WriteConflict):
        await store.commit_and_push(["knowledge/a.md"], "local edit")
    # 作業ツリーが壊れていない（rebase 中で止まっていない）こと
    status = store.git("status", "--porcelain")
    assert "rebase" not in store.git("status").lower()


def test_history_rewrite_detected_not_reset(remote, tmp_path):
    origin, seed = remote
    store = make_store(tmp_path, origin)
    # リモート履歴を書き換え（amend + force push）
    sh(seed, "commit", "--amend", "-m", "rewritten")
    sh(seed, "push", "--force")
    with pytest.raises(HistoryRewritten):
        store.fetch_and_ff()
```

- [ ] **Step 2: RED 確認** — module not found

- [ ] **Step 3: gitstore.py を実装**

```python
"""サーバー専用 clone と単一 writer（設計書 §6）。

- SoT = リモート main。ローカル commit は push 完了までは「耐久化された意図」
- 書き込みは asyncio.Lock で直列化し fetch→rebase→push リトライ
- 履歴書き換え検出時は自動 reset せず HistoryRewritten（人間介入待ち）
- flock による単一インスタンスガード（uvicorn 多重起動・二重デーモンの fail-fast）
"""

from __future__ import annotations

import asyncio
import fcntl
import subprocess
from pathlib import Path

from plk_memory.settings import Settings


class WriteConflict(RuntimeError):
    pass


class HistoryRewritten(RuntimeError):
    pass


class AnotherInstanceRunning(RuntimeError):
    pass


class GitStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = asyncio.Lock()
        self._flock_fh = None

    def git(self, *args: str) -> str:
        r = subprocess.run(
            ["git", "-C", str(self.settings.data_repo_path), *args],
            capture_output=True, text=True, check=True,
        )
        return r.stdout

    def ensure_repo(self) -> None:
        self._acquire_instance_lock()
        path = self.settings.data_repo_path
        if not (path / ".git").exists():
            if not self.settings.data_repo_url:
                raise RuntimeError("PLK_DATA_REPO_URL が未設定で clone も存在しない")
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "-b", "main", self.settings.data_repo_url, str(path)],
                capture_output=True, text=True, check=True,
            )
            self.git("config", "user.email", "plk-memory@byteflare.co")
            self.git("config", "user.name", "plk-memory")

    def _acquire_instance_lock(self) -> None:
        self.settings.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.settings.lock_path, "w")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            fh.close()
            raise AnotherInstanceRunning(
                "別の plk-memory インスタンスが writer ロックを保持している（単一レプリカ必須）"
            ) from e
        self._flock_fh = fh  # プロセス生存期間保持

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def fetch_and_ff(self) -> bool:
        """fetch して fast-forward。履歴書き換えは HistoryRewritten。戻り値: 更新があったか。"""
        self.git("fetch", "origin", "main")
        local = self.head()
        remote = self.git("rev-parse", "origin/main").strip()
        if local == remote:
            return False
        base = self.git("merge-base", "HEAD", "origin/main").strip()
        if base == local:
            self.git("merge", "--ff-only", "origin/main")
            return True
        if base != remote:
            # 双方に独自 commit（未 push あり）は commit_and_push の rebase に委ねる
            return False
        raise HistoryRewritten("リモート main の履歴が書き換えられている（自動 reset しない）")

    async def commit_and_push(self, rel_paths: list[str], message: str) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._commit_and_push_sync, rel_paths, message)

    def _commit_and_push_sync(self, rel_paths: list[str], message: str) -> str:
        self.git("add", "--", *rel_paths)
        self.git("commit", "-m", message)
        sha = self.head()
        for _ in range(3):
            try:
                self.git("push", "origin", "main")
                return self.head()
            except subprocess.CalledProcessError:
                self.git("fetch", "origin", "main")
                try:
                    self.git("rebase", "origin/main")
                except subprocess.CalledProcessError as e:
                    self.git("rebase", "--abort")
                    # rebase を諦めた自 commit を巻き戻し、SoT（リモート）に合わせる
                    self.git("reset", "--hard", "origin/main")
                    raise WriteConflict(
                        f"リモートと競合したため書き込みを破棄した（再試行が必要）: {message}"
                    ) from e
        raise WriteConflict(f"push リトライ上限超過: {message}")
```

注意: `HistoryRewritten` の merge-base 判定 — 「base が local でも remote でもない」= 双方に commit がある通常の分岐で、これは rebase で解決する分岐なので例外にしない。「base ≠ remote かつ base ≠ local かつ local に未 push が無い」ケースが履歴書き換え。上記実装は「local == merge-base → ff」「未 push commit がある分岐 → False（rebase は書き込み時に処理）」「それ以外 → HistoryRewritten」という近似。テスト `test_history_rewrite_detected_not_reset` では amend により base が local でも remote でもなく、server-clone に未 push commit は無い → HistoryRewritten になることを確認する。実装で判定を厳密化する場合も、**自動 reset をしない**不変条件は維持すること。

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/ -v` → 19 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: gitstore（専用clone・単一writer・push ループ・履歴書換え検出）"
```

---

### Task 5: facts（FactService — 書き込みパスとバリデータ統合）

**Files:**
- Create: `src/plk_memory/facts.py`
- Test: `tests/test_facts.py`

**Interfaces:**
- Consumes: `GitStore`（Task 4）、`Settings`、`plk_validator.schema.Fact`、`plk_validator.secrets.scan_file`、`rendering`
- Produces: `FactService(store, settings)`:
  - `index() -> dict[str, str]`（fact_id → rel_path。毎回スキャン、コーパス小なので十分）
  - `get(fact_id) -> tuple[frontmatter.Post, str]`（無ければ `FactNotFound`）
  - `list_posts() -> list[tuple[frontmatter.Post, str]]`
  - `async add(*, client, namespace, kind, statement, why, how_to_apply, source, tags=None, body="", slug=None, source_type="agent", supersedes=None) -> str`（新 id を返す）
  - `async invalidate(fact_id, reason, client) -> None`
  - `history(fact_id) -> dict`（`commits`: git log、`superseded_by` / `supersedes_chain`）
  - 例外: `FactError`（バリデーション/ポリシー違反）、`FactNotFound`

**ポリシー（Global Constraints の実装点）:**
- `source_type == "user"` 指定は拒否（user は人間の PR 直編集のみ）
- `namespace == "plk.shared"` への add は拒否（昇格経由のみ）
- `source_type == "external-untrusted"` は `namespace == "plk.quarantine"` 必須
- `written_by` は引数 `client`（トークン由来）で強制設定
- シークレット検知時はファイルを削除して `FactError`
- `supersedes` は同一 commit で旧ファクトの invalidated 化まで行う（アトミック）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_facts.py`（Task 4 の `remote` fixture を conftest に移して共用する — `tests/conftest.py` に `remote` と `make_store` を移動し、`test_gitstore.py` は conftest から import する形にリファクタしてよい）:

```python
import pytest

from plk_memory.facts import FactError, FactNotFound, FactService

VALID = dict(
    namespace="plk.domain.tax",
    kind="knowhow",
    statement="法人税の中間申告は前期税額20万円超で必要になる制度である",
    why="国税庁タックスアンサーの中間申告の要件に明記されているため",
    how_to_apply="設立2期目以降、前期法人税額を確認して要否を判定する",
    source="https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5000.htm",
    tags=["中間申告"],
    body="詳細メモ。",
)


@pytest.fixture
def svc(remote, tmp_path):
    origin, _ = remote
    from tests.conftest import make_store
    store = make_store(tmp_path, origin)
    return FactService(store, store.settings)


async def test_add_creates_valid_fact_and_pushes(svc, remote):
    fact_id = await svc.add(client="claude-code", **VALID)
    post, rel = svc.get(fact_id)
    assert post["written_by"] == "claude-code"
    assert post["source_type"] == "agent"
    assert rel.startswith("knowledge/domains/tax/")
    # push 済み = origin に届いている
    assert svc.store.git("rev-list", "--count", "origin/main..HEAD").strip() == "0"


async def test_add_rejects_user_source_type(svc):
    with pytest.raises(FactError, match="user"):
        await svc.add(client="claude-code", source_type="user", **VALID)


async def test_add_rejects_shared_namespace(svc):
    args = {**VALID, "namespace": "plk.shared"}
    with pytest.raises(FactError, match="shared"):
        await svc.add(client="claude-code", **args)


async def test_untrusted_requires_quarantine(svc):
    args = {**VALID, "namespace": "plk.domain.dev"}
    with pytest.raises(FactError, match="quarantine"):
        await svc.add(client="claude-code", source_type="external-untrusted", **args)


async def test_add_rejects_secret_and_cleans_up(svc):
    args = {**VALID, "body": "キー: " + "sk-ant-" + "api03-" + "x" * 24}
    with pytest.raises(FactError, match="シークレット"):
        await svc.add(client="claude-code", **args)
    # 作業ツリーに書きかけファイルが残っていない
    assert svc.store.git("status", "--porcelain").strip() == ""


async def test_add_rejects_invalid_content(svc):
    args = {**VALID, "statement": "短い"}
    with pytest.raises(FactError):
        await svc.add(client="claude-code", **args)


async def test_supersedes_is_atomic_single_commit(svc):
    old_id = await svc.add(client="claude-code", **VALID)
    new_args = {**VALID, "statement": "中間申告の判定は前期税額だけでなく仮決算方式の選択も併せて検討する"}
    before = svc.store.git("rev-list", "--count", "HEAD").strip()
    new_id = await svc.add(client="claude-code", supersedes=[old_id], **new_args)
    after = svc.store.git("rev-list", "--count", "HEAD").strip()
    assert int(after) == int(before) + 1  # 追加+無効化が 1 commit
    old_post, _ = svc.get(old_id)
    assert old_post["status"] == "invalidated"
    assert old_post["superseded_by"] == new_id
    assert old_post["invalidation_reason"]


async def test_invalidate_writes_reason(svc):
    fact_id = await svc.add(client="claude-code", **VALID)
    await svc.invalidate(fact_id, "制度改正で前提が変わった", client="codex")
    post, _ = svc.get(fact_id)
    assert post["status"] == "invalidated"
    assert post["invalidation_reason"] == "制度改正で前提が変わった"


async def test_history_returns_commits_and_chain(svc):
    old_id = await svc.add(client="claude-code", **VALID)
    new_args = {**VALID, "statement": "中間申告の判定は前期税額だけでなく仮決算方式の選択も併せて検討する"}
    new_id = await svc.add(client="claude-code", supersedes=[old_id], **new_args)
    h = svc.history(old_id)
    assert len(h["commits"]) >= 1
    assert h["superseded_by"] == new_id


def test_get_missing_raises(svc):
    with pytest.raises(FactNotFound):
        svc.get("01JZC2V7E8B3F4G5H6J7K8M9ZZ")
```

- [ ] **Step 2: RED 確認** — module not found

- [ ] **Step 3: facts.py を実装**

```python
"""FactService: 書き込みパス（設計書 §6-1〜2）とポリシー強制（§7）。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
from pydantic import ValidationError
from ulid import ULID

from plk_validator.schema import Fact
from plk_validator.secrets import scan_file

from plk_memory.gitstore import GitStore
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
        return {post["id"]: rel for post, rel in self.list_posts()}

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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(frontmatter.dumps(frontmatter.Post(body, **meta)), encoding="utf-8")

        findings = scan_file(path)
        if findings:
            path.unlink()
            raise FactError(f"シークレット検知のため拒否: {findings}")

        changed = [rel]
        for old_id in supersedes or []:
            try:
                old_post, old_rel = self.get(old_id)
            except FactNotFound:
                path.unlink()
                raise FactError(f"supersedes 対象が存在しない: {old_id}")
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
```

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/ -v` → 29 passed（gitstore の conftest リファクタ後も全て green）

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: FactService（バリデータ統合・ポリシー強制・supersedes アトミック）"
```

---

### Task 6: graphindex（graphiti-core ラッパー）⚠️ verify-and-adapt

**Files:**
- Create: `src/plk_memory/graphindex.py`
- Create: `tests/fakes.py`（FakeGraphIndex — Task 7/9 が使用）
- Test: `tests/test_graphindex_mapping.py`（純ロジックのみ）
- Test: `tests_live/test_graph_smoke.py`（`-m live`）

**Interfaces:**
- Consumes: `Settings`、`rendering`、`state.FactIndexEntry`
- Produces（**この interface は固定。内部実装は graphiti 0.29.x の実 API に合わせて適応してよい。適応内容は必ず report に記録**）:

```python
class SearchHit(BaseModel):
    fact_id: str
    fact_text: str      # ヒットしたグラフ上の fact（エッジ）テキスト
    score: float | None = None

class GraphIndex:
    def __init__(self, settings): ...
    async def start(self) -> None                    # 接続・インデックス構築。失敗は例外（呼び元が degraded 化）
    async def upsert_fact(self, post, old: FactIndexEntry | None) -> FactIndexEntry
    async def delete_fact(self, old: FactIndexEntry) -> None
    async def search(self, query: str, group_ids: list[str],
                     uuid_to_fact: dict[str, str], limit: int = 10) -> list[SearchHit]
    async def clear(self, group_ids: list[str]) -> None
    @property
    def ready(self) -> bool
```

**実装ガイド（検証済みファクトに基づく意図。signature は要確認）:**
- 構築: `Graphiti(graph_driver=FalkorDriver(host, port), llm_client=AnthropicClient(LLMConfig(model=settings.anthropic_model)), embedder=OpenAIEmbedder(OpenAIEmbedderConfig(api_key=settings.embedder_api_key, base_url=settings.embedder_base_url, embedding_model=settings.embedder_model, embedding_dim=settings.embedding_dim)))` — Ollama は OpenAI 互換エンドポイント。**cross_encoder のデフォルトは OpenAIRerankerClient なので必ず差し替えるか回避**（OPENAI_API_KEY は無い）。選択肢: ①reranker 不要の search 設定（RRF/MMR recipe を `search_()` で指定）②graphiti が None を許すなら None。実 API を確認して選び、決定を report へ
- `upsert_fact`: `old.episode_uuids` があれば先に削除（`remove_episode(uuid)` 相当）。`post["status"] == "invalidated"` なら削除のみで空 entry を返す（invalidated はグラフに置かない — 設計書 §4）。episode モード: `add_episode(name=episode_name(post), episode_body=render_episode(post), source_description=f"plk:{post['id']}", reference_time=<created_at を datetime に>, group_id=settings.group_for(post['namespace']))` の戻りから episode uuid を取得し entry に保存。**group 内逐次投入は呼び元（sync）が保証**
- triplet モード（`settings.ingest_mode == "triplet"`）: LLM 抽出なしの直挿入。`add_triplet(source_node, edge, target_node)` で `(fact ノード: name=statement)-[RELATES_TO]->(tag ノード)` を tags 分。tags が空なら namespace 名を疑似 topic に。embedding は graphiti が生成するか要確認 — しなければ embedder を直接呼んで node に設定。add_triplet が uuid を返さない場合は node uuid を entry に保存
- `search`: `await graphiti.search(query, group_ids=group_ids, num_results=limit * 3)`（または search_ + recipe）。結果エッジの `.episodes`（episode uuid 群）を `uuid_to_fact` で fact_id に解決、fact_id で dedupe して上位 limit 件。**エッジに episode 帰属が無い/空のケースは fact_id 解決不能としてスキップし、スキップ数を log に出す**（マッピング欠損の可視化）
- `clear`: `graphiti_core.utils.maintenance.graph_data_operations.clear_data(driver, group_ids=...)` → インデックス再構築

- [ ] **Step 1: mapping の純ロジックをテスト**（`_resolve_hits(edges, uuid_to_fact, limit)` を module 関数に切り出す）

`tests/test_graphindex_mapping.py`:

```python
from types import SimpleNamespace

from plk_memory.graphindex import _resolve_hits


def edge(fact, episodes, score=None):
    return SimpleNamespace(fact=fact, episodes=episodes, score=score)


def test_resolve_maps_dedupes_and_limits():
    u2f = {"u1": "F1", "u2": "F2", "u3": "F3"}
    edges = [
        edge("最初のfact", ["u1"]),
        edge("同じファクト由来の別エッジ", ["u1"]),   # dedupe される
        edge("別ファクト", ["u2"]),
        edge("帰属不明", []),                        # スキップ
        edge("未知uuid", ["zz"]),                    # スキップ
        edge("3件目", ["u3"]),
    ]
    hits = _resolve_hits(edges, u2f, limit=2)
    assert [h.fact_id for h in hits] == ["F1", "F2"]
    assert hits[0].fact_text == "最初のfact"
```

- [ ] **Step 2: RED → 実装 → GREEN**（`_resolve_hits` と `SearchHit` を先に実装し、クラス本体は上記ガイドに従って書く。graphiti の実 API 確認は `uv run python -c "import graphiti_core; ..."` とインストール済みソース `.venv/lib/**/graphiti_core/` の読解で行う）

- [ ] **Step 3: FakeGraphIndex を tests/fakes.py に実装**（Task 7/9 用の in-memory 実装 — upsert/delete/search/clear を dict で模倣。search は statement 部分一致）

```python
"""テスト用の in-memory GraphIndex（interface 互換）。"""

from plk_memory.graphindex import SearchHit
from plk_memory.rendering import content_hash, render_episode
from plk_memory.state import FactIndexEntry


class FakeGraphIndex:
    def __init__(self, fail_for: set[str] | None = None):
        self.docs: dict[str, dict] = {}   # fact_id -> {text, group_id}
        self.fail_for = fail_for or set()
        self.ready = True

    async def start(self):
        pass

    async def upsert_fact(self, post, old):
        fid = post["id"]
        if fid in self.fail_for:
            raise RuntimeError(f"fake ingest failure: {fid}")
        if old:
            self.docs.pop(next(iter(old.episode_uuids), None), None)
        if post["status"] == "invalidated":
            self.docs.pop(fid, None)
            return FactIndexEntry()
        self.docs[fid] = {"text": render_episode(post), "group_id": "plk.main"}
        return FactIndexEntry(episode_uuids=[fid], content_hash=content_hash(post), group_id="plk.main")

    async def delete_fact(self, old):
        for u in old.episode_uuids:
            self.docs.pop(u, None)

    async def search(self, query, group_ids, uuid_to_fact, limit=10):
        hits = [
            SearchHit(fact_id=fid, fact_text=d["text"][:80])
            for fid, d in self.docs.items()
            if any(tok in d["text"] for tok in query.split())
        ]
        return hits[:limit]

    async def clear(self, group_ids):
        self.docs.clear()
```

- [ ] **Step 4: live smoke テストを書く**（実行は Task 13。ここではコードのみ）

`tests_live/test_graph_smoke.py`:

```python
import pytest

import frontmatter

from plk_memory.graphindex import GraphIndex
from plk_memory.settings import Settings

pytestmark = pytest.mark.live


async def test_upsert_search_delete_roundtrip():
    s = Settings(tokens={"t": "c"}, admin_token="a", _env_file=None)
    g = GraphIndex(s)
    await g.start()
    meta = {
        "id": "01JZC2LIVE0000000000000000", "kind": "knowhow",
        "statement": "持続化補助金の経費は税込金額で積算する",
        "why": "免税事業者は税込経理のため補助対象経費も税込で扱う",
        "how_to_apply": "申請書の経費明細を税込で記載する",
        "source": "https://example.com", "source_type": "user",
        "namespace": "plk.domain.tax", "status": "active",
        "written_by": "test", "created_at": "2026-07-02T10:00:00+09:00", "tags": ["補助金"],
    }
    post = frontmatter.Post("", **meta)
    entry = await g.upsert_fact(post, None)
    assert entry.episode_uuids
    hits = await g.search("補助金の経費は税込か税抜か", ["plk.main"],
                          {u: meta["id"] for u in entry.episode_uuids}, limit=5)
    assert any(h.fact_id == meta["id"] for h in hits)
    await g.delete_fact(entry)
    await g.clear(["plk.main"])
```

- [ ] **Step 5: 単体テスト GREEN 確認** — `uv run pytest tests/ -v`（live は除外される）

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: GraphIndex（graphiti ラッパー・triplet モード・Fake・live smoke）"
```

---

### Task 7: sync（level-triggered 同期エンジン）

**Files:**
- Create: `src/plk_memory/sync.py`
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `GitStore`、`FactService`、`GraphIndex`（interface）、`StateStore`、`Settings`
- Produces: `SyncEngine(store, facts, graph, state_store, settings)`:
  - `async sync() -> dict`（fetch→ff → `last..HEAD` の diff を適用 → state 更新。返り値: `{"upserted": n, "deleted": n, "dead_letters": {...}, "head": sha, "degraded": str|None}`）
  - `async reindex() -> dict`（maintenance フラグ → 全 group clear → 全ファクト逐次 ingest → state リセット）
  - `maintenance: bool` 属性（True の間、FactService の書き込みを呼び元が 503 化）
  - `status() -> dict`（last_ingested_commit・HEAD との差分有無・dead_letters・索引済み件数）

**同期の規則（設計書 §6-3〜5）:**
- `last_ingested_commit is None` → 全ファイル ingest（clear はしない。reindex と区別）
- diff は `git diff --name-status --find-renames {last}..{head} -- knowledge/`
- A/M: HEAD の実ファイルから load して upsert（level-triggered: 内容は HEAD から読み直す）
- D: `git show {last}:{path}` で旧 frontmatter を読み id 解決 → state entry で delete
- R: 旧パスの entry を delete → 新パスを upsert（group またぎは delete+add で表現される）
- ファイル単位の失敗は dead_letters に記録して続行。成功したら該当 path の dead letter を消す
- 逐次処理（graphiti の公式推奨）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_sync.py`（`remote`/`make_store` fixture と FakeGraphIndex を使用。ヘルパー `write_valid_fact(repo_dir, rel, **over)` を定義して seed する — frontmatter は Task 5 の VALID 相当で plk_validator を通る内容にすること）:

```python
import pytest

from plk_memory.facts import FactService
from plk_memory.state import StateStore
from plk_memory.sync import SyncEngine
from tests.fakes import FakeGraphIndex


@pytest.fixture
def engine(remote, tmp_path):
    origin, seed = remote
    from tests.conftest import make_store
    store = make_store(tmp_path, origin)
    facts = FactService(store, store.settings)
    graph = FakeGraphIndex()
    state = StateStore(tmp_path / "state.json")
    return SyncEngine(store, facts, graph, state, store.settings), seed, graph


async def test_initial_sync_ingests_all(engine, write_valid_fact):
    eng, seed, graph = engine
    # seed 側で 2 ファクトを push（人間の編集を模倣）
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    write_valid_fact(seed, "knowledge/domains/dev/f2.md",
                     id="01JZC2V7E8B3F4G5H6J7K8M9N2", namespace="plk.domain.dev")
    push(seed)
    result = await eng.sync()
    assert result["upserted"] == 2
    assert len(graph.docs) == 2


async def test_incremental_add_modify_delete(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    # modify + add + delete を 1 push で
    modify_statement(seed, "knowledge/domains/tax/f1.md", "修正された知見の要旨で二十字以上ある")
    write_valid_fact(seed, "knowledge/domains/dev/f3.md",
                     id="01JZC2V7E8B3F4G5H6J7K8M9N3", namespace="plk.domain.dev")
    push(seed)
    r = await eng.sync()
    assert r["upserted"] == 2 and r["deleted"] == 0
    delete_file(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    r = await eng.sync()
    assert r["deleted"] == 1
    assert "01JZC2V7E8B3F4G5H6J7K8M9N0" not in graph.docs


async def test_rename_promotion_delete_and_readd(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    rename_with_namespace(seed, "knowledge/domains/tax/f1.md", "knowledge/shared/f1.md", "plk.shared")
    push(seed)
    r = await eng.sync()
    assert r["upserted"] == 1  # 新側
    assert len(graph.docs) == 1


async def test_dead_letter_recorded_and_recovered(engine, write_valid_fact):
    eng, seed, graph = engine
    graph.fail_for = {"01JZC2V7E8B3F4G5H6J7K8M9N0"}
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    r = await eng.sync()
    assert r["dead_letters"]
    graph.fail_for = set()
    r2 = await eng.sync()          # 再同期で回収（level-triggered）
    assert not r2["dead_letters"]
    assert len(graph.docs) == 1


async def test_invalidated_fact_removed_from_index(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    set_invalidated(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    assert len(graph.docs) == 0


async def test_reindex_clears_and_rebuilds(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    r = await eng.reindex()
    assert r["upserted"] == 1 and len(graph.docs) == 1
    assert eng.maintenance is False
```

（`push`/`modify_statement`/`delete_file`/`rename_with_namespace`/`set_invalidated`/`write_valid_fact` はテストヘルパー。conftest.py に実装: seed clone 上で frontmatter を書き換えて `git add/commit/push` する薄い関数群。`write_valid_fact` は pytest fixture として関数を返す形でよい）

- [ ] **Step 2: RED → 実装 → GREEN**

`sync.py` 実装（骨子 — dead letter 回収は「未処理 path を diff 由来の変更に加えて再適用」する。level-triggered なので HEAD の実ファイルを読み直すだけでよい）:

```python
"""level-triggered 同期エンジン（設計書 §6-3〜5）。"""

from __future__ import annotations

import frontmatter

from plk_memory.facts import FactService
from plk_memory.gitstore import GitStore, HistoryRewritten
from plk_memory.graphindex import GraphIndex
from plk_memory.settings import Settings
from plk_memory.state import FactIndexEntry, StateStore


def parse_name_status(text: str) -> list[list[str]]:
    return [line.split("\t") for line in text.splitlines() if line.strip()]


class SyncEngine:
    def __init__(self, store: GitStore, facts: FactService, graph, state_store: StateStore, settings: Settings):
        self.store = store
        self.facts = facts
        self.graph = graph
        self.state_store = state_store
        self.settings = settings
        self.maintenance = False
        self.degraded: str | None = None

    async def sync(self) -> dict:
        try:
            self.store.fetch_and_ff()
            self.degraded = None
        except HistoryRewritten as e:
            self.degraded = str(e)
            return {"upserted": 0, "deleted": 0, "dead_letters": {}, "head": self.store.head(), "degraded": self.degraded}

        state = self.state_store.load()
        head = self.store.head()
        upserted = deleted = 0

        # 対象 path 集合を決める（初回=全ファイル / 差分 + 既存 dead letters）
        targets: dict[str, str | None] = {}   # rel_path -> 旧 id（D/R の旧側のみ）
        if state.last_ingested_commit is None:
            for _, rel in self.facts.list_posts():
                targets[rel] = None
        elif state.last_ingested_commit != head:
            diff = self.store.git(
                "diff", "--name-status", "--find-renames",
                f"{state.last_ingested_commit}..{head}", "--",
                self.settings.knowledge_subdir + "/",
            )
            for entry in parse_name_status(diff):
                status, paths = entry[0], entry[1:]
                if status.startswith("R"):
                    old_id = self._id_at(state.last_ingested_commit, paths[0])
                    self._delete_by_id(state, old_id)
                    deleted += 0  # rename は delete+upsert で 1 ファクト扱い
                    targets[paths[1]] = None
                elif status == "D":
                    old_id = self._id_at(state.last_ingested_commit, paths[0])
                    if await self._delete_by_id_async(state, old_id):
                        deleted += 1
                else:  # A / M
                    targets[paths[0]] = None
        for p in list(state.dead_letters):
            targets.setdefault(p, None)

        for rel in sorted(targets):
            try:
                path = self.settings.data_repo_path / rel
                if not path.exists():
                    state.dead_letters.pop(rel, None)
                    continue
                post = frontmatter.load(path)
                fid = post["id"]
                old = state.facts.get(fid)
                entry = await self.graph.upsert_fact(post, old)
                if entry.episode_uuids:
                    state.facts[fid] = entry
                else:
                    state.facts.pop(fid, None)   # invalidated
                state.dead_letters.pop(rel, None)
                upserted += 1
            except Exception as e:
                state.dead_letters[rel] = str(e)

        state.last_ingested_commit = head
        self.state_store.save(state)
        return {"upserted": upserted, "deleted": deleted,
                "dead_letters": dict(state.dead_letters), "head": head, "degraded": None}

    def _id_at(self, ref: str, rel: str) -> str | None:
        try:
            return frontmatter.loads(self.store.git("show", f"{ref}:{rel}")).get("id")
        except Exception:
            return None

    async def _delete_by_id_async(self, state, fact_id: str | None) -> bool:
        if fact_id and fact_id in state.facts:
            await self.graph.delete_fact(state.facts.pop(fact_id))
            return True
        return False

    def _delete_by_id(self, state, fact_id):
        # rename 経路用の同期呼び出しラッパは実装時に async 化して統一してよい
        ...

    async def reindex(self) -> dict:
        self.maintenance = True
        try:
            await self.graph.clear(self.settings.all_groups())
            state = self.state_store.load()
            state.facts = {}
            state.dead_letters = {}
            state.last_ingested_commit = None
            self.state_store.save(state)
            return await self.sync()
        finally:
            self.maintenance = False

    def status(self) -> dict:
        state = self.state_store.load()
        head = self.store.head()
        unpushed = self.store.git("rev-list", "--count", "origin/main..HEAD").strip()
        return {
            "head": head,
            "last_ingested_commit": state.last_ingested_commit,
            "index_stale": state.last_ingested_commit != head,
            "indexed_facts": len(state.facts),
            "dead_letters": dict(state.dead_letters),
            "unpushed_commits": int(unpushed),
            "maintenance": self.maintenance,
            "degraded": self.degraded,
        }
```

（`_delete_by_id` の同期/非同期の整理・rename の deleted カウントの扱いは実装時に一貫させ、テストの期待値と一致させること。テストの期待が実装と食い違う場合はテストではなく実装ガイド側の解釈を直し、report に記録）

- [ ] **Step 3: GREEN 確認** — `uv run pytest tests/ -v`

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: level-triggered 同期エンジン（dead letter 回収・reindex・status）"
```

---

### Task 8: auth + usage_log

**Files:**
- Create: `src/plk_memory/auth.py`, `src/plk_memory/usage_log.py`
- Test: `tests/test_auth.py`, `tests/test_usage_log.py`

**Interfaces:**
- Produces:
  - `auth.current_client: ContextVar[str | None]`
  - `auth.BearerAuthMiddleware(app, settings)` — `/mcp` 配下: `settings.tokens` のトークン必須（一致で `current_client` 設定）。`/admin` 配下: `settings.admin_token` 必須。`/healthz` と `/` はスルー。失敗は 401 JSON（**HTML を返さない** — Hermes の content-type プリフライト対策）
  - `usage_log.UsageLog(path)` — `log(client, tool, query=None, hits=None, latency_ms=None, reason=None)` で JSONL 追記。**query の生値は 200 字で切り詰め、ヒット本文は記録しない**（設計書 §7: 消せない残存箇所を作らない）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_auth.py`:

```python
import httpx
import pytest
from fastapi import FastAPI

from plk_memory.auth import BearerAuthMiddleware, current_client
from plk_memory.settings import Settings


def make_app():
    s = Settings(tokens={"tok-cc": "claude-code"}, admin_token="tok-admin", _env_file=None)
    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, settings=s)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/mcp/echo")
    async def echo():
        return {"client": current_client.get()}

    @app.get("/admin/ping")
    async def admin_ping():
        return {"ok": True}

    return app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_healthz_open(client):
    r = await client.get("/healthz")
    assert r.status_code == 200


async def test_mcp_requires_token(client):
    r = await client.get("/mcp/echo")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")


async def test_mcp_valid_token_sets_client(client):
    r = await client.get("/mcp/echo", headers={"Authorization": "Bearer tok-cc"})
    assert r.status_code == 200 and r.json()["client"] == "claude-code"


async def test_admin_needs_admin_token(client):
    r = await client.get("/admin/ping", headers={"Authorization": "Bearer tok-cc"})
    assert r.status_code == 401
    r = await client.get("/admin/ping", headers={"Authorization": "Bearer tok-admin"})
    assert r.status_code == 200
```

`tests/test_usage_log.py`:

```python
import json

from plk_memory.usage_log import UsageLog


def test_appends_jsonl_and_truncates_query(tmp_path):
    log = UsageLog(tmp_path / "u.jsonl")
    log.log("claude-code", "plk_search", query="あ" * 500, hits=3, latency_ms=42, reason="auto-guideline")
    log.log("codex", "plk_add")
    lines = (tmp_path / "u.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["client"] == "claude-code" and len(rec["query"]) == 200
    assert rec["reason"] == "auto-guideline" and "ts" in rec
```

- [ ] **Step 2: RED → 実装 → GREEN**

`auth.py`:

```python
"""Bearer 認証（クライアント別トークン）と呼び出し元 contextvar（設計書 §7）。"""

from __future__ import annotations

from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from plk_memory.settings import Settings

current_client: ContextVar[str | None] = ContextVar("current_client", default=None)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        token = ""
        authz = request.headers.get("authorization", "")
        if authz.lower().startswith("bearer "):
            token = authz[7:].strip()

        if path.startswith("/admin"):
            if not self.settings.admin_token or token != self.settings.admin_token:
                return JSONResponse({"error": "admin token required"}, status_code=401)
        elif path.startswith("/mcp"):
            client = self.settings.tokens.get(token)
            if client is None:
                return JSONResponse({"error": "invalid or missing bearer token"}, status_code=401)
            current_client.set(client)
        return await call_next(request)
```

`usage_log.py`:

```python
"""利用ログ（JSONL。本文は記録しない — 設計書 §7/§9）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class UsageLog:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, client: str | None, tool: str, *, query: str | None = None,
            hits: int | None = None, latency_ms: int | None = None,
            reason: str | None = None) -> None:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "client": client, "tool": tool,
            "query": (query or "")[:200] or None,
            "hits": hits, "latency_ms": latency_ms, "reason": reason,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
```

- [ ] **Step 3: GREEN 確認** — `uv run pytest tests/ -v`

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: Bearer 認証ミドルウェアと利用ログ"
```

---

### Task 9: app + MCP ツール（統合）

**Files:**
- Create: `src/plk_memory/mcp_tools.py`, `src/plk_memory/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: 全モジュール
- Produces:
  - `app.create_app(settings=None, graph=None) -> FastAPI`（テストは FakeGraphIndex を注入。`--factory` で uvicorn 起動可能）
  - `app.AppServices`（store/facts/graph/sync/usage を束ねるコンテナ。`app.state.services` に格納）
  - MCP ツール（FastMCP、下記シグネチャ厳守 — 組織展開 互換サーフェス）:
    - `plk_search(query: str, namespaces: list[str] | None = None, kind: str | None = None, status: str = "active", limit: int = 10, reason: str | None = None) -> dict`
    - `plk_add(namespace: str, kind: str, statement: str, why: str, how_to_apply: str, source: str, tags: list[str] | None = None, body: str = "", slug: str | None = None, source_type: str = "agent", supersedes: list[str] | None = None) -> dict`
    - `plk_invalidate(fact_id: str, reason: str) -> dict`
    - `plk_history(fact_id: str) -> dict`
    - `plk_status() -> dict`
  - REST: `GET /healthz`（認証なし・即応）/ `POST /admin/sync` / `POST /admin/reindex`（バックグラウンドジョブ。実行中の書き込みは 503）

**動作規則:**
- `plk_search`: graph 未接続/degraded → `{"degraded": true, "message": "...", "hits": []}` を返す（エラーにしない — 設計書 §8）。通常時は group_ids（Byteflare モード: `[main_group]`。quarantine はデフォルト除外、`namespaces` に `plk.quarantine` を明示した時のみ含める）で検索 → hits の fact_id を frontmatter で解決 → `kind`/`status`/`namespaces` でフィルタ → `{"hits": [{fact_id, statement, namespace, kind, status, path, fact_text}], "degraded": false}`。UsageLog に記録
- `plk_add`/`plk_invalidate`: `sync.maintenance` 中は `{"error": "maintenance 中（reindex 実行中）", "retry": true}` を返す。成功時は commit 後に非同期で `sync()` を起動（`asyncio.create_task`）し、`{"fact_id": ..., "note": "索引は非同期で更新される"}` を即返す（60 秒制約）
- `written_by` は `auth.current_client.get()` から。None（認証レイヤ外での直接呼び出し）なら "unknown" ではなくエラー
- lifespan: `ensure_repo()` → `graph.start()`（失敗は degraded 記録して続行）→ 初回 `sync()` を task 起動 → `sync_interval_seconds` の周期 task。shutdown で task cancel
- ルート登録順: REST → `app.mount("/mcp", mcp_app)`（Mount が全パスを食う問題への対処）
- FastMCP 結線: `mcp_app = mcp.http_app(path="/")` + `fastmcp.utilities.lifespan.combine_lifespans`（検証済みパターン。実 API 名が違う場合は適応して report へ）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_app.py`（FakeGraphIndex 注入・httpx ASGITransport。**lifespan を実行するため `httpx.ASGITransport` ではなく `asgi_lifespan.LifespanManager` が必要になったら dev 依存に追加してよい**（report に記録）。シンプルに保つため、初回 sync の完了は `/admin/sync` を明示的に叩いて待つ形でテストする）:

```python
import httpx
import pytest

from plk_memory.app import create_app
from tests.fakes import FakeGraphIndex

AUTH_CC = {"Authorization": "Bearer tok-cc"}
AUTH_ADMIN = {"Authorization": "Bearer tok-admin"}

VALID_ARGS = dict(
    namespace="plk.domain.tax", kind="knowhow",
    statement="法人税の中間申告は前期税額20万円超で必要になる制度である",
    why="国税庁タックスアンサーの中間申告の要件に明記されているため",
    how_to_apply="設立2期目以降、前期法人税額を確認して要否を判定する",
    source="https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5000.htm",
)


@pytest.fixture
async def ctx(remote, tmp_path):
    origin, seed = remote
    from tests.conftest import make_settings
    settings = make_settings(tmp_path, origin,
                             tokens={"tok-cc": "claude-code"}, admin_token="tok-admin")
    graph = FakeGraphIndex()
    app = create_app(settings=settings, graph=graph)
    # lifespan 起動（asgi-lifespan or app.router.lifespan_context — 実装時に確定）
    async with lifespan_ctx(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c, app, graph


async def test_healthz_no_auth(ctx):
    c, *_ = ctx
    r = await c.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True


async def test_mcp_endpoint_requires_auth(ctx):
    c, *_ = ctx
    r = await c.post("/mcp/", json={})
    assert r.status_code == 401


async def test_add_then_sync_then_search_tools(ctx):
    c, app, graph = ctx
    svcs = app.state.services
    from plk_memory.auth import current_client
    current_client.set("claude-code")
    result = await svcs.tool_add(**VALID_ARGS)
    assert "fact_id" in result
    await svcs.sync.sync()
    hits = await svcs.tool_search(query="中間申告 前期税額", reason="test")
    assert hits["degraded"] is False
    assert any(h["fact_id"] == result["fact_id"] for h in hits["hits"])


async def test_search_degraded_when_graph_down(ctx):
    c, app, graph = ctx
    graph.ready = False
    svcs = app.state.services
    out = await svcs.tool_search(query="なんでも")
    assert out["degraded"] is True and out["hits"] == []


async def test_admin_reindex_blocks_writes(ctx):
    c, app, graph = ctx
    svcs = app.state.services
    svcs.sync.maintenance = True
    from plk_memory.auth import current_client
    current_client.set("claude-code")
    out = await svcs.tool_add(**VALID_ARGS)
    assert out.get("retry") is True and "error" in out
    svcs.sync.maintenance = False


async def test_admin_sync_endpoint(ctx):
    c, *_ = ctx
    r = await c.post("/admin/sync", headers=AUTH_ADMIN)
    assert r.status_code == 200 and "head" in r.json()


async def test_status_tool_reports_freshness(ctx):
    c, app, _ = ctx
    out = await app.state.services.tool_status()
    assert {"head", "last_ingested_commit", "indexed_facts", "dead_letters", "unpushed_commits"} <= out.keys()
```

（`tool_add`/`tool_search`/`tool_status` は MCP デコレータ適用前の実体関数を `AppServices` に持たせ、FastMCP ツールはそれを呼ぶ薄いラッパにする — テスト容易性と MCP 結線の分離。`make_settings` は conftest の `make_store` から Settings 構築部を切り出す）

- [ ] **Step 2: RED → 実装 → GREEN**（実装は上記動作規則に忠実に。FastMCP 結線は 1 本だけ実 HTTP で疎通確認するテストを追加できれば加点だが、MCP セッションハンドシェイクが複雑なら「/mcp が 401→認証付きで 406/400 系（MCP プロトコル応答）を返す」までの確認でよい — report に記録）

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: FastAPI+FastMCP 統合（plk_* ツール・admin・degraded 対応）"
```

---

### Task 10: docker-compose と README（起動手順）

**Files:**
- Create: `docker-compose.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 9 の `create_app`
- Produces: 開発起動一式。FalkorDB はコンテナ、api はホスト（uv run）が既定

- [ ] **Step 1: docker-compose.yml**

```yaml
services:
  falkordb:
    image: falkordb/falkordb:latest
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - falkordb-data:/var/lib/falkordb/data
    restart: unless-stopped

volumes:
  falkordb-data:
```

- [ ] **Step 2: README.md に起動手順を記載**

内容（この見出し構成で書く）: ①前提（uv / Docker / Ollama + `ollama pull bge-m3` / ANTHROPIC_API_KEY / agent-organization への ssh アクセス）②セットアップ（`cp .env.example .env` → トークン生成例 `openssl rand -hex 16` → `docker compose up -d falkordb` → `uv sync`）③起動（`uv run uvicorn plk_memory.app:create_app --factory --host 127.0.0.1 --port 8735`）④動作確認（`curl -s localhost:8735/healthz`、`curl -s -X POST localhost:8735/admin/sync -H "Authorization: Bearer $PLK_ADMIN_TOKEN"`）⑤単一レプリカ必須の注意（writer flock・多重起動は起動失敗する仕様）⑥MCP クライアント登録は `clients/` を参照 ⑦縮退動作（FalkorDB/Ollama 停止時は検索のみ縮退・書き込みと SoT は生きる）

- [ ] **Step 3: 実起動スモーク**

Run: `docker compose up -d falkordb && uv run uvicorn plk_memory.app:create_app --factory --port 8735 &` → `curl -s localhost:8735/healthz` → `{"ok":true}` を確認 → プロセス停止
（ANTHROPIC_API_KEY/Ollama 未起動でも healthz は生きる = degraded 起動の確認になる）

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: docker-compose（FalkorDB）と README 起動手順"
```

---

### Task 11: クライアント接続テンプレートと検索動線

**Files:**
- Create: `clients/README.md`, `clients/claude-code.md`, `clients/codex.md`, `clients/hermes.md`, `clients/agent-sdk.md`, `clients/guideline-line.md`

**Interfaces:**
- Consumes: なし（ドキュメントのみ。検証済みの各 CLI 現行仕様に基づく）
- Produces: Phase 1 完了条件④（検索動線の配布物）と Phase 3 逆輸入対象の接続テンプレート

- [ ] **Step 1: 各ファイルを作成**

`clients/guideline-line.md` — 全クライアント共通の動線 1 行（システムプロンプト/CLAUDE.md/AGENTS.md に貼る文言）:

```markdown
# 検索動線（1 行）

以下をエージェントの常駐指示（CLAUDE.md / AGENTS.md / システムプロンプト）に追加する:

> 税務・社会保険・法務・過去の意思決定・社内ノウハウに関わる判断の前に、必ず plk の `plk_search` を一度呼ぶこと（引数 `reason="auto-guideline"` を付ける。ヒットが無ければそのまま進めてよい）。

`reason` は利用ログで「自発（プロンプト誘導）か人間の明示指示か」を区別するための計測用（設計書 §9）。
```

`clients/claude-code.md`:

````markdown
# Claude Code 接続

```bash
export PLK_TOKEN=<発行されたトークン>
claude mcp add --transport http plk http://127.0.0.1:8735/mcp --header "Authorization: Bearer ${PLK_TOKEN}"
```

- `.mcp.json` をプロジェクト共有する場合は `${PLK_TOKEN:-}` とデフォルト付きで書く（未定義だと設定パース自体が失敗する）
- ツール名は `mcp__plk__plk_search` 形式
- サーバー停止時は非ブロッキング（セッション継続・自動再接続）
````

`clients/codex.md`:

````markdown
# Codex CLI 接続

```bash
codex mcp add plk --url http://127.0.0.1:8735/mcp --bearer-token-env-var PLK_TOKEN
```

- トークン直書きは Codex が拒否する仕様。必ず環境変数で
- **注意**: Codex はサーバー無応答時に初回ターンが startup_timeout（既定 10 秒）ブロックされる既知課題がある。plk-memory を停止する時は `[mcp_servers.plk] enabled = false` で一時無効化を推奨
````

`clients/hermes.md`:

````markdown
# Hermes Agent 接続

`~/.hermes/config.yaml`:

```yaml
mcp_servers:
  plk:
    url: http://127.0.0.1:8735/mcp
    headers:
      Authorization: "Bearer ${PLK_TOKEN}"
```

- ツール名は `mcp_plk_plk_search` 形式（アンダースコア 1 つ）
- Hermes は接続時に content-type を検査する。plk-memory はエラー時も JSON を返す設計なので相性問題なし
````

`clients/agent-sdk.md`:

````markdown
# Claude Agent SDK（自作エージェント）接続

```python
import os
from claude_agent_sdk import ClaudeAgentOptions

options = ClaudeAgentOptions(
    mcp_servers={
        "plk": {
            "type": "http",
            "url": "http://127.0.0.1:8735/mcp",
            "headers": {"Authorization": f"Bearer {os.environ['PLK_TOKEN']}"},
        }
    },
    allowed_tools=["mcp__plk__*"],
)
```

- `allowed_tools` の明示が必須（無いとツールが見えても呼べない）
````

`clients/README.md` — 一覧と共通事項（タイムアウト → メモリなしで続行の契約、トークンは環境変数のみ、トークン発行 = サーバー側 `.env` の `PLK_TOKENS` に追記して再起動）。

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "docs: クライアント接続テンプレートと検索動線"
```

---

### Task 12: Phase 0 繰延修正（agent-organization 側）

**Files:**（リポジトリは `/Users/masahiro/dev/byteflare-co/agent-organization`）
- Modify: `tools/validator/src/plk_validator/repo_checks.py`
- Modify: `tools/validator/scripts/new_fact.py`
- Modify: `knowledge/CONVENTIONS.md`
- Test: `tools/validator/tests/test_repo_checks.py`（追記）

**Interfaces:**
- Consumes: Phase 0 の validate_repo
- Produces: superseded_by 参照整合チェック／new_fact.py のドメイン検証／CONVENTIONS.md の実装ルール文書化

- [ ] **Step 1: 失敗するテストを追記**（test_repo_checks.py）

```python
def test_dangling_superseded_by_fails(tmp_path):
    write_fact(tmp_path / "domains/tax/fact1.md",
               status="invalidated",
               invalidation_reason="後継に置換",
               invalidated_at="2026-07-02T10:00:00+09:00",
               superseded_by="01JZC2V7E8B3F4G5H6J7K8M9N9")  # 存在しない id
    errors = validate_repo(tmp_path)
    assert any("superseded_by" in e for e in errors)


def test_valid_superseded_by_passes(tmp_path):
    write_fact(tmp_path / "domains/tax/old.md",
               status="invalidated", invalidation_reason="後継に置換",
               invalidated_at="2026-07-02T10:00:00+09:00",
               superseded_by="01JZC2V7E8B3F4G5H6J7K8M9N1")
    write_fact(tmp_path / "domains/tax/new.md", id="01JZC2V7E8B3F4G5H6J7K8M9N1")
    assert validate_repo(tmp_path) == []
```

- [ ] **Step 2: RED → 実装 → GREEN**（validate_repo の走査後に「全 superseded_by 値が seen_ids に存在する」チェックを追加。40 passed 前後になる）

- [ ] **Step 3: new_fact.py のドメイン検証**（`domains/<d>` の `<d>` が `plk_validator.schema.DOMAINS` に無ければエラー終了。動作確認は `uv run python scripts/new_fact.py domains/foo x` → 非ゼロ exit）

- [ ] **Step 4: CONVENTIONS.md に実装ルールを文書化**（追記セクション「バリデータが強制する詳細ルール」: CONVENTIONS.md/README.md は検証対象外／定型文ブラックリストの列挙／本文上限は markdown 記法込みの文字数／source の参照形式 = https URL・32 桁 hex の Notion ID・UUID）

- [ ] **Step 5: 全テスト・CI 確認と Commit**

```bash
cd tools/validator && uv run pytest tests/ -q && uv run plk-validate ../../knowledge
cd ../.. && git add -A && git commit -m "feat: superseded_by 参照整合・new_fact ドメイン検証・規約詳細の文書化" && git push
gh run watch --exit-status
```

---

### Task 13: live E2E と ingest 実測（episode / triplet）⚠️ 実 API 消費

**Files:**
- Create: `scripts/eval/measure_ingest.py`
- Create: `tests_live/conftest.py`（live 前提チェック: FalkorDB 到達・Ollama 到達・ANTHROPIC_API_KEY。無ければ skip でなく明示 fail）

**Interfaces:**
- Consumes: 全モジュール、実サービス（FalkorDB・Ollama・Anthropic API）、実データ（agent-organization の 23 ファクト）
- Produces: `measure_ingest.py`（reindex を実行し、モード別に件数・総時間・件あたり時間・dead letters を計測して JSON を出力）と実測値

**前提セットアップ（実施して report に記録）:**

```bash
ollama pull bge-m3
docker compose up -d falkordb
# .env: PLK_DATA_REPO_URL=git@github.com:cutsome/agent-organization.git ほか
```

- [ ] **Step 1: measure_ingest.py を実装**

```python
"""ingest 実測: reindex を実行してモード別の所要時間・成功率を計測する。

usage: uv run python scripts/eval/measure_ingest.py --mode episode --out /tmp/ingest-episode.json
"""
```

処理: settings をロード（`--mode` で ingest_mode 上書き）→ GitStore/FactService/GraphIndex/SyncEngine を組み立て → `graph.start()` → `reindex()` を実行 → 各ファクトの所要時間（sync 内で計測できるようフックを足すか、ファクト数と総時間から平均を出す）→ JSON 出力 `{mode, total_facts, upserted, dead_letters, total_seconds, seconds_per_fact}`。

- [ ] **Step 2: live smoke を実行**

Run: `uv run pytest tests_live/ -m live -v`
Expected: `test_upsert_search_delete_roundtrip` が PASS（初の実 graphiti 経路。失敗したら GraphIndex の適応箇所を修正 — ここが Task 6 の verify-and-adapt の答え合わせ）

- [ ] **Step 3: episode モード実測**

Run: `uv run python scripts/eval/measure_ingest.py --mode episode --out /tmp/ingest-episode.json && cat /tmp/ingest-episode.json`
Expected: 23 ファクトが dead letter なしで ingest され、所要時間が記録される

- [ ] **Step 4: triplet モード実測**

Run: `uv run python scripts/eval/measure_ingest.py --mode triplet --out /tmp/ingest-triplet.json`
Expected: LLM 呼び出しなし（またはごく少数）で高速に完了

- [ ] **Step 5: plk_search の手動スモーク**（サーバー起動して実クエリ 3 本 — 「厚生年金の口座振替はどうする」「持続化補助金の経費は税込か」「freee の事業所はどっち」— がヒットするか確認し結果を控える）

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: ingest 実測スクリプトと live E2E（実測値は report に記録）"
```

---

### Task 14: 評価ハーネス（20 クエリ・ベースライン対照）と Phase 1 レポート

**Files:**
- Create: `scripts/eval/queries.yaml`, `scripts/eval/run_eval.py`
- Create（agent-organization 側）: `reports/phase1-eval-report.md`

**Interfaces:**
- Consumes: GraphIndex（実）、Ollama embeddings API、agent-organization コーパス、Task 13 の実測値
- Produces: 評価レポート（チェックポイント判断の材料）。**日本語評価セットは 組織展開 への引き継ぎ資産**（設計書 §14）

- [ ] **Step 1: queries.yaml を作成（20 本）**

agent-organization の knowledge/ 全 23 ファクトを読み、実利用を模した日本語クエリ 20 本と期待ヒット（fact id）を作る。作為的にファイル名や statement の言い回しをそのまま使わず、**言い換え・口語**で書くこと（例: statement が「社会保険の被扶養者資格の遡及訂正は～」なら query は「扶養の手続きを遡ってやり直せるか」）。形式:

```yaml
- query: "扶養の手続きを遡ってやり直せる？"
  expected: ["01KW..."]
  note: "言い換え検索"
```

うち 2 本は矛盾系列トピック（freee 事業所）で、**invalidated 側でなく active 側が返ること**を期待に含める。

- [ ] **Step 2: run_eval.py を実装**

ランナー 3 種を同一クエリセットで実行:
1. `graph` — GraphIndex.search（top5）
2. `rg` — `rg -l -i <クエリの空白区切りトークン>` を knowledge/ に対して実行しマッチ行数でランキング（rg が無ければ Python の単純一致で代替）
3. `embed` — 全ファクトの `render_episode` テキストと query を Ollama `/v1/embeddings`（bge-m3）で埋め込み、cosine 類似 top5（**graphiti を介さない素の埋め込み検索** = ベースライン対照の本命）

指標: hit@5（expected のいずれかが top5 に入るか）と MRR。モード別（episode / triplet）の graph も比較。出力は per-query 表と集計の markdown。

- [ ] **Step 3: 実行してレポート生成**

Run: `uv run python scripts/eval/run_eval.py --queries scripts/eval/queries.yaml --out /tmp/phase1-eval.md`

- [ ] **Step 4: レポートを agent-organization/reports/ に整形コミット**

`reports/phase1-eval-report.md` の構成（この順で）:
1. 実行条件（日付・コーパス 23 件・embedder=bge-m3(ローカル)・LLM=Haiku・graphiti バージョン）
2. **検索精度**: graph(episode) vs graph(triplet) vs embed-baseline vs rg の hit@5 / MRR 表 + per-query 表
3. **ingest コスト**: Task 13 の実測（モード別 件/秒・総時間。API 費用は Anthropic コンソールの実額を手動転記する欄を設ける）
4. **制約の明記**: クラウド embedder（Voyage/Gemini/OpenAI）はキー未所持のため未比較／コーパス 23 件は撤退ライン判定（50 件以上で実施）にはまだ使わない参考値／利用ログ計測はこのレポート日から開始
5. **チェックポイント所見**: ベースラインと比べた graph の優位/劣位の一次所見（判断は人間）

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
git add reports/ && git commit -m "docs: Phase 1 評価レポート（検索精度・ingest 実測・ベースライン対照）" && git push
```

- [ ] **Step 5: plk-memory 側も Commit**

```bash
cd /Users/masahiro/dev/byteflare-co/plk-memory
git add -A && git commit -m "feat: 評価ハーネス（20クエリ・3ランナー・レポート生成）"
```

---

## Phase 1 完了条件（設計書 §11）

- [ ] plk_add/search/invalidate/history/status が動作し、単体テスト全 green
- [ ] level-triggered 同期・reindex・dead letter が動作
- [ ] クライアント別トークン認証・graceful degradation（graph 停止時に search が縮退応答）
- [ ] **ベースライン対照**: 同一 20 クエリで graph vs 素の埋め込み検索 vs rg の比較値がレポートに存在
- [ ] **episode vs triplet** の精度・コスト比較値がレポートに存在
- [ ] ingest 実測（件/秒・所要時間、費用転記欄）がレポートに存在
- [ ] 検索動線（clients/guideline-line.md）が配布物として存在し、利用ログが reason を記録できる
- [ ] Phase 0 繰延修正（superseded_by 整合・new_fact ドメイン検証・CONVENTIONS 文書化）が agent-organization で CI green
