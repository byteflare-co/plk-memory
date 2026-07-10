# plk-memory Phase 2（Mac 常駐＋運用）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1 でローカル動作した `plk-memory` を **Mac 常駐（launchd）** に昇格させ、昇格フロー（PromotionRequest 状態機械＋`plk_propose_promotion`＋PR 自動作成＋merge ポーリング→applied→ingest）・月次キュレーションレポート・read 専用 Web UI を実装し、全クライアント（CC/Codex/Hermes/自作1体）を実接続する。完了条件＝昇格パイプが 1 往復し、全クライアントが接続済み。

> **改訂（2026-07-03 ユーザー決定）:** EC2 昇格は延期。根拠: t4g.small（2 GiB）に LLM/embedder が載らない・全クライアントが Mac 上で動く・昇格フロー/UI/キュレーションは場所非依存（設計書 §2/§11 改訂済み）。Phase 2 は Mac 常駐のまま機能実装する。EC2/組織展開 期に持ち越す項目は各所に注記。

**Architecture:** Git=SoT・Graphiti=再構築可能な派生索引（設計書 v1.0 §3〜§9・§11 Phase 2）は Phase 1 のまま。Phase 2 は (a) PromotionRequest を API 内第一級リソースとして永続化（proposed/approved/rejected/applied）、GitHub PR をそのバックエンド実装として分離、(b) merge 検知は webhook でなく定期ポーリング、(c) read 専用 Web UI は REST のみに接続（Bearer をブラウザに持ち込まない・sanitize＋CSP・HttpOnly cookie）、(d) 常駐化は launchd（KeepAlive）＋ FalkorDB compose の `restart: unless-stopped`。**LLM/embedder は Phase 1 の完全ローカル構成（Ollama: gpt-oss:20b ＋ bge-m3）のまま変更なし＝追加費用ゼロ。**

**Tech Stack:** Phase 1 と同一（Python 3.12 / uv / FastAPI / FastMCP `mcp>=1.27,<2` / graphiti-core 0.29.x / FalkorDB / Ollama / python-frontmatter / pydantic-settings / pytest）＋ 追加: `nh3`（本文 sanitize）・`markdown`（本文レンダリング）・GitHub CLI `gh`（PR 作成。Mac の既存 `gh auth` を利用）・launchd（常駐）。

**設計書（SoT）:** `agent-memory/specs/2026-07-02-plk-memory-design.md` §5・§7（Phase 2 行）・§9（運用設計）・§11 Phase 2
**コードリポジトリ:** `/Users/masahiro/dev/byteflare-co/plk-memory`（HEAD=79506c9・54+3 tests・Phase 1 FULLY COMPLETE）
**データリポジトリ:** `/Users/masahiro/dev/byteflare-co/agent-organization`（GitHub: cutsome/agent-organization）

## Global Constraints

- **LLM/embedder は Phase 1 の完全ローカル構成のまま変更なし**（Ollama `gpt-oss:20b` ＋ `bge-m3`、`llm_provider="openai-compatible"`）。ユーザー費用が発生する変更は本 Phase に存在しない。
- **常駐サーバーの既定 `ingest_mode=triplet`**（チェックポイント拘束: グラフ層はコーパス 50 件到達まで凍結気味。episode reindex は行わない）。Phase 1 実測で triplet の MRR は素の埋め込み検索と同等（グラフ構造の付加価値は 23 件時点で未確認）。
- **公開面ゼロ = `127.0.0.1` bind のまま**（設計書 §7）。常駐化しても bind は変えない。Tailscale 内限定公開は EC2 昇格時（延期）の課題。
- **単一 writer・単一レプリカ必須**（設計書 §6 の不変条件）。launchd 常駐でも uvicorn `workers=1`。gitstore の flock 単一インスタンスガードを維持し、二重起動が fail-fast することを Task 9 で実機確認する。
- 依存ピンは Phase 1 のまま変更しない（`mcp>=1.27,<2` / `fastmcp>=3,<4` / `graphiti-core[anthropic,falkordb]>=0.29.2,<0.30`）。追加依存 `nh3`・`markdown` のみ増やす。
- **昇格の不変条件**（設計書 §7）: shared への直接書き込み禁止（昇格経由のみ・Phase 1 で FactService が強制済み）。昇格 PR は `domains/*→shared/*` の rename・1 ファイルのみ・内容差分は frontmatter `namespace:` 行 1 行のみ（`plk.domain.<d>`→`plk.shared`）。この CI チェックは Phase 0 実装済み（`plk_validator.gitchecks.check_promotion`）。Task 5 が作成する PR は **必ずこの形に一致させる**。
- **GitHub 資格情報**: Mac 常駐期は push＝既存の ssh remote、PR 作成・merge 照会＝Mac の既存 `gh auth` 認証をそのまま使う（新規 PAT 発行なし）。設計書 §7 の「push 用 fine-grained PAT（contents:write）と PR 用の 2 分離」は **EC2/組織展開 期の課題**として README に注記のみ残す。
- **外部書き込みの承認**（CLAUDE.md 動作原則）: 実 GitHub への昇格 PR 作成（Task 10 の実証）は、PR 内容の全文プレビューを提示しユーザーの明示承認を得てからのみ実行する。
- **written_by はサーバーがトークン identity から導出**（Phase 1 済み）。API 経由の `source_type` 上限は `agent`。これらは Phase 2 で緩めない。
- **Web UI（Task 8）は read 専用 REST のみに接続**。ブラウザから MCP・Bearer を使わない。閲覧認証は HttpOnly cookie。本文は非信頼入力として markdown を sanitize（nh3）＋ CSP 必須。
- **矛盾・重複検出はコーパス 100 件到達まで無効**（設計書 §9）。月次キュレーションレポート（Task 7）は未参照ファクト集計・利用ログ集計のみ。矛盾検出コードは 100 件ガードの後ろに置く。
- **キュレーションレポートには運用期キル基準の数値を毎回印字**（設計書 §11: 4 週連続で動線経由 plk_search の引用が週 3 回未満、または保守が週 30 分超過 → グラフ層凍結・常駐解除）。
- **全 MCP ツールは 60 秒以内に応答**。書き込み系は commit 後に非同期 sync を起動して即返す（Phase 1 済み）。
- graceful degradation は Phase 1 の契約を維持（graph/embedder 停止時 `plk_search` は degraded 応答、`/healthz` は認証なし即応）。
- テスト規律は Phase 1 と同一: 単体（`tests/`）は外部 API・Docker 不要で完結、live（`tests_live/`）は `-m live`。各タスク末尾で必ず commit。
- **verify-and-adapt ライセンス（不確実な外部依存のみ）**: 以下は「インストール版の実 API / 実コマンド出力を確認して適応し、逸脱を report に記録する」ことを許可する。それ以外のモジュールは計画どおり実装する。
  - `gh` CLI の PR 作成・照会サブコマンドの正確なフラグと JSON 出力形（Task 5・Task 10）。
  - launchd の `launchctl` サブコマンド差（`bootstrap`/`bootout`/`kickstart` の実挙動）と、launchd 環境での `uv`・`gh` の絶対パス／PATH 解決（Task 9）。

## 常駐方針（Mac）

- API は launchd LaunchAgent（`KeepAlive`）で常駐。クラッシュ・ログイン時に自動再起動。flock 単一インスタンスガードは launchd の再起動と整合（プロセス終了で flock は自動解放される）。
- FalkorDB は Phase 1 の docker-compose（`restart: unless-stopped`）のまま。Docker Desktop のログイン時自動起動を前提に README で明記。
- ingest LLM・embedder は Phase 1 のローカル Ollama（gpt-oss:20b / bge-m3）のまま。triplet 既定でも `add_triplet` の dedupe が LLM を呼ぶが、ローカルモデルなので費用ゼロ。
- EC2 昇格（Tailscale 内限定公開・PAT 2 分離・実ホスト名の DNS リバインディング保護）は延期し、設計書 §7 準拠の注記として README に残す。

## File Structure

```
plk-memory/
  src/plk_memory/
    settings.py       # 【変更】git identity・domains・bind/allowed_hosts・promotion/UI 設定を追加
    gitstore.py       # 【変更】identity を settings 化・promote 用 worktree メソッド追加
    app.py            # 【変更】promotion 配線・poller・UI ルート・TrustedHost・reindex ガード
    mcp_tools.py      # 【変更】plk_propose_promotion を追加
    sync.py           # 【変更】status() に pending promotions を足さず、app 側で合成（sync は不変）
    promotions.py     # 【新規】PromotionRequest 状態機械 + PromotionStore（永続化）
    github_promotion.py # 【新規】GitHubPromotionBackend（gh で PR 作成・merge 照会）⚠️ verify-and-adapt
    curation.py       # 【新規】月次キュレーションレポート生成（未参照・利用ログ集計）
    webui.py          # 【新規】read 専用 REST ルーター・cookie 認証・CSP・本文 sanitize
    static/index.html # 【新規】自己完結 SPA（一覧・フィルタ・検索・変遷表示）
  tests/              # 【追加】test_promotions/test_github_promotion/test_curation/test_webui/
                      #         test_app_promotion・既存テスト更新
  deploy/             # 【新規】com.byteflare.plk-memory.plist（launchd）・README は運用 runbook を追記
  scripts/curation/run_report.py  # 【新規】レポート生成→agent-organization へ commit
agent-organization/
  tools/validator/src/plk_validator/repo_checks.py  # 【変更】superseded_by 自己参照検出
```

---

### Task 1: 設定の外部化とアプリのプロダクション化（cheap fixes: git identity・DOMAINS・bind/allowed_hosts）

**Files:**
- Modify: `src/plk_memory/settings.py`
- Modify: `src/plk_memory/gitstore.py:52-55`（`ensure_repo` の identity 設定）
- Modify: `src/plk_memory/app.py`（`create_app` に TrustedHostMiddleware を追加）
- Test: `tests/test_settings.py`（追記）、`tests/test_gitstore.py`（追記）、`tests/test_app.py`（追記）

**Interfaces:**
- Consumes: 既存 `Settings`
- Produces（後続タスクが依存）:
  - `Settings.git_author_name: str`（既定 `"plk-memory"`）、`Settings.git_author_email: str`（既定 `"plk-memory@byteflare.co"`）
  - `Settings.domains: list[str]`（既定 `["tax","legal","shaho","dev","backoffice","biz"]`）。`all_groups()`・`path_for_namespace()` はこの値を使う
  - `Settings.allowed_hosts: list[str]`（既定 `["*"]`。将来の実ホスト名 bind（EC2/組織展開 期）用。ローカル常駐では既定のまま）
  - `Settings.repo_slug -> str`（`data_repo_url` から `owner/repo` を導出。Task 5 が使用）
  - `GitStore.ensure_repo()` は `settings.git_author_name/email` で identity を設定

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_settings.py` に追記:

```python
def test_domains_are_configurable_and_drive_groups():
    s = make(group_mode="per-namespace", domains=["tax", "dev"])
    groups = s.all_groups()
    assert "plk-domain-tax" in groups and "plk-domain-dev" in groups
    assert "plk-domain-legal" not in groups


def test_git_identity_defaults_and_override():
    assert make().git_author_name == "plk-memory"
    s = make(git_author_email="x@y.co")
    assert s.git_author_email == "x@y.co"


def test_repo_slug_from_ssh_and_https_urls():
    assert make(data_repo_url="git@github.com:cutsome/agent-organization.git").repo_slug == "cutsome/agent-organization"
    assert make(data_repo_url="https://github.com/cutsome/agent-organization.git").repo_slug == "cutsome/agent-organization"
```

（`make(...)` は `tests/test_settings.py` 既存ヘルパー。`domains` を渡せるよう `Settings` に list フィールドを足す）

`tests/test_gitstore.py` に追記:

```python
def test_ensure_repo_uses_configured_identity(remote, tmp_path):
    origin, _ = remote
    from tests.conftest import make_settings
    s = make_settings(tmp_path, origin, git_author_name="alice", git_author_email="alice@example.com")
    store = GitStore(s)
    store.ensure_repo()
    assert store.git("config", "user.name").strip() == "alice"
    assert store.git("config", "user.email").strip() == "alice@example.com"
```

`tests/test_app.py` に追記（Host ヘッダ拒否 — DNS リバインディング保護代替）:

```python
async def test_disallowed_host_rejected_when_allowlist_set(remote, tmp_path):
    origin, seed = remote
    from tests.conftest import make_settings
    settings = make_settings(tmp_path, origin, tokens={"tok-cc": "claude-code"},
                             admin_token="tok-admin", allowed_hosts=["plk.example.com"])
    from plk_memory.app import create_app
    from tests.fakes import FakeGraphIndex
    app = create_app(settings=settings, graph=FakeGraphIndex())
    import httpx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://evil.example") as c:
        r = await c.get("/healthz", headers={"host": "evil.example"})
        assert r.status_code == 400  # TrustedHostMiddleware
        r2 = await c.get("/healthz", headers={"host": "plk.example.com"})
        assert r2.status_code == 200
```

- [ ] **Step 2: RED 確認**

Run: `cd /Users/masahiro/dev/byteflare-co/plk-memory && uv run pytest tests/test_settings.py tests/test_gitstore.py -v -k "domains or identity or slug or configured_identity"`
Expected: FAIL（`domains` 属性なし / identity ハードコード / `repo_slug` なし）

- [ ] **Step 3: settings.py を実装**

`DOMAINS` モジュール定数は残しつつ、`Settings` にフィールドを追加。`all_groups()` / `path_for_namespace()` は `self.domains` を使う:

```python
# import 追加
from urllib.parse import urlparse

# Settings 内に追加（既存フィールド群の末尾など）
    # git identity（deferred fix: ハードコードを設定化）
    git_author_name: str = "plk-memory"
    git_author_email: str = "plk-memory@byteflare.co"

    # ドメイン（deferred fix: モジュール定数を設定化）
    domains: list[str] = list(DOMAINS)

    # 将来の実ホスト名 bind 時の DNS リバインディング保護（EC2/組織展開 期。ローカルは既定のまま）
    allowed_hosts: list[str] = ["*"]

    @property
    def repo_slug(self) -> str:
        url = self.data_repo_url
        if url.startswith("git@"):
            # git@github.com:owner/repo.git
            path = url.split(":", 1)[1]
        else:
            path = urlparse(url).path.lstrip("/")
        return path.removesuffix(".git")
```

既存 `all_groups()` の `for d in DOMAINS` を `for d in self.domains` に変更:

```python
    def all_groups(self) -> list[str]:
        if self.group_mode == "per-namespace":
            return [f"plk-domain-{d}" for d in self.domains] + ["plk-shared", self.quarantine_group]
        return [self.main_group, self.quarantine_group]
```

- [ ] **Step 4: gitstore.py の identity を設定化**

`src/plk_memory/gitstore.py` の `ensure_repo` 内 clone 直後:

```python
            self.git("config", "user.email", self.settings.git_author_email)
            self.git("config", "user.name", self.settings.git_author_name)
```

- [ ] **Step 5: app.py に TrustedHostMiddleware を追加**

`create_app` 内、`BearerAuthMiddleware` 追加の直前に（allowlist が `["*"]` 以外のときのみ有効化）:

```python
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    if settings.allowed_hosts and settings.allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
```

（FastMCP 側の transport_security allowlist は実ホスト名 bind に移る EC2/組織展開 期の課題。ローカル 127.0.0.1 bind の本 Phase では既定 `["*"]` のまま動作に影響しない。Starlette 層の Host 検証は将来に備えた一次防御として先に設定化しておく）

- [ ] **Step 6: GREEN 確認**

Run: `uv run pytest tests/ -v`
Expected: 追記分含め全 pass（既存 54 も維持）

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: 設定外部化（git identity・domains・allowed_hosts）と Host 検証ミドルウェア"
```

---

### Task 2: plk_search の recall 改善と /admin/reindex 二重起動ガード（cheap fixes）

**Files:**
- Modify: `src/plk_memory/app.py`（`AppServices.tool_search` の候補プール・`admin_reindex` のガード・`SyncEngine` 開始の原子化）
- Modify: `src/plk_memory/sync.py`（`reindex` に「既に maintenance 中なら例外」ガード）
- Test: `tests/test_app.py`（追記）、`tests/test_sync.py`（追記）

**Interfaces:**
- Consumes: Phase 1 の `tool_search` / `SyncEngine.reindex`
- Produces:
  - `tool_search` は post-filter（kind/status/namespace/quarantine 除外）で候補が枯渇しないよう、graph から **`max(limit*5, 50)` 件**の候補を取得してから post-filter して `limit` 件に詰める
  - `SyncEngine.reindex()` は `maintenance` が既に True の場合 `ReindexInProgress` を送出（二重起動防止）。`SyncEngine.ReindexInProgress` 例外を新設
  - `/admin/reindex` は `ReindexInProgress` を 409 に変換

**背景（Phase 1 の残課題）:** 現行 `tool_search` は `graph.search(..., limit=limit)` の後に kind/status/namespace/quarantine を post-filter するため、フィルタで落ちると `limit` 未満になる（recall 劣化）。graph 内部でも `num_results=limit*3` を取るが、外側の取得件数が `limit` なので候補が細い。取得件数を増やして post-filter 後に `limit` を満たすようにする。`/admin/reindex` は `maintenance` フラグ確認と set の間にレースがある。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_sync.py` に追記:

```python
async def test_reindex_rejects_double_start(engine, write_valid_fact):
    eng, seed, graph = engine
    write_valid_fact(seed, "knowledge/domains/tax/f1.md")
    push(seed)
    await eng.sync()
    eng.maintenance = True  # 別 reindex 実行中を模す
    from plk_memory.sync import ReindexInProgress
    with pytest.raises(ReindexInProgress):
        await eng.reindex()
    eng.maintenance = False
```

`tests/test_app.py` に追記（recall: 大量の非該当 kind に埋もれても該当 status/kind が limit 件返る）:

```python
async def test_search_recall_survives_post_filter(ctx):
    c, app, graph = ctx
    # graph に kind 違いのダミーを多数 + 目的の 1 件を最後に積む
    from plk_memory.state import FactIndexEntry
    svcs = app.state.services
    # FakeGraphIndex は docs[fact_id] に text/group_id を持つ。search は query トークン一致で返す。
    for i in range(30):
        graph.docs[f"noise{i}"] = {"text": "中間申告 ノイズ", "group_id": "plk-main"}
    # 目的ファクトを実 add
    from plk_memory.auth import current_client
    current_client.set("claude-code")
    r = await svcs.tool_add(**VALID_ARGS)
    await svcs.sync.sync()
    # ノイズは facts.get で FactNotFound になり弾かれるが、候補プールが広いので目的が残る
    hits = await svcs.tool_search(query="中間申告", limit=5)
    assert any(h["fact_id"] == r["fact_id"] for h in hits["hits"])
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/test_sync.py -k double_start tests/test_app.py -k recall -v`
Expected: FAIL（`ReindexInProgress` 未定義 / recall はノイズで枯渇し得る）

- [ ] **Step 3: sync.py に ReindexInProgress を実装**

`sync.py` の先頭に例外を追加し、`reindex` にガードを入れる:

```python
class ReindexInProgress(RuntimeError):
    pass
```

`reindex` メソッド冒頭にガードの 2 行を足す（本体は Phase 1 のまま）:

```python
    async def reindex(self) -> dict:
        if self.maintenance:
            raise ReindexInProgress("reindex は既に実行中")
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
```

- [ ] **Step 4: app.py の tool_search 候補プールと reindex ガードを実装**

`tool_search` の graph 検索呼び出しを候補プール拡大に変更:

```python
        pool = max(limit * 5, 50)
        try:
            raw_hits = await self.graph.search(query, group_ids, uuid_to_fact, limit=pool)
        except Exception as e:  # noqa: BLE001
            self.usage.log(client, "plk_search", query=query, hits=0, reason=reason)
            return {"degraded": True, "message": f"search 失敗: {e}", "hits": []}
```

（後続の post-filter ループと `if len(results) >= limit: break` は既存のまま。候補が広がるだけ）

`admin_reindex` ルートを `ReindexInProgress` 対応に:

```python
    @app.post("/admin/reindex")
    async def admin_reindex(background_tasks: BackgroundTasks) -> dict:
        if services.sync.maintenance:
            raise HTTPException(status_code=409, detail="reindex は既に実行中")

        async def _guarded_reindex() -> None:
            try:
                await services.sync.reindex()
            except Exception:  # noqa: BLE001 - 背景ジョブの失敗でサーバーを落とさない
                pass

        background_tasks.add_task(_guarded_reindex)
        return {"status": "started"}
```

- [ ] **Step 5: GREEN 確認**

Run: `uv run pytest tests/ -v`
Expected: 全 pass

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "fix: plk_search の候補プール拡大（recall 改善）と reindex 二重起動ガード（409）"
```

---

### Task 3: superseded_by 自己参照検出（agent-organization バリデータ）

**Files:**（リポジトリは `/Users/masahiro/dev/byteflare-co/agent-organization`）
- Modify: `tools/validator/src/plk_validator/repo_checks.py`（`validate_repo` の superseded_by チェック）
- Test: `tools/validator/tests/test_repo_checks.py`（追記）

**Interfaces:**
- Consumes: Phase 1 で追加済みの dangling superseded_by チェック（`pending_superseded_by` ループ）
- Produces: `superseded_by == 自 id` を規約違反にする

**背景:** Phase 1 T12 で dangling（存在しない id 参照）は検出するようになったが、`superseded_by` が自分自身の id を指すケースは素通り（progress-phase1 T12 Minor）。自己参照は無限ループ的な変遷を生むので拒否する。

- [ ] **Step 1: 失敗するテストを追記**

`tools/validator/tests/test_repo_checks.py`:

```python
def test_self_referential_superseded_by_fails(tmp_path):
    write_fact(tmp_path / "domains/tax/self.md",
               id="01JZC2V7E8B3F4G5H6J7K8M9N1",
               status="invalidated",
               invalidation_reason="自己参照の異常系",
               invalidated_at="2026-07-03T10:00:00+09:00",
               superseded_by="01JZC2V7E8B3F4G5H6J7K8M9N1")  # 自分自身
    errors = validate_repo(tmp_path)
    assert any("自己参照" in e or "自身" in e for e in errors)
```

（`write_fact` は既存テストヘルパー。無ければ既存テストの書き方に合わせる）

- [ ] **Step 2: RED 確認**

Run: `cd /Users/masahiro/dev/byteflare-co/agent-organization/tools/validator && uv run pytest tests/test_repo_checks.py -k self_referential -v`
Expected: FAIL（自己参照が素通り）

- [ ] **Step 3: repo_checks.py に自己参照チェックを実装**

`validate_repo` のファイル走査ループ内、`if fact.superseded_by is not None:` のブロックに自己参照判定を追加:

```python
        if fact.superseded_by is not None:
            if fact.superseded_by == fact.id:
                errors.append(f"{rel}: superseded_by が自身の id を参照している（自己参照は不可）")
            else:
                pending_superseded_by.append((rel, fact.superseded_by))
```

- [ ] **Step 4: GREEN 確認と CI**

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization/tools/validator && uv run pytest tests/ -q && uv run plk-validate ../../knowledge
```
Expected: 全 pass・実データ OK

- [ ] **Step 5: Commit**

```bash
cd /Users/masahiro/dev/byteflare-co/agent-organization
git add -A && git commit -m "feat: superseded_by 自己参照を規約違反として検出" && git push
gh run watch --exit-status
```

---

### Task 4: PromotionRequest 状態機械と永続化ストア

**Files:**
- Create: `src/plk_memory/promotions.py`
- Test: `tests/test_promotions.py`

**Interfaces:**
- Consumes: なし（`Settings` は不要。ストアはパスのみ）
- Produces（Task 5/6 が依存）:
  - `PromotionState`（Enum: `proposed`/`approved`/`rejected`/`applied`）
  - `PromotionRequest`（pydantic）: `id`（ULID）, `fact_id`, `from_namespace`, `to_namespace="plk.shared"`, `old_path`, `new_path`, `branch`, `state`, `pr_number: int|None`, `pr_url: str|None`, `reason: str|None`, `created_at`, `updated_at`
  - `PromotionError`（不正遷移）
  - `PromotionStore(path)`: `load() -> dict[str, PromotionRequest]`、`save(map)`、`upsert(pr)`、`get(id) -> PromotionRequest`、`by_state(state) -> list[PromotionRequest]`、`by_fact(fact_id) -> list[PromotionRequest]`。atomic 書き込み（`StateStore` と同型）
  - `transition(pr, new_state) -> PromotionRequest`（許可遷移を検証し `updated_at` を更新して返す。純関数）

**許可遷移:** `proposed → {approved, applied, rejected}`、`approved → {applied, rejected}`、終端 `applied`/`rejected` からの遷移は不可。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_promotions.py`:

```python
import pytest

from plk_memory.promotions import (
    PromotionError, PromotionRequest, PromotionState, PromotionStore, new_promotion, transition,
)


def make_pr(**over) -> PromotionRequest:
    base = dict(
        fact_id="01JZC2V7E8B3F4G5H6J7K8M9N0",
        from_namespace="plk.domain.tax",
        old_path="knowledge/domains/tax/x.md",
        new_path="knowledge/shared/x.md",
        branch="promote/01JZC2V7E8B3F4G5H6J7K8M9N0",
    )
    base.update(over)
    return new_promotion(**base)


def test_new_promotion_defaults():
    pr = make_pr()
    assert pr.state is PromotionState.proposed
    assert pr.to_namespace == "plk.shared"
    assert pr.created_at and pr.updated_at


def test_valid_transitions():
    pr = transition(make_pr(), PromotionState.applied)
    assert pr.state is PromotionState.applied


def test_invalid_transition_from_terminal():
    pr = transition(make_pr(), PromotionState.rejected)
    with pytest.raises(PromotionError):
        transition(pr, PromotionState.applied)


def test_store_roundtrip_and_queries(tmp_path):
    store = PromotionStore(tmp_path / "promotions.json")
    pr1 = make_pr()
    pr2 = make_pr(fact_id="01JZC2V7E8B3F4G5H6J7K8M9N2",
                  old_path="knowledge/domains/dev/y.md", new_path="knowledge/shared/y.md",
                  from_namespace="plk.domain.dev")
    store.upsert(pr1)
    store.upsert(pr2)
    assert set(store.load().keys()) == {pr1.id, pr2.id}
    assert [p.id for p in store.by_state(PromotionState.proposed)] == [pr1.id, pr2.id]
    store.upsert(transition(store.get(pr1.id), PromotionState.applied))
    assert [p.id for p in store.by_state(PromotionState.proposed)] == [pr2.id]
    assert store.by_fact(pr2.fact_id)[0].id == pr2.id


def test_store_atomic_no_partial_file(tmp_path):
    path = tmp_path / "promotions.json"
    PromotionStore(path).upsert(make_pr())
    assert path.exists()
    assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 2: RED 確認** — `uv run pytest tests/test_promotions.py -v` → ERROR（module not found）

- [ ] **Step 3: promotions.py を実装**

```python
"""PromotionRequest 状態機械と永続化（設計書 §5・§9: API 内第一級リソース）。

GitHub PR はこの状態機械のバックエンド実装（github_promotion.py）に過ぎない。
状態機械を API 側に置くことで UI/バックエンド差し替え（Slack Block Kit 等）が
UI アダプタ交換で済む（設計書 §2 の決定）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel
from ulid import ULID


class PromotionState(str, Enum):
    proposed = "proposed"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"


_ALLOWED: dict[PromotionState, set[PromotionState]] = {
    PromotionState.proposed: {PromotionState.approved, PromotionState.applied, PromotionState.rejected},
    PromotionState.approved: {PromotionState.applied, PromotionState.rejected},
    PromotionState.applied: set(),
    PromotionState.rejected: set(),
}


class PromotionError(RuntimeError):
    pass


class PromotionRequest(BaseModel):
    id: str
    fact_id: str
    from_namespace: str
    to_namespace: str = "plk.shared"
    old_path: str
    new_path: str
    branch: str
    state: PromotionState = PromotionState.proposed
    pr_number: int | None = None
    pr_url: str | None = None
    reason: str | None = None
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_promotion(*, fact_id: str, from_namespace: str, old_path: str, new_path: str,
                  branch: str, reason: str | None = None) -> PromotionRequest:
    now = _now()
    return PromotionRequest(
        id=str(ULID()), fact_id=fact_id, from_namespace=from_namespace,
        old_path=old_path, new_path=new_path, branch=branch, reason=reason,
        created_at=now, updated_at=now,
    )


def transition(pr: PromotionRequest, new_state: PromotionState) -> PromotionRequest:
    if new_state not in _ALLOWED[pr.state]:
        raise PromotionError(f"不正な遷移: {pr.state.value} -> {new_state.value}")
    return pr.model_copy(update={"state": new_state, "updated_at": _now()})


class PromotionStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, PromotionRequest]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {k: PromotionRequest.model_validate(v) for k, v in raw.items()}

    def save(self, items: dict[str, PromotionRequest]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        payload = {k: v.model_dump() for k, v in items.items()}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def upsert(self, pr: PromotionRequest) -> None:
        items = self.load()
        items[pr.id] = pr
        self.save(items)

    def get(self, promotion_id: str) -> PromotionRequest:
        return self.load()[promotion_id]

    def by_state(self, state: PromotionState) -> list[PromotionRequest]:
        return [p for p in self.load().values() if p.state is state]

    def by_fact(self, fact_id: str) -> list[PromotionRequest]:
        return [p for p in self.load().values() if p.fact_id == fact_id]
```

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/test_promotions.py -v` → 全 pass

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: PromotionRequest 状態機械と永続化ストア"
```

---

### Task 5: GitHubPromotionBackend（PR 作成・merge 照会）⚠️ verify-and-adapt

**Files:**
- Create: `src/plk_memory/github_promotion.py`
- Modify: `src/plk_memory/gitstore.py`（promote 用 worktree メソッド追加）
- Test: `tests/test_github_promotion.py`、`tests/test_gitstore.py`（worktree 追記）

**Interfaces:**
- Consumes: `GitStore`、`Settings`
- Produces:
  - `GitStore.build_promotion_branch(*, old_rel, new_rel, branch, message) -> None`（**専用 git worktree** で `origin/main` から分岐 → `git mv` → frontmatter の `namespace:` 行を `plk.shared` に書換え → commit → `push origin <branch>`。**メイン作業ツリーの HEAD は動かさない**ので read と競合しない。asyncio.Lock で直列化）
  - `PromotionBackend` プロトコル（Task 6 が Fake を注入するための構造的型）: `async create_pr(pr) -> tuple[int, str]`（PR 番号・URL）、`async merged_state(pr_number) -> str`（`"MERGED"`/`"CLOSED"`/`"OPEN"`）
  - `GitHubPromotionBackend(store, settings)` の実装（`gh` CLI 使用。認証は Mac の既存 `gh auth`。⚠️ verify-and-adapt）
  - 純関数 `promotion_pr_body(pr) -> str`（固定テンプレート・生 HTML/HTML コメント除去。設計書 §7）と `parse_pr_view(json_str) -> str`（`gh pr view --json` 出力から状態を導出）

**設計書 §7 の CI 整合:** PR は `domains/<d>/x.md → shared/x.md` の rename・1 ファイル・`namespace:` 1 行のみ差分。`build_promotion_branch` の worktree 操作はこの形に一致させる（Phase 1 conftest の `rename_with_namespace` と同じ挙動）。

- [ ] **Step 1: 失敗するテスト（純関数と worktree）を書く**

`tests/test_github_promotion.py`:

```python
from plk_memory.github_promotion import parse_pr_view, promotion_pr_body
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
    assert "<" not in body and ">" not in body  # 生 HTML / HTML コメントを含まない


def test_parse_pr_view_maps_states():
    assert parse_pr_view('{"state":"MERGED","mergedAt":"2026-07-03T00:00:00Z"}') == "MERGED"
    assert parse_pr_view('{"state":"CLOSED","mergedAt":null}') == "CLOSED"
    assert parse_pr_view('{"state":"OPEN","mergedAt":null}') == "OPEN"
```

`tests/test_gitstore.py` に追記（worktree ブランチ生成が origin に届く・メイン HEAD が動かない）:

```python
async def test_build_promotion_branch_pushes_and_keeps_main(remote, tmp_path, write_valid_fact):
    origin, seed = remote
    from tests.conftest import make_store, push
    store = make_store(tmp_path, origin)
    # seed に昇格対象ファクトを置いて main に反映
    write_valid_fact(seed, "knowledge/domains/tax/x.md")
    push(seed)
    store.fetch_and_ff()
    main_before = store.head()
    await store.build_promotion_branch(
        old_rel="knowledge/domains/tax/x.md",
        new_rel="knowledge/shared/x.md",
        branch="promote/x",
        message="promote x",
    )
    # メイン作業ツリーの HEAD は不変（read と競合しない）
    assert store.head() == main_before
    # origin にブランチが push されている
    from tests.conftest import sh
    assert "promote/x" in sh(seed, "ls-remote", "--heads", str(origin))
```

- [ ] **Step 2: RED 確認** — `uv run pytest tests/test_github_promotion.py tests/test_gitstore.py -k "pr_body or pr_view or promotion_branch" -v` → FAIL

- [ ] **Step 3: gitstore.py に build_promotion_branch を実装**

`gitstore.py` に追加（`import shutil` を追加）:

```python
    async def build_promotion_branch(self, *, old_rel: str, new_rel: str,
                                     branch: str, message: str) -> None:
        """昇格 PR 用ブランチを専用 worktree で作成し push する（メイン HEAD を動かさない）。"""
        async with self._lock:
            await asyncio.to_thread(self._build_promotion_branch_sync, old_rel, new_rel, branch, message)

    def _build_promotion_branch_sync(self, old_rel: str, new_rel: str, branch: str, message: str) -> None:
        self.git("fetch", "origin", "main")
        wt = self.settings.data_repo_path.parent / f"promote-{branch.replace('/', '_')}"
        if wt.exists():
            self.git("worktree", "remove", "--force", str(wt))
        # origin/main から新ブランチの worktree を作る
        self.git("worktree", "add", "-B", branch, str(wt), "origin/main")
        try:
            import frontmatter
            subprocess.run(["git", "-C", str(wt), "mv", old_rel, new_rel],
                           capture_output=True, text=True, check=True)
            new_path = wt / new_rel
            post = frontmatter.load(new_path)
            post["namespace"] = "plk.shared"
            new_path.write_text(frontmatter.dumps(post), encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "config", "user.email", self.settings.git_author_email], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.name", self.settings.git_author_name], check=True)
            subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", message], capture_output=True, text=True, check=True)
            subprocess.run(["git", "-C", str(wt), "push", "-f", "origin", branch], capture_output=True, text=True, check=True)
        finally:
            self.git("worktree", "remove", "--force", str(wt))
```

（`self._lock`・`asyncio`・`subprocess` は既存 import。`frontmatter` はメソッド内 import で足りる）

- [ ] **Step 4: github_promotion.py を実装** ⚠️ verify-and-adapt（`gh` の実フラグ・JSON キーは実行時に確認して適応し report に記録）

```python
"""GitHub PR を PromotionRequest のバックエンドとして駆動する（設計書 §7・§9）。

⚠️ verify-and-adapt: `gh` CLI のサブコマンド/フラグ/JSON 出力キーは
インストール版で確認して適応する。認証は Mac の既存 `gh auth` を利用
（push 用 fine-grained PAT と PR 用資格情報の 2 分離は EC2/組織展開 期の
課題 — 設計書 §7 準拠の注記のみ。Mac 常駐期は新規 PAT を発行しない）。
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess

from plk_memory.gitstore import GitStore
from plk_memory.promotions import PromotionRequest
from plk_memory.settings import Settings

_HTML = re.compile(r"[<>]")


def promotion_pr_body(pr: PromotionRequest) -> str:
    """固定テンプレート。生 HTML / HTML コメントを含めない（設計書 §7）。"""
    body = (
        "plk-memory 自動生成の昇格リクエストです。\n\n"
        f"- fact_id: {pr.fact_id}\n"
        f"- from: {pr.from_namespace}\n"
        f"- to: {pr.to_namespace}\n"
        f"- rename: {pr.old_path} -> {pr.new_path}\n\n"
        "承認判断は本文でなく Files changed（namespace 行 1 行のみの rename）を正とすること。\n"
    )
    return _HTML.sub("", body)


def parse_pr_view(json_str: str) -> str:
    data = json.loads(json_str)
    if data.get("mergedAt"):
        return "MERGED"
    return str(data.get("state", "OPEN")).upper()


class GitHubPromotionBackend:
    def __init__(self, store: GitStore, settings: Settings):
        self.store = store
        self.settings = settings

    async def create_pr(self, pr: PromotionRequest) -> tuple[int, str]:
        await self.store.build_promotion_branch(
            old_rel=pr.old_path, new_rel=pr.new_path, branch=pr.branch,
            message=f"promote: {pr.old_path} -> {pr.new_path}",
        )
        title = f"promote {pr.fact_id} to shared"
        url = await asyncio.to_thread(
            self._gh, "pr", "create", "--repo", self.settings.repo_slug,
            "--base", "main", "--head", pr.branch,
            "--title", title, "--body", promotion_pr_body(pr),
        )
        url = url.strip()
        m = re.search(r"/pull/(\d+)", url)
        number = int(m.group(1)) if m else 0
        return number, url

    async def merged_state(self, pr_number: int) -> str:
        out = await asyncio.to_thread(
            self._gh, "pr", "view", str(pr_number), "--repo", self.settings.repo_slug,
            "--json", "state,mergedAt",
        )
        return parse_pr_view(out)

    def _gh(self, *args: str) -> str:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
        return r.stdout
```

- [ ] **Step 5: GREEN 確認**（純関数と worktree のみ。`gh` 実呼び出しは Task 10 で live 検証）

Run: `uv run pytest tests/test_github_promotion.py tests/test_gitstore.py -v`
Expected: 純関数・worktree テスト pass（`gh` を叩くメソッドは単体テストしない）

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: GitHubPromotionBackend（worktree でブランチ生成・gh で PR 作成/照会）"
```

---

### Task 6: plk_propose_promotion ツールと applied パイプライン・poller・plk_status 拡張

**Files:**
- Modify: `src/plk_memory/app.py`（`AppServices` に promotion 配線・`tool_propose_promotion`・`poll_promotions`・`tool_status` 拡張・lifespan に poller task）
- Modify: `src/plk_memory/mcp_tools.py`（`plk_propose_promotion` ツール追加）
- Test: `tests/test_app_promotion.py`、`tests/fakes.py`（`FakePromotionBackend` 追加）

**Interfaces:**
- Consumes: `promotions`（Task 4）、`PromotionBackend`（Task 5 の構造的型）、`FactService`、`SyncEngine`
- Produces:
  - `AppServices` は `promotion_store: PromotionStore` と `promotion_backend`（`None` 可＝未設定なら propose はエラー）を保持
  - `AppServices.tool_propose_promotion(fact_id: str, reason: str | None = None) -> dict`:
    - 前提: fact が存在・`status=active`・namespace が `plk.domain.*`（shared/quarantine は不可）・**push 完了（`origin/main..HEAD` の未 push commit が 0）**
    - 既に proposed/approved の PromotionRequest がある fact は再作成しない（`{"error": ..., "promotion_id": 既存}`）
    - `new_promotion(...)` → store.upsert(proposed) → `backend.create_pr` → pr_number/pr_url 保存 → `{"promotion_id", "pr_url", "state": "proposed"}`
  - `AppServices.poll_promotions() -> dict`: proposed/approved を走査し `backend.merged_state` を照会。`MERGED`→`transition(applied)`＋`await self.sync.sync()`（level-triggered が rename を拾い shared へ再 ingest）。`CLOSED`→`transition(rejected)`。集計を返す
  - `AppServices.tool_status()` は `sync.status()` に `pending_promotions`（proposed/approved の一覧）を合成
  - MCP: `plk_propose_promotion(fact_id: str, reason: str | None = None) -> dict`
  - lifespan に `poll_promotions` の周期 task（`sync_interval_seconds` 間隔）を追加

- [ ] **Step 1: FakePromotionBackend を tests/fakes.py に追加**

```python
class FakePromotionBackend:
    """テスト用: PR 作成を記録し、merged_state を制御可能にする。"""

    def __init__(self):
        self.created: list = []
        self.state_by_number: dict[int, str] = {}
        self._next_number = 100

    async def create_pr(self, pr):
        self._next_number += 1
        number = self._next_number
        self.created.append(pr)
        self.state_by_number[number] = "OPEN"
        return number, f"https://github.com/cutsome/agent-organization/pull/{number}"

    async def merged_state(self, pr_number):
        return self.state_by_number.get(pr_number, "OPEN")
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_app_promotion.py`:

```python
import pytest


@pytest.fixture
async def pctx(remote, tmp_path):
    origin, seed = remote
    from tests.conftest import make_settings
    from plk_memory.app import create_app
    from plk_memory.auth import current_client
    from tests.fakes import FakeGraphIndex, FakePromotionBackend
    settings = make_settings(tmp_path, origin, tokens={"tok-cc": "claude-code"}, admin_token="tok-admin")
    backend = FakePromotionBackend()
    app = create_app(settings=settings, graph=FakeGraphIndex(), promotion_backend=backend)
    svcs = app.state.services
    svcs.store.ensure_repo()
    current_client.set("claude-code")
    return svcs, backend


VALID_ARGS = dict(
    namespace="plk.domain.tax", kind="knowhow",
    statement="法人税の中間申告は前期税額20万円超で必要になる制度である",
    why="国税庁タックスアンサーの中間申告の要件に明記されているため",
    how_to_apply="設立2期目以降、前期法人税額を確認して要否を判定する",
    source="https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5000.htm",
)


async def test_propose_creates_promotion_and_pr(pctx):
    svcs, backend = pctx
    add = await svcs.tool_add(**VALID_ARGS)
    out = await svcs.tool_propose_promotion(add["fact_id"], reason="安定運用に足る")
    assert out["state"] == "proposed" and out["pr_url"].endswith("/pull/101")
    assert len(backend.created) == 1


async def test_propose_rejects_non_domain_namespace(pctx):
    svcs, _ = pctx
    # shared は add 自体が不可なので、quarantine を propose 対象にして弾かれることを見る
    q = dict(VALID_ARGS, namespace="plk.quarantine", source_type="external-untrusted")
    add = await svcs.tool_add(**q)
    out = await svcs.tool_propose_promotion(add["fact_id"])
    assert "error" in out


async def test_propose_is_idempotent_per_fact(pctx):
    svcs, backend = pctx
    add = await svcs.tool_add(**VALID_ARGS)
    await svcs.tool_propose_promotion(add["fact_id"])
    out = await svcs.tool_propose_promotion(add["fact_id"])
    assert "error" in out and out.get("promotion_id")
    assert len(backend.created) == 1  # 二重 PR を作らない


async def test_poll_applies_on_merge_and_reingests(pctx):
    svcs, backend = pctx
    add = await svcs.tool_add(**VALID_ARGS)
    out = await svcs.tool_propose_promotion(add["fact_id"])
    # 人間が seed 側で PR をマージした状況を FakeBackend の状態で模す
    number = int(out["pr_url"].rsplit("/", 1)[1])
    backend.state_by_number[number] = "MERGED"
    result = await svcs.poll_promotions()
    assert result["applied"] == 1
    from plk_memory.promotions import PromotionState
    assert svcs.promotion_store.by_state(PromotionState.applied)
    # applied は pending から消える
    status = await svcs.tool_status()
    assert status["pending_promotions"] == []


async def test_status_lists_pending(pctx):
    svcs, _ = pctx
    add = await svcs.tool_add(**VALID_ARGS)
    await svcs.tool_propose_promotion(add["fact_id"])
    status = await svcs.tool_status()
    assert len(status["pending_promotions"]) == 1
    assert status["pending_promotions"][0]["fact_id"] == add["fact_id"]
```

（注: `test_poll_applies_on_merge_and_reingests` は FakePromotionBackend で merge を模すため、実際の main への rename は起きない。`poll_promotions` の sync 呼び出しが例外なく回り applied 遷移することを検証する。real な rename→ingest は Task 10 の live 往復で確認する）

- [ ] **Step 3: RED → 実装 → GREEN**

`app.py` の変更点:

1. `_build_services` と `create_app` に `promotion_backend=None` 引数を通し、`AppServices` に `promotion_store`・`promotion_backend` を渡す。`promotion_store` は `PromotionStore(settings.data_repo_path.parent / "promotions.json")`… ではなく **ローカル状態**として `settings.state_path.parent / "promotions.json"` に置く（SoT でなく運用状態）。`Settings` に `promotion_store_path` を足すか、`state_path` と同ディレクトリに固定。ここでは `settings.state_path.with_name("promotions.json")` を使う。

```python
# import 追加
from plk_memory.promotions import (
    PromotionState, PromotionStore, new_promotion, transition,
)

# AppServices.__init__ に追加
        self.promotion_store = promotion_store
        self.promotion_backend = promotion_backend
```

2. `tool_propose_promotion`:

```python
    async def tool_propose_promotion(self, fact_id: str, reason: str | None = None) -> dict:
        self._require_client()
        if self.promotion_backend is None:
            return {"error": "promotion backend が未設定（enable_github_promotion=True の常駐プロセスのみ有効）"}
        try:
            post, rel = self.facts.get(fact_id)
        except FactNotFound:
            return {"error": f"fact が存在しない: {fact_id}"}
        if post.get("status") != "active":
            return {"error": "active な fact のみ昇格できる"}
        ns = post.get("namespace")
        if not str(ns).startswith("plk.domain."):
            return {"error": f"昇格できるのは plk.domain.* のみ（現在: {ns}）"}
        # 既存の未処理昇格があれば再作成しない
        for existing in self.promotion_store.by_fact(fact_id):
            if existing.state in (PromotionState.proposed, PromotionState.approved):
                return {"error": "既に昇格リクエストが存在する", "promotion_id": existing.id}
        # push 完了がプリコンディション（設計書 §5）
        unpushed = self.store.git("rev-list", "--count", "origin/main..HEAD").strip()
        if unpushed != "0":
            return {"error": f"未 push の commit が {unpushed} 件ある（push 完了後に再試行）"}

        # domains/<d>/<file> -> shared/<file>（CI の check_promotion が要求する rename 形）
        import posixpath
        new_rel = "knowledge/shared/" + posixpath.basename(rel)
        pr = new_promotion(
            fact_id=fact_id, from_namespace=ns, old_path=rel, new_path=new_rel,
            branch=f"promote/{fact_id}", reason=reason,
        )
        self.promotion_store.upsert(pr)
        try:
            number, url = await self.promotion_backend.create_pr(pr)
        except Exception as e:  # noqa: BLE001
            return {"error": f"PR 作成に失敗: {e}", "promotion_id": pr.id}
        pr = pr.model_copy(update={"pr_number": number, "pr_url": url})
        self.promotion_store.upsert(pr)
        return {"promotion_id": pr.id, "pr_url": url, "state": pr.state.value}
```

3. `poll_promotions`:

```python
    async def poll_promotions(self) -> dict:
        if self.promotion_backend is None:
            return {"applied": 0, "rejected": 0, "checked": 0}
        applied = rejected = checked = 0
        for pr in self.promotion_store.by_state(PromotionState.proposed) + \
                self.promotion_store.by_state(PromotionState.approved):
            if pr.pr_number is None:
                continue
            checked += 1
            try:
                state = await self.promotion_backend.merged_state(pr.pr_number)
            except Exception:  # noqa: BLE001 - 照会失敗は次回に回す
                continue
            if state == "MERGED":
                self.promotion_store.upsert(transition(pr, PromotionState.applied))
                await self.sync.sync()  # level-triggered が rename を拾い shared へ再 ingest
                applied += 1
            elif state == "CLOSED":
                self.promotion_store.upsert(transition(pr, PromotionState.rejected))
                rejected += 1
        return {"applied": applied, "rejected": rejected, "checked": checked}
```

4. `tool_status` に pending を合成:

```python
    async def tool_status(self) -> dict:
        status = self.sync.status()
        pending = self.promotion_store.by_state(PromotionState.proposed) + \
            self.promotion_store.by_state(PromotionState.approved)
        status["pending_promotions"] = [
            {"promotion_id": p.id, "fact_id": p.fact_id, "state": p.state.value, "pr_url": p.pr_url}
            for p in pending
        ]
        return status
```

5. `_build_services` は `promotion_store` を組み、`promotion_backend` を注入する。本番は store 生成後に GitHubPromotionBackend を組む必要がある（store は 1 個だけ＝flock 単一インスタンス）ため、**object 注入（テスト用）と `enable_github_promotion`（本番用）の 2 経路**を持たせる:

```python
def _build_services(settings, graph, promotion_backend=None,
                    enable_github_promotion=False) -> AppServices:
    store = GitStore(settings)
    facts = FactService(store, settings)
    if graph is None:
        graph = GraphIndex(settings)
    state_store = StateStore(settings.state_path)
    sync = SyncEngine(store, facts, graph, state_store, settings)
    usage = UsageLog(settings.usage_log_path)
    promotion_store = PromotionStore(settings.state_path.with_name("promotions.json"))
    if promotion_backend is None and enable_github_promotion:
        from plk_memory.github_promotion import GitHubPromotionBackend
        promotion_backend = GitHubPromotionBackend(store, settings)
    return AppServices(
        settings=settings, store=store, facts=facts, graph=graph, sync=sync,
        state_store=state_store, usage=usage,
        promotion_store=promotion_store, promotion_backend=promotion_backend,
    )
```

6. `create_app(settings=None, graph=None, promotion_backend=None, enable_github_promotion=False)` はこれらを `_build_services` に素通しする。テストは `promotion_backend=Fake...` を注入、本番は `enable_github_promotion=True`。lifespan に poller 周期 task を追加:

```python
        async def _periodic_poll() -> None:
            while True:
                await asyncio.sleep(settings.sync_interval_seconds)
                try:
                    await services.poll_promotions()
                except Exception:  # noqa: BLE001
                    pass

        poll_task = asyncio.create_task(_periodic_poll())
```

（`finally` で `poll_task.cancel()` も追加。既存 `task`（periodic_sync）と同様に扱う）

`mcp_tools.py` に追加:

```python
    @mcp.tool
    async def plk_propose_promotion(fact_id: str, reason: str | None = None) -> dict:
        return await services.tool_propose_promotion(fact_id, reason)
```

Run: `uv run pytest tests/test_app_promotion.py tests/test_app.py -v`
Expected: 全 pass

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: plk_propose_promotion・merge ポーリング applied パイプライン・plk_status に pending 昇格"
```

---

### Task 7: 月次キュレーションレポート生成

**Files:**
- Create: `src/plk_memory/curation.py`
- Create: `scripts/curation/__init__.py`、`scripts/curation/run_report.py`
- Test: `tests/test_curation.py`

**Interfaces:**
- Consumes: `FactService.list_posts`、利用ログ JSONL（`usage_log_path`）、`SyncState`（索引件数）
- Produces:
  - `curation.read_usage(path) -> list[dict]`（JSONL を読む。壊れ行はスキップ）
  - `curation.aggregate(posts, usage, *, corpus_conflict_threshold=100) -> dict`:
    - `total_facts`・`active_facts`・`invalidated_facts`
    - `unreferenced`: 利用ログの plk_search で一度もヒット（`hits>0` のクエリで返った fact は追えないため、ここでは「plk_search が呼ばれた総数」と「ヒット週次件数」を集計し、未参照 = **一度も add/invalidate/history の対象になっていない active fact**＋**全期間 plk_search ヒット 0 の近似**として fact 一覧を出す）。実装は「usage ログに現れた fact_id 集合（history/invalidate の対象）に無い active fact」を unreferenced として列挙
    - `search_stats`: `total_searches`・`auto_vs_manual`（`reason=="auto-guideline"` 件数 vs それ以外）・`weekly_hit_counts`（直近週の hits>0 件数）
    - `conflicts`: コーパスが閾値未満なら `{"enabled": false, "reason": "コーパス < 100 件のため矛盾検出は無効（設計書 §9）"}`。閾値以上なら重複 statement の近似検出（同一 namespace 内で statement 完全一致）を返す
  - `curation.render_markdown(agg, *, kill_criteria: str) -> str`（レポート markdown。**運用期キル基準を毎回印字** — 設計書 §11）
  - `scripts/curation/run_report.py`: settings をロード→集計→`agent-organization/reports/curation/YYYY-MM.md` に書いて commit/push

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_curation.py`:

```python
import frontmatter

from plk_memory.curation import aggregate, read_usage, render_markdown


def _post(fid, ns="plk.domain.tax", status="active", statement="x" * 25):
    return frontmatter.Post("body", id=fid, namespace=ns, status=status, kind="knowhow",
                            statement=statement, why="y" * 25, how_to_apply="h" * 20,
                            source="https://e.co", source_type="agent", written_by="t",
                            created_at="2026-07-01T00:00:00+09:00")


def test_read_usage_skips_broken_lines(tmp_path):
    p = tmp_path / "u.jsonl"
    p.write_text('{"tool":"plk_search","hits":2,"reason":"auto-guideline"}\nnot-json\n', encoding="utf-8")
    assert len(read_usage(p)) == 1


def test_aggregate_counts_and_unreferenced():
    posts = [(_post("01A"), "knowledge/domains/tax/a.md"),
             (_post("01B", status="invalidated"), "knowledge/domains/tax/b.md")]
    usage = [{"tool": "plk_search", "hits": 1, "reason": "auto-guideline"},
             {"tool": "plk_search", "hits": 0, "reason": "manual"}]
    agg = aggregate(posts, usage)
    assert agg["total_facts"] == 2 and agg["active_facts"] == 1
    assert agg["search_stats"]["total_searches"] == 2
    assert agg["search_stats"]["auto_vs_manual"] == {"auto": 1, "manual": 1}
    assert "01A" in [u["id"] for u in agg["unreferenced"]]


def test_conflict_detection_disabled_below_threshold():
    posts = [(_post(f"{i:026X}"), f"knowledge/domains/tax/{i}.md") for i in range(5)]
    agg = aggregate(posts, [])
    assert agg["conflicts"]["enabled"] is False


def test_render_prints_kill_criteria():
    md = render_markdown(aggregate([], []), kill_criteria="週3回未満で撤退")
    assert "週3回未満で撤退" in md and "#" in md
```

- [ ] **Step 2: RED 確認** — `uv run pytest tests/test_curation.py -v` → ERROR

- [ ] **Step 3: curation.py を実装**

```python
"""月次キュレーションレポート（設計書 §9・§11）。

矛盾・重複検出はコーパス 100 件到達まで無効（小コーパス期の誤検知抑止）。
運用期キル基準の数値を毎回印字する。
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read_usage(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def aggregate(posts, usage, *, corpus_conflict_threshold: int = 100) -> dict:
    active = [(p, rel) for p, rel in posts if p.get("status") == "active"]
    invalidated = [(p, rel) for p, rel in posts if p.get("status") == "invalidated"]

    searches = [u for u in usage if u.get("tool") == "plk_search"]
    auto = sum(1 for u in searches if u.get("reason") == "auto-guideline")
    manual = len(searches) - auto
    hit_searches = sum(1 for u in searches if (u.get("hits") or 0) > 0)

    # 利用ログに現れた fact_id（history/invalidate 等の明示対象）を「参照済み」とみなす近似
    referenced = {u.get("fact_id") for u in usage if u.get("fact_id")}
    unreferenced = [
        {"id": p.get("id"), "namespace": p.get("namespace"), "statement": p.get("statement")}
        for p, _ in active
        if p.get("id") not in referenced
    ]

    if len(posts) < corpus_conflict_threshold:
        conflicts: dict = {
            "enabled": False,
            "reason": f"コーパス {len(posts)} 件 < {corpus_conflict_threshold} 件のため矛盾検出は無効（設計書 §9）",
        }
    else:
        dupes = [s for s, n in Counter(
            (p.get("namespace"), p.get("statement")) for p, _ in active
        ).items() if n > 1]
        conflicts = {"enabled": True, "duplicate_statements": [d[1] for d in dupes]}

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "total_facts": len(posts),
        "active_facts": len(active),
        "invalidated_facts": len(invalidated),
        "unreferenced": unreferenced,
        "search_stats": {
            "total_searches": len(searches),
            "auto_vs_manual": {"auto": auto, "manual": manual},
            "weekly_hit_counts": hit_searches,
        },
        "conflicts": conflicts,
    }


def render_markdown(agg: dict, *, kill_criteria: str) -> str:
    lines = [
        "# plk-memory 月次キュレーションレポート",
        "",
        f"生成日時: {agg.get('generated_at', '')}",
        "",
        "## サマリ",
        f"- 総ファクト: {agg['total_facts']}（active {agg['active_facts']} / invalidated {agg['invalidated_facts']}）",
        f"- plk_search 総数: {agg['search_stats']['total_searches']}"
        f"（auto {agg['search_stats']['auto_vs_manual']['auto']} /"
        f" manual {agg['search_stats']['auto_vs_manual']['manual']}）",
        f"- ヒットありの検索: {agg['search_stats']['weekly_hit_counts']}",
        "",
        "## 未参照ファクト（棚卸し候補）",
    ]
    if agg["unreferenced"]:
        lines += [f"- `{u['id']}` [{u['namespace']}] {u['statement']}" for u in agg["unreferenced"]]
    else:
        lines.append("- なし")
    lines += ["", "## 矛盾・重複検出"]
    if agg["conflicts"].get("enabled"):
        dups = agg["conflicts"].get("duplicate_statements", [])
        lines += [f"- 重複 statement: {d}" for d in dups] or ["- 重複なし"]
    else:
        lines.append(f"- 無効: {agg['conflicts']['reason']}")
    lines += [
        "",
        "## 運用期キル基準（設計書 §11・毎回印字）",
        f"- {kill_criteria}",
        "",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: run_report.py を実装**

```python
"""月次キュレーションレポートを生成し agent-organization/reports/curation/ に commit する。

usage: uv run python scripts/curation/run_report.py [--out <path>] [--no-commit]
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path

from plk_memory.curation import aggregate, read_usage, render_markdown
from plk_memory.facts import FactService
from plk_memory.gitstore import GitStore
from plk_memory.settings import Settings

KILL = ("4 週連続で動線経由 plk_search の引用が週 3 回未満、または保守が週 30 分超過 →"
        " グラフ層凍結・常駐解除（設計書 §11）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-commit", action="store_true")
    args = ap.parse_args()

    settings = Settings()
    store = GitStore(settings)
    store.ensure_repo()
    facts = FactService(store, settings)
    agg = aggregate(facts.list_posts(), read_usage(settings.usage_log_path))
    md = render_markdown(agg, kill_criteria=KILL)

    month = datetime.now().strftime("%Y-%m")
    rel = f"reports/curation/{month}.md"
    out = settings.data_repo_path / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"wrote {out}")

    if not args.no_commit:
        repo = str(settings.data_repo_path)
        subprocess.run(["git", "-C", repo, "add", rel], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-m", f"docs: {month} キュレーションレポート"], check=True)
        subprocess.run(["git", "-C", repo, "push", "origin", "main"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: GREEN 確認** — `uv run pytest tests/test_curation.py -v` → 全 pass

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: 月次キュレーションレポート（未参照・利用ログ集計・キル基準印字・100件まで矛盾検出無効）"
```

---

### Task 8: read 専用 Web UI（REST・cookie 認証・CSP・本文 sanitize）

**Files:**
- Create: `src/plk_memory/webui.py`
- Create: `src/plk_memory/static/index.html`
- Modify: `src/plk_memory/app.py`（UI ルーター mount・CSP ミドルウェア）
- Modify: `pyproject.toml`（`nh3`・`markdown` を deps に追加）
- Modify: `src/plk_memory/settings.py`（`ui_password: str`・`ui_cookie_name: str` 追加）
- Test: `tests/test_webui.py`

**Interfaces:**
- Consumes: `FactService`（read）、`AppServices.tool_search`（read）、`Settings`
- Produces（設計書 §5: read 専用 REST のみ・Bearer をブラウザに持ち込まない）:
  - `webui.build_ui_router(services) -> APIRouter`:
    - `POST /ui/login`（body `{"password": ...}`）→ 一致で HttpOnly cookie を set（`SameSite=Strict`・`HttpOnly`・`Secure=False`（127.0.0.1 の http のため。公開面ゼロ）・値は `settings.ui_password` から導出したトークン）。不一致は 401
    - `GET /ui/api/facts?namespace=&kind=&status=&q=` → cookie 必須。一覧（`fact_id/statement/namespace/kind/status/path`）。`q` があれば `tool_search` 経由、無ければ `facts.list_posts` をフィルタ
    - `GET /ui/api/facts/{fact_id}` → cookie 必須。detail（frontmatter フィールド＋**sanitize 済み本文 HTML**＋`facts.history`）
    - すべての `/ui/api` は cookie 未提示なら 401 JSON
  - `webui.sanitize_markdown(text) -> str`（`markdown` でレンダリング→`nh3.clean` で allowlist sanitize。設計書 §5: 本文は非信頼入力）
  - `GET /`（静的 `index.html`）と全 `/ui` 応答に **CSP ヘッダ**を付与するミドルウェア

- [ ] **Step 1: pyproject に依存追加**

`[project].dependencies` に `"nh3>=0.2"`, `"markdown>=3.6"` を追加し `uv sync`。

- [ ] **Step 2: settings に UI 設定を追加**

```python
    # Web UI（read 専用）
    ui_password: str = ""          # 空なら UI ログイン不可（本番のみ設定）
    ui_cookie_name: str = "plk_ui"
```

- [ ] **Step 3: 失敗するテストを書く**

`tests/test_webui.py`:

```python
import httpx
import pytest

from plk_memory.webui import sanitize_markdown


def test_sanitize_strips_script_keeps_markup():
    html = sanitize_markdown("# 見出し\n\n<script>alert(1)</script>\n\n**強調**")
    assert "<script" not in html.lower()
    assert "<strong>" in html or "<em>" in html or "<h1>" in html


@pytest.fixture
async def uiclient(remote, tmp_path, write_valid_fact):
    origin, seed = remote
    from tests.conftest import make_settings, push
    from plk_memory.app import create_app
    from tests.fakes import FakeGraphIndex
    write_valid_fact(seed, "knowledge/domains/tax/x.md")
    push(seed)
    settings = make_settings(tmp_path, origin, tokens={"tok-cc": "cc"},
                             admin_token="adm", ui_password="s3cret")
    app = create_app(settings=settings, graph=FakeGraphIndex())
    app.state.services.store.ensure_repo()
    app.state.services.store.fetch_and_ff()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://plk") as c:
        yield c


async def test_ui_api_requires_cookie(uiclient):
    r = await uiclient.get("/ui/api/facts")
    assert r.status_code == 401


async def test_ui_login_sets_httponly_cookie_and_lists(uiclient):
    r = await uiclient.post("/ui/login", json={"password": "s3cret"})
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie
    r2 = await uiclient.get("/ui/api/facts")
    assert r2.status_code == 200
    assert any(f["namespace"] == "plk.domain.tax" for f in r2.json()["facts"])


async def test_ui_login_wrong_password(uiclient):
    r = await uiclient.post("/ui/login", json={"password": "nope"})
    assert r.status_code == 401


async def test_csp_header_present(uiclient):
    r = await uiclient.get("/")
    assert "content-security-policy" in {k.lower() for k in r.headers}


async def test_ui_detail_has_sanitized_body_and_history(uiclient):
    await uiclient.post("/ui/login", json={"password": "s3cret"})
    facts = (await uiclient.get("/ui/api/facts")).json()["facts"]
    fid = facts[0]["fact_id"]
    r = await uiclient.get(f"/ui/api/facts/{fid}")
    assert r.status_code == 200
    body = r.json()
    assert "body_html" in body and "history" in body
    assert "<script" not in body["body_html"].lower()
```

- [ ] **Step 4: RED → 実装 → GREEN**

`webui.py`:

```python
"""read 専用 Web UI（設計書 §5）。

ブラウザは REST のみに接続する（MCP・Bearer を持ち込まない）。閲覧認証は
HttpOnly cookie。本文は非信頼入力として markdown を sanitize（nh3）する。
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import markdown as md
import nh3
from fastapi import APIRouter, HTTPException, Request, Response

if TYPE_CHECKING:
    from plk_memory.app import AppServices

_ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "p", "ul", "ol", "li", "strong", "em", "code",
    "pre", "blockquote", "a", "br", "hr", "table", "thead", "tbody", "tr", "th", "td",
}


def sanitize_markdown(text: str) -> str:
    html = md.markdown(text or "", extensions=["fenced_code", "tables"])
    return nh3.clean(html, tags=_ALLOWED_TAGS, attributes={"a": {"href", "title"}})


def _cookie_value(password: str) -> str:
    return hashlib.sha256(("plk-ui:" + password).encode("utf-8")).hexdigest()


def build_ui_router(services: "AppServices") -> APIRouter:
    router = APIRouter()
    settings = services.settings
    expected = _cookie_value(settings.ui_password) if settings.ui_password else None

    def _require_cookie(request: Request) -> None:
        if expected is None:
            raise HTTPException(status_code=401, detail="UI is disabled")
        if request.cookies.get(settings.ui_cookie_name) != expected:
            raise HTTPException(status_code=401, detail="login required")

    @router.post("/ui/login")
    async def ui_login(payload: dict, response: Response) -> dict:
        if not settings.ui_password or payload.get("password") != settings.ui_password:
            raise HTTPException(status_code=401, detail="invalid password")
        response.set_cookie(
            settings.ui_cookie_name, _cookie_value(settings.ui_password),
            httponly=True, samesite="strict", secure=False, max_age=86400,
        )
        return {"ok": True}

    @router.get("/ui/api/facts")
    async def ui_facts(request: Request, namespace: str | None = None,
                       kind: str | None = None, status: str = "active",
                       q: str | None = None) -> dict:
        _require_cookie(request)
        if q:
            res = await services.tool_search(
                query=q, namespaces=[namespace] if namespace else None,
                kind=kind, status=status, limit=50, reason="webui",
            )
            return {"facts": res.get("hits", []), "degraded": res.get("degraded", False)}
        facts = []
        for post, rel in services.facts.list_posts():
            if not post.get("id"):
                continue
            if namespace and post.get("namespace") != namespace:
                continue
            if kind and post.get("kind") != kind:
                continue
            if status and post.get("status") != status:
                continue
            facts.append({
                "fact_id": post.get("id"), "statement": post.get("statement"),
                "namespace": post.get("namespace"), "kind": post.get("kind"),
                "status": post.get("status"), "path": rel,
            })
        return {"facts": facts}

    @router.get("/ui/api/facts/{fact_id}")
    async def ui_fact_detail(request: Request, fact_id: str) -> dict:
        _require_cookie(request)
        from plk_memory.facts import FactNotFound
        try:
            post, rel = services.facts.get(fact_id)
        except FactNotFound:
            raise HTTPException(status_code=404, detail="not found")
        meta = {k: v for k, v in post.metadata.items()}
        return {
            "fact_id": fact_id, "path": rel, "meta": meta,
            "body_html": sanitize_markdown(post.content),
            "history": services.facts.history(fact_id),
        }

    return router
```

`app.py` の `create_app` に UI 配線と CSP ミドルウェアを追加:

```python
    from starlette.staticfiles import StaticFiles  # もし使うなら
    from plk_memory.webui import build_ui_router

    # CSP: 本文 sanitize と併せて XSS を二重に防ぐ（設計書 §5）
    @app.middleware("http")
    async def _csp(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/ui"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:"
            )
        return response

    app.include_router(build_ui_router(services))

    from pathlib import Path as _Path
    _index = _Path(__file__).parent / "static" / "index.html"

    @app.get("/")
    async def _ui_index():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_index.read_text(encoding="utf-8"))
```

**注意（BearerAuthMiddleware との整合）:** 現行 `BearerAuthMiddleware` は `/mcp`・`/admin` のみ検査し `/`・`/healthz` はスルーする。`/ui` は Bearer 検査対象外（UI は cookie 認証）なので追加変更不要。UI ルーターの `_require_cookie` が独自に守る。

`static/index.html`（自己完結 SPA。一覧・namespace/kind/status フィルタ・全文検索・クリックで変遷表示。インライン CSS/JS のみ・外部リソース参照なし＝CSP 準拠）:

```html
<!doctype html>
<meta charset="utf-8">
<title>plk-memory</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 1rem; }
  input, select, button { padding: .3rem; margin: .2rem; }
  .fact { border-bottom: 1px solid #ccc; padding: .4rem 0; cursor: pointer; }
  .ns { color: #567; font-size: .8rem; }
  #detail { position: fixed; right: 0; top: 0; width: 40%; height: 100%;
            overflow: auto; background: #fafafa; border-left: 1px solid #ccc; padding: 1rem; }
</style>
<h1>plk-memory</h1>
<div id="login">
  <input id="pw" type="password" placeholder="password">
  <button onclick="login()">login</button>
</div>
<div id="main" style="display:none">
  <input id="q" placeholder="検索"><button onclick="load()">検索</button>
  <select id="ns"><option value="">(namespace)</option></select>
  <select id="status"><option value="active">active</option><option value="invalidated">invalidated</option></select>
  <div id="list"></div>
</div>
<div id="detail" style="display:none"></div>
<script>
async function login() {
  const r = await fetch('/ui/login', {method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify({password: document.getElementById('pw').value})});
  if (r.ok) { document.getElementById('login').style.display='none';
    document.getElementById('main').style.display='block'; initNs(); load(); }
  else alert('login failed');
}
function initNs() {
  const opts = ['plk.domain.tax','plk.domain.legal','plk.domain.shaho','plk.domain.dev',
    'plk.domain.backoffice','plk.domain.biz','plk.shared'];
  const sel = document.getElementById('ns');
  opts.forEach(o => { const e=document.createElement('option'); e.value=o; e.textContent=o; sel.appendChild(e); });
}
async function load() {
  const q = document.getElementById('q').value, ns = document.getElementById('ns').value,
        st = document.getElementById('status').value;
  const p = new URLSearchParams(); if (q) p.set('q', q); if (ns) p.set('namespace', ns); if (st) p.set('status', st);
  const r = await fetch('/ui/api/facts?' + p.toString());
  const data = await r.json();
  const list = document.getElementById('list'); list.innerHTML='';
  (data.facts||[]).forEach(f => {
    const d = document.createElement('div'); d.className='fact';
    d.innerHTML = '<div>'+escapeHtml(f.statement||'')+'</div><div class="ns">'+
      escapeHtml(f.namespace||'')+' · '+escapeHtml(f.kind||'')+' · '+escapeHtml(f.status||'')+'</div>';
    d.onclick = () => detail(f.fact_id); list.appendChild(d);
  });
}
async function detail(id) {
  const r = await fetch('/ui/api/facts/'+encodeURIComponent(id));
  const data = await r.json(); const el = document.getElementById('detail');
  el.style.display='block';
  el.innerHTML = '<button onclick="document.getElementById(\'detail\').style.display=\'none\'">×</button>'+
    '<h2>'+escapeHtml(data.meta.statement||'')+'</h2>'+
    '<p><b>why:</b> '+escapeHtml(data.meta.why||'')+'</p>'+
    '<p><b>how:</b> '+escapeHtml(data.meta.how_to_apply||'')+'</p>'+
    '<div>'+data.body_html+'</div>'+
    '<h3>変遷</h3><pre>'+escapeHtml(JSON.stringify(data.history, null, 1))+'</pre>';
}
function escapeHtml(s){return (s+'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
</script>
```

Run: `uv run pytest tests/test_webui.py -v`
Expected: 全 pass（`body_html` は server 側で sanitize 済み。UI の `escapeHtml` は二重防御）

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: read 専用 Web UI（cookie 認証・CSP・本文 sanitize・一覧/検索/変遷）"
```

---

### Task 9: Mac 常駐化（launchd・FalkorDB 自動再起動・運用 runbook）⚠️ 環境依存・verify-and-adapt・report 必須

**Files:**
- Modify: `src/plk_memory/app.py`（本番エントリ `create_prod_app` 追加）
- Create: `deploy/com.byteflare.plk-memory.plist`
- Modify: `README.md`（運用 runbook 追記）
- Modify: `docker-compose.yml`（`restart: unless-stopped` の確認のみ — Phase 1 で設定済みなら変更なし）

**Interfaces:**
- Consumes: `create_app(..., enable_github_promotion=True)`（Task 6）
- Produces: Mac 上で FalkorDB＋API が常駐し、再起動・クラッシュ後も自動復帰。`/healthz` が 127.0.0.1 から 200

**⚠️ この Task は実機（この Mac）の環境に依存する。各ステップは「実行→検証コマンド→結果を report に記録」の形で進める。LLM/embedder は現行のローカル Ollama 設定のまま（変更なし・費用ゼロ）。**

- [ ] **Step 1: 本番エントリポイントを用意**

`src/plk_memory/app.py` に本番用ファクトリを追加（Task 6 の `enable_github_promotion` 経路を使う。store は create_app 内で 1 個だけ生成され GitHubPromotionBackend に渡るため flock 単一インスタンスと両立する）:

```python
def create_prod_app() -> FastAPI:
    return create_app(settings=Settings(), enable_github_promotion=True)
```

（uvicorn 起動: `uvicorn plk_memory.app:create_prod_app --factory`。`PLK_*` は pydantic-settings が repo 直下の `.env` から読む — launchd の `WorkingDirectory` を repo に向けるのはこのため）

- [ ] **Step 2: .env に常駐設定を反映**

repo 直下 `.env`（gitignore 済み）に以下を確認・追記:

```
PLK_INGEST_MODE=triplet          # チェックポイント拘束: 常駐既定は triplet
PLK_UI_PASSWORD=<ui-pass>        # Task 8 の Web UI 用（openssl rand -hex 8 等で生成）
# LLM/embedder は Phase 1 のまま（PLK_LLM_PROVIDER=openai-compatible / Ollama）— 変更しない
```

- [ ] **Step 3: FalkorDB の自動再起動を確認**

Run: `grep -n "restart" /Users/masahiro/dev/byteflare-co/plk-memory/docker-compose.yml`
Expected: `restart: unless-stopped`（Phase 1 Task 10 で設定済み）。無ければ falkordb サービスに追記。Docker Desktop の「ログイン時に自動起動」が ON であることを確認し report に記録（OFF なら ON にする — FalkorDB の自動復帰前提）。

- [ ] **Step 4: launchd plist を作成** ⚠️ verify-and-adapt（`uv` の絶対パスは `which uv` で確認して埋める。launchd は PATH を継承しないため `gh`・`git`・`ollama` の在処を含む PATH を明示する）

`deploy/com.byteflare.plk-memory.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.byteflare.plk-memory</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/uv</string>
    <string>run</string>
    <string>uvicorn</string>
    <string>plk_memory.app:create_prod_app</string>
    <string>--factory</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8735</string>
    <string>--workers</string>
    <string>1</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/masahiro/dev/byteflare-co/plk-memory</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/masahiro/.plk/logs/plk-memory.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/masahiro/.plk/logs/plk-memory.err.log</string>
</dict>
</plist>
```

（`ANTHROPIC_API_KEY` は不要 — LLM はローカル Ollama。`gh` は keychain ベースの `gh auth` 認証を使うため plist に資格情報を書かない）

- [ ] **Step 5: 常駐を開始して検証** ⚠️ verify-and-adapt（`launchctl bootstrap/bootout/kickstart` の実挙動は macOS バージョンで確認し、逸脱を report に記録）

```bash
mkdir -p ~/.plk/logs
cp deploy/com.byteflare.plk-memory.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.byteflare.plk-memory.plist
sleep 3 && curl -s http://127.0.0.1:8735/healthz    # {"ok":true}
# KeepAlive の自動復帰確認:
pkill -f "plk_memory.app:create_prod_app" ; sleep 5
curl -s http://127.0.0.1:8735/healthz               # 自動再起動して {"ok":true}
```

Expected: healthz 200 → kill 後も 5 秒程度で自動復帰して 200。結果（復帰所要時間・ログ末尾）を report に記録。

- [ ] **Step 6: flock 単一レプリカガードとの整合を実機確認**

```bash
# launchd 常駐が生きた状態で手動二重起動を試みる:
cd /Users/masahiro/dev/byteflare-co/plk-memory
uv run uvicorn plk_memory.app:create_prod_app --factory --port 8736
```

Expected: 2 個目のプロセスは `AnotherInstanceRunning`（writer ロック保持中）で fail-fast（起動失敗）。launchd の KeepAlive とは整合する（launchd 管理プロセスの終了時に flock は OS が解放するため、再起動ループに陥らない）。結果を report に記録。

- [ ] **Step 7: 運用 runbook を README に追記**

`README.md` に「常駐運用（launchd）」セクションを追記。内容（この見出し構成で書く）:
1. **起動**: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.byteflare.plk-memory.plist`
2. **停止**: `launchctl bootout gui/$(id -u)/com.byteflare.plk-memory`（KeepAlive ごと止まる）
3. **再起動**: `launchctl kickstart -k gui/$(id -u)/com.byteflare.plk-memory`
4. **ログ**: `~/.plk/logs/plk-memory.{out,err}.log`（`tail -f` で追う）
5. **前提サービス**: Docker Desktop 自動起動（FalkorDB `restart: unless-stopped`）・Ollama 常駐（`ollama serve` / メニューバーアプリ）。どちらか停止時は plk_search が degraded 応答（書き込みと SoT は生存）
6. **単一レプリカ**: writer flock により二重起動は fail-fast。`workers=1` 固定
7. **EC2/組織展開 期への持ち越し注記（設計書 §7 準拠）**: Tailscale 内限定公開・push 用 fine-grained PAT（contents:write）と PR 用資格情報の 2 分離・実ホスト名 bind 時の DNS リバインディング allowlist（`PLK_ALLOWED_HOSTS`）は本 Phase では未実施。Mac 常駐期は 127.0.0.1 bind＋既存 ssh/gh 認証で運用する

- [ ] **Step 8: report と Commit**

report に記載必須: uv/gh の実パス・launchctl 実コマンドと逸脱・KeepAlive 復帰確認の結果・flock 二重起動 fail-fast の確認・Docker Desktop/Ollama 自動起動の状態。

```bash
cd /Users/masahiro/dev/byteflare-co/plk-memory
git add deploy/ README.md src/plk_memory/app.py && git commit -m "feat: Mac 常駐化（launchd plist・本番エントリ・運用 runbook）"
```

---

### Task 10: 全クライアント実接続・検索動線配布・昇格 1 往復の実証 ⚠️ 環境依存・report 必須

**Files:**
- Modify: `clients/*.md`（常駐前提の注意を追記。URL は localhost のまま）
- Create: `clients/DISTRIBUTION.md`（各クライアントへの動線配布記録）

**Interfaces:**
- Consumes: Task 9 の稼働中の常駐サーバー（`http://127.0.0.1:8735`）、`clients/`（Phase 1 のテンプレート）、`clients/guideline-line.md`
- Produces: Phase 2 完了条件（昇格パイプ 1 往復・全クライアント接続）の実証記録

**⚠️ 環境依存。実接続と実往復を行い結果を report に記録する。**

- [ ] **Step 1: clients テンプレートを常駐前提に更新**

URL は `http://127.0.0.1:8735/mcp` のまま（変更不要であることを確認）。各テンプレートに常駐前提の注意を追記: launchd 常駐のため手動起動は不要・停止時は縮退（メモリなしで続行）・Codex は停止中サーバーで初回ターン 10 秒ブロックのため長期停止時は `enabled=false` を推奨。トークンは各クライアント個別（Phase 1 の 4 トークン設計を踏襲）。

- [ ] **Step 2: 4 クライアントを実接続**

- Claude Code: `claude mcp add --transport http plk http://127.0.0.1:8735/mcp --header "Authorization: Bearer $PLK_TOKEN"` → `mcp__plk__plk_search` が見えることを確認
- Codex: `codex mcp add plk --url http://127.0.0.1:8735/mcp --bearer-token-env-var PLK_TOKEN`（無応答時 10 秒ブロック対策の `enabled=false` 手順も記載）
- Hermes: `~/.hermes/config.yaml` に mcp_servers.plk を追加 → `mcp_plk_plk_search` 確認
- 自作 1 体（Agent SDK）: `ClaudeAgentOptions(mcp_servers={"plk": {"type": "http", "url": "http://127.0.0.1:8735/mcp", ...}}, allowed_tools=["mcp__plk__*"])` で 1 クエリ実行

各クライアントで `plk_search("持続化補助金の経費は税込か")` を実行しヒットを確認。結果を report に記録。

- [ ] **Step 3: 検索動線を各クライアント設定に配布**

`clients/guideline-line.md` の 1 行を CLAUDE.md / Codex AGENTS.md / Hermes システムプロンプト / 自作エージェントのプロンプトへ実配布。`reason="auto-guideline"` が利用ログに記録されることを 1 件確認。配布先を `clients/DISTRIBUTION.md` に記録。

- [ ] **Step 4: 昇格 1 往復の実証 — PR 作成前にユーザーの明示承認を得る**

**外部書き込み原則（CLAUDE.md）:** `plk_propose_promotion` は実 GitHub（cutsome/agent-organization）に PR を作成する外部書き込み。実行前に必ず以下をユーザーへ全文プレビュー提示し、明示承認を得てからのみ実行する:
- 昇格対象ファクト（fact_id・statement・現 namespace・ファイルパス）
- 作成される PR のタイトル・本文（`promotion_pr_body` の出力）・ブランチ名・rename 内容（`domains/<d>/x.md → shared/x.md`＋namespace 1 行書換え）

承認後の手順:

```bash
# Mac 上で（write トークン）:
# 1. 昇格対象の active な domain ファクトを 1 件選び、上記プレビューを提示 → ユーザー承認
# 2. 承認後に plk_propose_promotion を実行 → PR URL を受け取る
#    （MCP 経由 or REST。plk_status の pending_promotions に proposed が出ること）
# 3. GitHub で PR を確認（CI: 昇格 PR チェックが green＝namespace 1 行の rename）
# 4. 人間（ユーザー）が PR をレビュー・merge
# 5. poller（sync_interval）を待つ or /admin/sync を叩いて poll を促す
#    → PromotionRequest が applied、shared/ へ rename、shared として再 ingest
# 6. plk_search で当該ファクトが plk.shared として引けることを確認
```

Expected（完了条件）: 昇格パイプが 1 往復（承認→propose→PR→CI green→merge→ポーリング検知→applied→ingest）。`plk_status.pending_promotions` から消え、fact が `plk.shared` で検索ヒット。全 4 クライアント接続済み。すべて report に記録。

- [ ] **Step 5: Commit**

```bash
git add clients/ && git commit -m "docs: 常駐前提の接続テンプレート更新・動線配布記録・昇格 1 往復の手順"
```

---

## Phase 2 完了条件（設計書 §11 Phase 2・2026-07-03 改訂: Mac 常駐）

- [ ] Mac（launchd・127.0.0.1 bind・公開面ゼロ・単一レプリカ）に FalkorDB＋API が常駐し、クラッシュ後も自動復帰して `/healthz` が 200
- [ ] PromotionRequest 状態機械（proposed/approved/rejected/applied）が永続化され、`plk_propose_promotion` が PR を自動作成
- [ ] 昇格パイプが 1 往復（ユーザー承認→propose→PR→merge→ポーリング検知→applied→ingest）し、fact が `plk.shared` で検索ヒット
- [ ] 月次キュレーションレポート（未参照・利用ログ集計・キル基準印字）が生成され data repo に commit できる
- [ ] read 専用 Web UI（cookie 認証・CSP・本文 sanitize・一覧/フィルタ/検索/変遷）が localhost で閲覧可能
- [ ] cheap fixes 完了: git identity 設定化・DOMAINS 設定化・plk_search recall 改善・/admin/reindex 二重起動ガード・superseded_by 自己参照検出
- [ ] 全クライアント（CC/Codex/Hermes/自作1体）が接続し、検索動線が配布され利用ログが `reason` を記録
- [ ] 常駐サーバーの `ingest_mode=triplet`・episode reindex 不実施（グラフ層凍結気味の拘束を遵守）
