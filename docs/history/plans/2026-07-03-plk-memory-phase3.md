# plk-memory Phase 3（組織展開 逆輸入パッケージ）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** plk-memory を「組織展開 の誰かが半日で stg に立てられる」逆輸入パッケージに仕上げる（P2 持ち越しの安価修正・認証アダプタの実換装 1 回・Slack 承認アダプタのスタブ・移行ガイド・運用知見レポート・README 総仕上げ）。

**Architecture:** 現行コード（HEAD=`b5f88df`, 102 tests）に対する追補。コード変更は「並行性バグ 2 件の修正」「JWT/JWKS 認証アダプタの dormant 追加（既定は静的 Bearer のまま）」「Slack PromotionBackend スタブ 1 ファイル追加」の 3 点に閉じ、残りはドキュメント資産（MIGRATION.md / LESSONS.md / README・DISTRIBUTION.md 更新）。ポート境界（FactStore / GraphIndex / WriteSerializer / PromotionBackend / AuthProvider / LogSink）は既に実装済みなので、Phase 3 は「境界の実在を非 GitHub / 非 Bearer 実装で一度ずつ通す」ことと「逆輸入の受け手が読む文書」を作ることが本体。

**Tech Stack:** Python 3.12 / FastAPI / FastMCP 3.4.2（`mcp 1.28.1`, `mcp>=1.27,<2` ピン）/ graphiti-core 0.29.2 / FalkorDB / pytest（asyncio auto）/ pydantic-settings / authlib 1.7.2 + PyJWT 2.13.0（JWT 換装用・既存依存）。

## Global Constraints

以下は設計書（`specs/2026-07-02-plk-memory-design.md`）のプロジェクト全体規約。全タスクの要件に暗黙に含まれる。

- **言語**: ドキュメント・コメント・コミットメッセージは日本語。文字コード UTF-8。
- **依存ピン**: `graphiti-core>=0.28.2`（現 0.29.2。0.28.2 未満に Cypher injection 脆弱性）・`mcp>=1.27,<2`・`falkordb<2`・`fastmcp==3.4.2`。新規依存は追加しない（authlib / PyJWT / cryptography は既に依存グラフ内にある）。
- **単一 writer 不変条件**: データリポジトリ書き込みは専用 clone 経由の単一 writer（`flock`）。`workers>1` は起動時 fail-fast。この不変条件を壊す変更は禁止。
- **written_by はサーバー導出**: クライアント申告値は無視。API 経由の `source_type` 上限は `agent`（`user` は人間の PR 直編集のみ・CI 強制）。
- **group_id はハイフン区切り**（`plk-main` / `plk-quarantine` / `plk-domain-tax`）。namespace（frontmatter）はドット区切り（`plk.domain.tax`）。graphiti の `validate_group_id` が `^[a-zA-Z0-9_-]+$` のみ許可しドットを拒否するため。
- **全 MCP ツールは 60 秒以内に応答**（Codex `tool_timeout` の最小制約）。`/healthz` は即応。
- **Mac 運用継続**: Phase 3 の認証換装は「JWTVerifier モードを 1 回起動して工数を実測し、静的 Bearer に戻す」もの。既定設定は `auth_mode=bearer` のまま。新規 Auth0 等の外部アカウントは作らない（外部承認不要の範囲）。
- **ANTHROPIC_API_KEY は `.env` に書かない**（シェル環境で export）。
- **テスト方針**: TDD。各コード変更は失敗するテストを先に書く。ドキュメントタスクは検証ステップ＝実手順の dry-run（grep で参照先の実在確認・cited 数値の突き合わせ）。
- **verify-and-adapt**: `gh` CLI・FastMCP JWTVerifier・authlib の API はインストール版で `--help` / `inspect.signature` を実行して確認してから使う（本計画のシグネチャは 2026-07-03 時点の実測値）。

---

## File Structure

**変更するファイル:**
- `src/plk_memory/sync.py` — `SyncEngine` に `_do_reindex` / `begin_reindex` / `end_reindex` を分離（reindex silent-drop 修正）
- `src/plk_memory/app.py` — `/admin/reindex` ルートを atomic check-and-set に・`tool_propose_promotion` の push プリコンディションを重複チェック前へ移動・`build_mcp` 呼び出しは不変
- `src/plk_memory/settings.py` — 認証モード関連の設定キー追加（`auth_mode` ほか）
- `src/plk_memory/auth.py` — `build_jwt_verifier` 追加・`BearerAuthMiddleware` に jwt モードの current_client 導出を追加
- `src/plk_memory/mcp_tools.py` — `build_mcp` で `auth_mode=jwt` 時に `FastMCP(..., auth=verifier)` を渡す
- `src/plk_memory/app.py` — `/.well-known/jwks.json` ルート追加（jwt モードのローカル JWKS 提供）
- `README.md` — §7 に UI auth 強化を EC2 前必須として追記・全体総仕上げ
- `clients/DISTRIBUTION.md` — 動線 3 ファイルの配布済み実態に更新
- `.env.example` — 認証モード設定のコメント追記

**新規作成するファイル:**
- `src/plk_memory/slack_promotion.py` — Slack PromotionBackend スタブ（Block Kit ペイロード生成・承認コールバック→transition）
- `scripts/auth/__init__.py`, `scripts/auth/issue_jwt.py` — 自己発行 JWT ＋ローカル JWKS 生成スクリプト（4 クライアント接続確認・工数実測用）
- `tests/test_slack_promotion.py` — Slack スタブのゴールデンテスト
- `tests/test_jwt_auth.py` — JWTVerifier の受理/拒否ゴールデンテスト
- `docs/MIGRATION.md` — 組織展開 が半日で stg に立てるための移行ガイド＋差分表
- `docs/LESSONS.md` — 運用知見レポート（逆輸入の本体資産）

---

### Task 1: P2 持ち越しの並行性バグ 2 件を修正

**Files:**
- Modify: `src/plk_memory/sync.py:139-153`（`reindex` を `_do_reindex` / `begin_reindex` / `end_reindex` に分離）
- Modify: `src/plk_memory/app.py:415-427`（`/admin/reindex` ルート）
- Modify: `src/plk_memory/app.py:233-276`（`tool_propose_promotion` の push プリコンディション位置）
- Test: `tests/test_sync.py`（reindex）・`tests/test_app_promotion.py`（propose 並行）

**Interfaces:**
- Consumes: `SyncEngine.maintenance: bool`・`SyncEngine._sync_lock: asyncio.Lock`・`SyncEngine._sync_locked()`・`SyncEngine.reindex()`・`AppServices.tool_propose_promotion(fact_id, reason)`・`PromotionStore.by_fact(fact_id) -> list[PromotionRequest]`
- Produces: `SyncEngine.begin_reindex() -> bool`（同期 check-and-set。既に実行中なら False）・`SyncEngine.end_reindex() -> None`・`SyncEngine._do_reindex() -> dict`（フラグ管理なしの本体）。`reindex()` は後方互換（自己フラグ管理＋`ReindexInProgress`）を維持

#### 1a. reindex silent-drop（連打の 2 件目が 200 'started' を返す）

背景: 現行の `/admin/reindex` は `services.sync.maintenance` を read してから `background_tasks.add_task` で `reindex()` を後追い実行する。`reindex()` が実際に `maintenance=True` を立てるのは背景タスクが走る時点なので、ルートが 200 を返してから背景タスクが走るまでの窓で来た 2 件目のリクエストが check をすり抜け、両方 200 'started' を返す（2 件目は後で `ReindexInProgress` になり `_guarded_reindex` の except に飲まれて silent drop）。修正 = フラグをルート側で先行セットして atomic 化する。

- [ ] **Step 1: 失敗するテストを書く（begin_reindex の atomic check-and-set）**

`tests/test_sync.py` に追記:

```python
async def test_begin_reindex_is_atomic_check_and_set(engine):
    eng = engine
    assert eng.begin_reindex() is True      # 1 件目は取得成功
    assert eng.maintenance is True
    assert eng.begin_reindex() is False     # 2 件目は実行中を検知して False
    eng.end_reindex()
    assert eng.maintenance is False
    assert eng.begin_reindex() is True       # 解放後は再取得できる
    eng.end_reindex()
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_sync.py::test_begin_reindex_is_atomic_check_and_set -v`
Expected: FAIL（`AttributeError: 'SyncEngine' object has no attribute 'begin_reindex'`）

- [ ] **Step 3: SyncEngine を分離実装**

`src/plk_memory/sync.py` の `reindex` メソッド（139-153 行）を以下に置換:

```python
    def begin_reindex(self) -> bool:
        """ルート用の同期 check-and-set。既に実行中なら False。
        event loop 上で await を挟まずに呼ぶことで、/admin/reindex 連打の
        2 件目を確実に 409 にする（silent drop 修正）。"""
        if self.maintenance:
            return False
        self.maintenance = True
        return True

    def end_reindex(self) -> None:
        self.maintenance = False

    async def _do_reindex(self) -> dict:
        """フラグ管理を含まない再構築本体。呼び出し側が maintenance を保持している前提。"""
        async with self._sync_lock:
            await self.graph.clear(self.settings.all_groups())
            state = self.state_store.load()
            state.facts = {}
            state.dead_letters = {}
            state.last_ingested_commit = None
            self.state_store.save(state)
            return await self._sync_locked()

    async def reindex(self) -> dict:
        """スタンドアロン用（テスト・手動）。自己でフラグを立て、二重起動を拒否する。"""
        if not self.begin_reindex():
            raise ReindexInProgress("reindex は既に実行中")
        try:
            return await self._do_reindex()
        finally:
            self.end_reindex()
```

- [ ] **Step 4: begin_reindex テストが通ることを確認・既存 reindex テストの非回帰を確認**

Run: `uv run pytest tests/test_sync.py -v -k reindex`
Expected: PASS（`test_begin_reindex_is_atomic_check_and_set` 追加分＋既存 `test_reindex_clears_and_rebuilds`・`test_reindex_rejects_double_start` が緑のまま。後者 2 つは `reindex()` の後方互換で維持される）

- [ ] **Step 5: ルートをフラグ先行セットに変更**

`src/plk_memory/app.py` の `/admin/reindex` ルート（415-427 行）を置換:

```python
    @app.post("/admin/reindex")
    async def admin_reindex(background_tasks: BackgroundTasks) -> dict:
        # フラグをルート側で先行セット（begin_reindex は await を挟まない atomic）。
        # 連打の 2 件目は背景タスク開始前にここで 409 になり、silent drop を防ぐ。
        if not services.sync.begin_reindex():
            raise HTTPException(status_code=409, detail="reindex は既に実行中")

        async def _guarded_reindex() -> None:
            try:
                await services.sync._do_reindex()
            except Exception:  # noqa: BLE001 - 背景ジョブの失敗でサーバーを落とさない
                pass
            finally:
                services.sync.end_reindex()

        background_tasks.add_task(_guarded_reindex)
        return {"status": "started"}
```

- [ ] **Step 6: 既存のルート二重起動テストが通ることを確認**

Run: `uv run pytest tests/test_app.py -v -k reindex`
Expected: PASS（`test_admin_reindex_double_start_returns_409` は手動で `maintenance=True` をセットして 409 を確認する既存テスト。`begin_reindex` 経由でも同じ 409 になる。`test_admin_reindex_blocks_writes` も緑）

#### 1b. 同一 fact 並行 propose の重複レコードレース

背景: `tool_propose_promotion` は「重複チェック（`by_fact`）→ push プリコンディション（`rev-list` を `await asyncio.to_thread`）→ upsert」の順。await が重複チェックと upsert の間にあるため、同一 fact への並行 propose で両方が重複チェックをすり抜け 2 レコードできる。修正 = push プリコンディションを重複チェックより前に移し、「重複チェック→upsert」を event loop 上で await 無しの不可分区間にする。

- [ ] **Step 7: 失敗するテストを書く（並行 propose は 1 レコードに収束）**

`tests/test_app_promotion.py` に追記（`pctx` / `VALID_ARGS` は既存）:

```python
async def test_concurrent_propose_same_fact_creates_one_record(pctx):
    import asyncio
    svcs, backend = pctx
    add = await svcs.tool_add(**VALID_ARGS)
    fid = add["fact_id"]
    r1, r2 = await asyncio.gather(
        svcs.tool_propose_promotion(fid),
        svcs.tool_propose_promotion(fid),
    )
    # どちらか片方だけが proposed を返し、もう片方は重複拒否になる
    states = sorted([r1.get("state") or r1.get("error", ""),
                     r2.get("state") or r2.get("error", "")])
    assert "proposed" in [r1.get("state"), r2.get("state")]
    # 永続レコードは 1 件だけ（重複レコードが生まれない）
    assert len(svcs.promotion_store.by_fact(fid)) == 1
    # backend への PR 作成も 1 回だけ
    assert len(backend.created) == 1
```

- [ ] **Step 8: 失敗を確認**

Run: `uv run pytest tests/test_app_promotion.py::test_concurrent_propose_same_fact_creates_one_record -v`
Expected: FAIL（修正前は `by_fact` が 2 件・`backend.created` が 2 件になる）

- [ ] **Step 9: push プリコンディションを重複チェック前へ移動**

`src/plk_memory/app.py` の `tool_propose_promotion`（233-276 行）のうち、`ns` 判定の直後から upsert までを以下の順に組み替える（`ns` の `plk.domain.` 判定までは現状維持）:

```python
        ns = post.get("namespace")
        if not str(ns).startswith("plk.domain."):
            return {"error": f"昇格できるのは plk.domain.* のみ（現在: {ns}）"}
        # push 完了がプリコンディション（設計書 §5）。
        # ここで先に await（to_thread）を消化しておくことで、以降の
        # 「重複チェック → upsert」を event loop 上で await 無しの不可分区間にする
        # （同一 fact への並行 propose が重複レコードを作るレースの防止）。
        unpushed = (
            await asyncio.to_thread(self.store.git, "rev-list", "--count", "origin/main..HEAD")
        ).strip()
        if unpushed != "0":
            return {"error": f"未 push の commit が {unpushed} 件ある（push 完了後に再試行）"}
        # 既存の未処理昇格があれば再作成しない（ここから upsert まで await を挟まない）
        for existing in self.promotion_store.by_fact(fact_id):
            if existing.state in (PromotionState.proposed, PromotionState.approved):
                return {"error": "既に昇格リクエストが存在する", "promotion_id": existing.id}
        # domains/<d>/<file> -> shared/<file>（CI の check_promotion が要求する rename 形）
        import posixpath
        new_rel = f"{self.settings.knowledge_subdir}/shared/" + posixpath.basename(rel)
        pr = new_promotion(
            fact_id=fact_id, from_namespace=ns, old_path=rel, new_path=new_rel,
            branch=f"promote/{fact_id}", reason=reason,
        )
        self.promotion_store.upsert(pr)
```

（`create_pr` 呼び出し以降のロールバック処理は現状のまま。）

- [ ] **Step 10: 並行 propose テストと既存 propose テスト群が通ることを確認**

Run: `uv run pytest tests/test_app_promotion.py -v`
Expected: PASS（新規並行テスト＋既存 `test_propose_creates_promotion_and_pr`・`test_propose_is_idempotent_per_fact`・`test_propose_rolls_back_store_when_create_pr_fails` 等が緑）

- [ ] **Step 11: 全テスト緑を確認してコミット**

Run: `uv run pytest -q`
Expected: PASS（104 passed 前後・1 deselected）

```bash
git add src/plk_memory/sync.py src/plk_memory/app.py tests/test_sync.py tests/test_app_promotion.py
git commit -m "fix: reindex 連打の silent drop と並行 propose の重複レコードを修正

P2 最終レビュー持ち越しの並行性バグ 2 件:
- /admin/reindex: begin_reindex の atomic check-and-set でフラグ先行セット
- tool_propose_promotion: push プリコンディションを重複チェック前へ移し
  重複チェック→upsert を await 無しの不可分区間にした

Claude-Session: https://claude.ai/code/session_01BH2sda1uFhHN1W87V4v1nt"
```

---

### Task 2: 認証アダプタの実換装（自己発行 JWT ＋ローカル JWKS で JWTVerifier モードを起動）

**目的（設計書 §11）**: 静的 Bearer → FastMCP JWTVerifier の換装工数を実測する。既定は `auth_mode=bearer` のまま（Mac 運用継続）。JWT パスは dormant に追加し、ゴールデンテストで受理/拒否を自動検証、4 クライアント接続確認は手動 verify ステップ（工数を LESSONS.md へ）。外部アカウント（Auth0 等）は作らず、自己発行 RSA 鍵＋ローカル JWKS で完結させる。

**Files:**
- Modify: `src/plk_memory/settings.py:24-29`（認証設定キー追加）
- Modify: `src/plk_memory/auth.py`（`build_jwt_verifier`・jwt モードの current_client 導出）
- Modify: `src/plk_memory/mcp_tools.py:17-18`（`build_mcp` で auth 注入）
- Modify: `src/plk_memory/app.py`（`/.well-known/jwks.json` ルート）
- Create: `scripts/auth/__init__.py`, `scripts/auth/issue_jwt.py`
- Modify: `.env.example`
- Test: `tests/test_jwt_auth.py`（新規）

**Interfaces:**
- Consumes: `Settings`・`fastmcp.server.auth.providers.jwt.JWTVerifier(public_key=..., jwks_uri=..., issuer=..., audience=..., algorithm=...)`・`JWTVerifier.verify_token(token) -> AccessToken | None`・`RSAKeyPair.generate()` / `RSAKeyPair.create_token(subject, issuer, audience, kid, expires_in_seconds)` / `.public_key: str(PEM)` / `.private_key: str`
- Produces: `Settings.auth_mode: str`（`bearer`|`jwt`, 既定 `bearer`）・`Settings.jwt_issuer/jwt_audience/jwks_uri/jwt_public_key`・`auth.build_jwt_verifier(settings) -> JWTVerifier`・`auth.client_from_jwt(token) -> str | None`（sub 抽出）

**確認済み API（2026-07-03, fastmcp 3.4.2）**: `JWTVerifier.__init__(*, public_key=None, jwks_uri=None, issuer=None, audience=None, algorithm=None, ...)`・`verify_token(self, token) -> AccessToken | None`・`RSAKeyPair.public_key` は PEM 文字列・`create_token(subject, issuer, audience, scopes, expires_in_seconds, additional_claims, kid)`・`FastMCP.__init__` は `auth` パラメータを持つ。

- [ ] **Step 1: 認証設定キーを追加**

`src/plk_memory/settings.py` の `admin_token: str = ""`（29 行）の直後に追記:

```python
    # 認証モード（Phase 3: JWT 換装の実測用。既定 bearer のまま Mac 運用を継続する）
    auth_mode: str = "bearer"  # bearer | jwt
    jwt_issuer: str = "https://plk-memory.local/"
    jwt_audience: str = "plk-memory"
    # jwks_uri を設定するとその URI から公開鍵を取得（本番/ローカル JWKS 配信）。
    # 空なら jwt_public_key（PEM）を直接使う（テスト・オフライン検証）。
    jwks_uri: str = ""
    jwt_public_key: str = ""
```

- [ ] **Step 2: 失敗するゴールデンテストを書く（JWTVerifier の受理/拒否）**

`tests/test_jwt_auth.py`（新規）:

```python
import time

import pytest
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from plk_memory.auth import build_jwt_verifier, client_from_jwt
from plk_memory.settings import Settings

ISSUER = "https://plk-memory.local/"
AUDIENCE = "plk-memory"


@pytest.fixture
def keypair():
    return RSAKeyPair.generate()


def make_settings(keypair) -> Settings:
    return Settings(
        auth_mode="jwt", jwt_issuer=ISSUER, jwt_audience=AUDIENCE,
        jwt_public_key=keypair.public_key, _env_file=None,
    )


async def test_valid_token_is_accepted(keypair):
    verifier = build_jwt_verifier(make_settings(keypair))
    token = keypair.create_token(subject="claude-code", issuer=ISSUER, audience=AUDIENCE)
    access = await verifier.verify_token(token)
    assert access is not None


async def test_wrong_issuer_is_rejected(keypair):
    verifier = build_jwt_verifier(make_settings(keypair))
    token = keypair.create_token(subject="claude-code", issuer="https://evil.example/", audience=AUDIENCE)
    assert await verifier.verify_token(token) is None


async def test_wrong_audience_is_rejected(keypair):
    verifier = build_jwt_verifier(make_settings(keypair))
    token = keypair.create_token(subject="claude-code", issuer=ISSUER, audience="other-service")
    assert await verifier.verify_token(token) is None


async def test_expired_token_is_rejected(keypair):
    verifier = build_jwt_verifier(make_settings(keypair))
    token = keypair.create_token(
        subject="claude-code", issuer=ISSUER, audience=AUDIENCE, expires_in_seconds=-10,
    )
    assert await verifier.verify_token(token) is None


def test_client_from_jwt_extracts_sub(keypair):
    token = keypair.create_token(subject="codex", issuer=ISSUER, audience=AUDIENCE)
    assert client_from_jwt(token) == "codex"
```

- [ ] **Step 3: 失敗を確認**

Run: `uv run pytest tests/test_jwt_auth.py -v`
Expected: FAIL（`ImportError: cannot import name 'build_jwt_verifier'`）

- [ ] **Step 4: build_jwt_verifier と client_from_jwt を実装**

`src/plk_memory/auth.py` の末尾に追記（`from __future__ import annotations` は既存）:

```python
def build_jwt_verifier(settings: Settings):
    """設計書 §7 の逆輸入時 AuthProvider = FastMCP JWTVerifier。
    jwks_uri があれば JWKS 配信から公開鍵を取得（本番/Auth0 相当）。
    空なら jwt_public_key(PEM) を直接使う（テスト・オフライン検証）。"""
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    if settings.jwks_uri:
        return JWTVerifier(
            jwks_uri=settings.jwks_uri, issuer=settings.jwt_issuer,
            audience=settings.jwt_audience, algorithm="RS256",
        )
    return JWTVerifier(
        public_key=settings.jwt_public_key, issuer=settings.jwt_issuer,
        audience=settings.jwt_audience, algorithm="RS256",
    )


def client_from_jwt(token: str) -> str | None:
    """JWT の sub クレームを written_by 用の client 名として取り出す。
    署名検証は FastMCP の JWTVerifier が /mcp レイヤで行う（ここは同一トークンからの
    identity 導出のみ）。この二重処理自体が『written_by が Starlette ミドルウェアに
    結合している』という換装摩擦の実測対象（LESSONS.md 参照）。"""
    import jwt as pyjwt

    try:
        claims = pyjwt.decode(token, options={"verify_signature": False})
    except pyjwt.PyJWTError:
        return None
    sub = claims.get("sub")
    return str(sub) if sub else None
```

- [ ] **Step 5: BearerAuthMiddleware に jwt モードの current_client 導出を追加**

`src/plk_memory/auth.py` の `dispatch` の `/mcp` 分岐（31-35 行）を置換:

```python
        elif path.startswith("/mcp"):
            if self.settings.auth_mode == "jwt":
                # 署名検証は FastMCP JWTVerifier（/mcp レイヤ）が行う。
                # ここは verify 済み前提で sub から written_by を導出するだけ。
                client = client_from_jwt(token)
                if client is None:
                    return JSONResponse({"error": "invalid or missing JWT"}, status_code=401)
                current_client.set(client)
            else:
                client = self.settings.tokens.get(token)
                if client is None:
                    return JSONResponse({"error": "invalid or missing bearer token"}, status_code=401)
                current_client.set(client)
```

- [ ] **Step 6: build_mcp で auth を注入**

`src/plk_memory/mcp_tools.py:18` の `mcp = FastMCP("plk-memory")` を置換:

```python
    auth = None
    if services.settings.auth_mode == "jwt":
        from plk_memory.auth import build_jwt_verifier
        auth = build_jwt_verifier(services.settings)
    mcp = FastMCP("plk-memory", auth=auth)
```

- [ ] **Step 7: ローカル JWKS ルートを追加**

`src/plk_memory/app.py` の `/healthz` ルート（405-407 行）の直前に追記:

```python
    @app.get("/.well-known/jwks.json")
    async def jwks() -> dict:
        # ローカル JWKS 配信（jwt モードの JWTVerifier(jwks_uri=...) が取得する）。
        # jwt_public_key(PEM) から JWK を組み立てて返す。未設定時は 404。
        if not settings.jwt_public_key:
            raise HTTPException(status_code=404, detail="JWKS 未設定")
        from authlib.jose import JsonWebKey

        key = JsonWebKey.import_key(
            settings.jwt_public_key, {"kty": "RSA", "use": "sig", "alg": "RS256"}
        )
        return {"keys": [key.as_dict()]}
```

（`/.well-known` は `/admin` でも `/mcp` でもないため `BearerAuthMiddleware` を素通りする＝認証不要で公開鍵を配れる。これは正しい挙動。）

- [ ] **Step 8: 換装テストと全体の非回帰を確認**

Run: `uv run pytest tests/test_jwt_auth.py tests/test_auth.py -v`
Expected: PASS（jwt 受理/拒否 5 件＋既存 Bearer テスト 5 件。既定 `auth_mode=bearer` なので既存挙動は不変）

- [ ] **Step 9: 4 クライアント接続用の JWT/JWKS 発行スクリプトを作成**

`scripts/auth/__init__.py`（空ファイル）と `scripts/auth/issue_jwt.py`（新規）:

```python
"""自己発行 JWT ＋ローカル JWKS の生成（Phase 3 認証換装の 4 クライアント接続確認用）。

verify-and-adapt: RSAKeyPair / JsonWebKey の API は fastmcp 3.4.2 / authlib 1.7.2 で確認済み。
使い方:
    uv run python -m scripts.auth.issue_jwt
出力:
    ~/.plk/jwt/  … private.pem / public.pem / jwks.json / tokens.env（4 クライアント分）
戻し方（実測後）: PLK_AUTH_MODE を消す（既定 bearer に戻る）。鍵は破棄してよい。
"""

from __future__ import annotations

import json
from pathlib import Path

from authlib.jose import JsonWebKey
from fastmcp.server.auth.providers.jwt import RSAKeyPair

ISSUER = "https://plk-memory.local/"
AUDIENCE = "plk-memory"
CLIENTS = ["claude-code", "codex", "hermes", "custom-agent"]
OUT = Path.home() / ".plk" / "jwt"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pair = RSAKeyPair.generate()
    (OUT / "private.pem").write_text(pair.private_key, encoding="utf-8")
    (OUT / "public.pem").write_text(pair.public_key, encoding="utf-8")

    jwk = JsonWebKey.import_key(pair.public_key, {"kty": "RSA", "use": "sig", "alg": "RS256"})
    jwk_dict = jwk.as_dict()
    (OUT / "jwks.json").write_text(
        json.dumps({"keys": [jwk_dict]}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = []
    for client in CLIENTS:
        token = pair.create_token(
            subject=client, issuer=ISSUER, audience=AUDIENCE,
            kid=jwk_dict.get("kid"), expires_in_seconds=30 * 24 * 3600,
        )
        lines.append(f"# {client}\nPLK_JWT_{client.replace('-', '_').upper()}={token}")
    (OUT / "tokens.env").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"生成完了: {OUT}")
    print("サーバー起動（jwt モード）例:")
    print(f'  PLK_AUTH_MODE=jwt PLK_JWKS_URI=http://127.0.0.1:8735/.well-known/jwks.json \\')
    print(f'  PLK_JWT_PUBLIC_KEY="$(cat {OUT}/public.pem)" \\')
    print("  uv run uvicorn plk_memory.app:create_app --factory --host 127.0.0.1 --port 8735")
    print(f"各クライアントの Bearer には {OUT}/tokens.env の JWT を使う")


if __name__ == "__main__":
    main()
```

- [ ] **Step 10: .env.example に認証モードのコメントを追記**

`.env.example` の末尾に追記:

```bash

# 認証モード（既定 bearer）。Phase 3 の JWT 換装実測時のみ jwt にする。
# PLK_AUTH_MODE=jwt
# PLK_JWKS_URI=http://127.0.0.1:8735/.well-known/jwks.json   # ローカル JWKS 配信
# PLK_JWT_ISSUER=https://plk-memory.local/
# PLK_JWT_AUDIENCE=plk-memory
# JWT/JWKS の発行: uv run python -m scripts.auth.issue_jwt
```

- [ ] **Step 11: 手動 verify（4 クライアント接続確認・工数実測）— dry-run 手順**

これは自動テストではなく実測ステップ。以下を実行して所要時間（壁時計）と変更行数を記録し、Task 5（LESSONS.md）の「認証換装の実測」節に転記する:

1. `uv run python -m scripts.auth.issue_jwt` で鍵・JWKS・4 トークンを生成。
2. `PLK_AUTH_MODE=jwt PLK_JWKS_URI=http://127.0.0.1:8735/.well-known/jwks.json PLK_JWT_PUBLIC_KEY="$(cat ~/.plk/jwt/public.pem)"` 付きでサーバー起動。
3. `curl -s http://127.0.0.1:8735/.well-known/jwks.json` で JWK が返ることを確認。
4. `~/.plk/jwt/tokens.env` の各 JWT を Bearer にして 4 クライアント（Claude Code / Codex / Hermes / Agent SDK の `examples/sdk_client_check.py`）から `plk_search` を 1 回ずつ実行し、200 応答と `usage.jsonl` に written_by（=sub）が記録されることを確認。
5. `PLK_AUTH_MODE` を外して再起動し、静的 Bearer に戻る（既定回帰）ことを確認。
6. 記録項目: (a) 換装に要した実作業時間 (b) 追加/変更した行数 (c) 詰まった点（例: written_by が Starlette ミドルウェア結合／JWKS の kid 一致／audience 設定）。

- [ ] **Step 12: 全テスト緑を確認してコミット**

Run: `uv run pytest -q`
Expected: PASS（既定 bearer で全緑・jwt テストは明示 Settings 注入で緑）

```bash
git add src/plk_memory/settings.py src/plk_memory/auth.py src/plk_memory/mcp_tools.py \
        src/plk_memory/app.py scripts/auth tests/test_jwt_auth.py .env.example
git commit -m "feat: JWT/JWKS 認証アダプタを dormant 追加（既定 bearer・換装工数実測用）

設計書 §11 の認証アダプタ実換装 1 回。build_jwt_verifier + ローカル JWKS ルート
+ 発行スクリプト。auth_mode=jwt で FastMCP JWTVerifier を起動、4 クライアント接続確認後
静的 Bearer に戻す。外部アカウントは作らず自己発行 RSA 鍵で完結。

Claude-Session: https://claude.ai/code/session_01BH2sda1uFhHN1W87V4v1nt"
```

---

### Task 3: Slack 承認アダプタのスタブ＋ゴールデンテスト

**目的（設計書 §2・§10）**: `PromotionBackend` Protocol を GitHub 以外の実装（Slack Block Kit）で一度通し、境界の実在を証明する。Block Kit ペイロード生成と承認コールバック→transition の「形だけ」。実 Slack 接続なし・slack-bolt 依存も追加しない（ペイロードは素の dict）。

**Files:**
- Create: `src/plk_memory/slack_promotion.py`
- Test: `tests/test_slack_promotion.py`（新規）

**Interfaces:**
- Consumes: `PromotionBackend` Protocol（`github_promotion.py`: `async create_pr(pr) -> tuple[int,str]`・`async merged_state(pr_number) -> str`）・`PromotionRequest`（`promotions.py`: `.id/.fact_id/.from_namespace/.to_namespace/.old_path/.new_path`）・`transition(pr, PromotionState) -> PromotionRequest`
- Produces: `SlackPromotionBackend`（Protocol 準拠）・`build_approval_blocks(pr) -> list[dict]`（Block Kit）・`parse_action_callback(payload: dict) -> tuple[str, str]`（`(promotion_id, "MERGED"|"CLOSED")`）

- [ ] **Step 1: 失敗するゴールデンテストを書く**

`tests/test_slack_promotion.py`（新規）:

```python
import pytest

from plk_memory.promotions import PromotionState, new_promotion, transition
from plk_memory.slack_promotion import (
    SlackPromotionBackend,
    build_approval_blocks,
    parse_action_callback,
)


def make_pr():
    return new_promotion(
        fact_id="01JZC2V7E8B3F4G5H6J7K8M9N0",
        from_namespace="plk.domain.tax",
        old_path="knowledge/domains/tax/x.md",
        new_path="knowledge/shared/x.md",
        branch="promote/01JZC2V7E8B3F4G5H6J7K8M9N0",
    )


def test_build_approval_blocks_golden():
    pr = make_pr()
    blocks = build_approval_blocks(pr)
    assert blocks == [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*plk-memory 昇格リクエスト*\n"
                    "・fact_id: `01JZC2V7E8B3F4G5H6J7K8M9N0`\n"
                    "・from: `plk.domain.tax` → to: `plk.shared`\n"
                    "・rename: `knowledge/domains/tax/x.md` → `knowledge/shared/x.md`"
                ),
            },
        },
        {
            "type": "actions",
            "block_id": pr.id,
            "elements": [
                {
                    "type": "button",
                    "action_id": "plk_promote_approve",
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "承認"},
                    "value": pr.id,
                },
                {
                    "type": "button",
                    "action_id": "plk_promote_reject",
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "却下"},
                    "value": pr.id,
                },
            ],
        },
    ]


def test_parse_approve_callback():
    pr = make_pr()
    payload = {
        "actions": [{"action_id": "plk_promote_approve", "value": pr.id}],
    }
    assert parse_action_callback(payload) == (pr.id, "MERGED")


def test_parse_reject_callback():
    pr = make_pr()
    payload = {"actions": [{"action_id": "plk_promote_reject", "value": pr.id}]}
    assert parse_action_callback(payload) == (pr.id, "CLOSED")


async def test_backend_conforms_to_protocol_and_drives_transition():
    pr = make_pr()
    backend = SlackPromotionBackend()
    number, url = await backend.create_pr(pr)         # Protocol: create_pr
    assert isinstance(number, int) and url.startswith("https://")
    # 承認コールバックが来るまでは未確定（OPEN）
    assert await backend.merged_state(number) == "OPEN"
    # Slack 承認ボタン押下を模した callback → 状態機械を実際に 1 回通す
    pid, mapped = parse_action_callback(
        {"actions": [{"action_id": "plk_promote_approve", "value": pr.id}]}
    )
    backend.record_decision(number, mapped)
    assert await backend.merged_state(number) == "MERGED"
    # transition が proposed → applied を許可する（境界が状態機械に接続している）
    applied = transition(pr, PromotionState.applied)
    assert applied.state is PromotionState.applied
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_slack_promotion.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'plk_memory.slack_promotion'`）

- [ ] **Step 3: SlackPromotionBackend スタブを実装**

`src/plk_memory/slack_promotion.py`（新規）:

```python
"""Slack 承認アダプタのスタブ（設計書 §2・§10: 境界の実在を一度通す）。

PromotionBackend Protocol の非 GitHub 実装。Block Kit ペイロード生成と
承認コールバック → transition の『形だけ』を提供する。実 Slack 接続・slack-bolt 依存はない。
組織展開 逆輸入時にここへ実 chat.postMessage / interactivity エンドポイントを差し込む。
"""

from __future__ import annotations

from plk_memory.promotions import PromotionRequest

ACTION_APPROVE = "plk_promote_approve"
ACTION_REJECT = "plk_promote_reject"


def build_approval_blocks(pr: PromotionRequest) -> list[dict]:
    """昇格リクエストの承認メッセージ（Slack Block Kit）。
    button の value に promotion id を載せ、interactivity callback で回収する。"""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*plk-memory 昇格リクエスト*\n"
                    f"・fact_id: `{pr.fact_id}`\n"
                    f"・from: `{pr.from_namespace}` → to: `{pr.to_namespace}`\n"
                    f"・rename: `{pr.old_path}` → `{pr.new_path}`"
                ),
            },
        },
        {
            "type": "actions",
            "block_id": pr.id,
            "elements": [
                {
                    "type": "button",
                    "action_id": ACTION_APPROVE,
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "承認"},
                    "value": pr.id,
                },
                {
                    "type": "button",
                    "action_id": ACTION_REJECT,
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "却下"},
                    "value": pr.id,
                },
            ],
        },
    ]


def parse_action_callback(payload: dict) -> tuple[str, str]:
    """Slack interactivity callback を (promotion_id, merged_state) に写像する。
    approve → MERGED / reject → CLOSED（poll_promotions が解釈する merged_state 語彙に合わせる）。"""
    action = payload["actions"][0]
    promotion_id = action["value"]
    if action["action_id"] == ACTION_APPROVE:
        return promotion_id, "MERGED"
    if action["action_id"] == ACTION_REJECT:
        return promotion_id, "CLOSED"
    raise ValueError(f"未知の action_id: {action['action_id']}")


class SlackPromotionBackend:
    """PromotionBackend Protocol（create_pr / merged_state）の Slack 実装スケルトン。

    実 Slack 接続はしない。create_pr = 承認メッセージ投稿の代わりに Block Kit を記録し
    合成 (message_id, permalink) を返す。merged_state = record_decision で記録された
    承認/却下を返す（実運用では interactivity エンドポイントが record_decision を呼ぶ）。
    """

    def __init__(self) -> None:
        self.posted: dict[int, list[dict]] = {}   # message_id -> blocks
        self._decisions: dict[int, str] = {}       # message_id -> "MERGED"|"CLOSED"
        self._next_id = 1000

    async def create_pr(self, pr: PromotionRequest) -> tuple[int, str]:
        self._next_id += 1
        message_id = self._next_id
        self.posted[message_id] = build_approval_blocks(pr)
        # 実運用では chat.postMessage の permalink。スタブでは合成 URL。
        return message_id, f"https://slack.example/archives/C000/p{message_id}"

    def record_decision(self, message_id: int, state: str) -> None:
        """interactivity callback → merged_state へ橋渡し（承認/却下の記録）。"""
        self._decisions[message_id] = state

    async def merged_state(self, message_id: int) -> str:
        return self._decisions.get(message_id, "OPEN")
```

- [ ] **Step 4: ゴールデンテストが通ることを確認**

Run: `uv run pytest tests/test_slack_promotion.py -v`
Expected: PASS（4 テスト全緑）

- [ ] **Step 5: Protocol 構造適合を型チェックで確認**

Run: `uv run python -c "from plk_memory.slack_promotion import SlackPromotionBackend; from plk_memory.github_promotion import PromotionBackend; b: PromotionBackend = SlackPromotionBackend(); print('conforms')"`
Expected: 標準出力に `conforms`（構造的部分型として `PromotionBackend` に代入できる）

- [ ] **Step 6: 全テスト緑を確認してコミット**

Run: `uv run pytest -q`
Expected: PASS

```bash
git add src/plk_memory/slack_promotion.py tests/test_slack_promotion.py
git commit -m "feat: Slack 承認アダプタのスタブ＋ゴールデンテスト

設計書 §10: PromotionBackend Protocol を非 GitHub 実装（Block Kit ペイロード生成・
承認コールバック→transition）で一度通し、境界の実在を証明する。実 Slack 接続なし。

Claude-Session: https://claude.ai/code/session_01BH2sda1uFhHN1W87V4v1nt"
```

---

### Task 4: 移行ガイド docs/MIGRATION.md

**目的（設計書 §10・§11）**: 組織展開 が半日で stg に立てるための手順＋差分表。実装済みの設定キー・ポート境界に紐付けた具体値で書く（抽象論を書かない）。

**Files:**
- Create: `docs/MIGRATION.md`

- [ ] **Step 1: 参照先の実在を確認（dry-run 前提の事実固め）**

差分表の各行が指す設定キー／不変条件が現行コードに実在することを確認する:

Run: `uv run python -c "from plk_memory.settings import Settings; s=Settings(_env_file=None); print(s.auth_mode, s.group_mode, s.llm_provider, s.embedder_model, s.ingest_mode)"`
Expected: `bearer single openai-compatible bge-m3 episode`

Run: `grep -n "group_mode\|per-namespace\|validate_group_id\|driver=\|workers>1\|AnotherInstanceRunning" src/plk_memory/*.py`
Expected: `group_mode` は `settings.py`、per-namespace 分岐は `settings.py` の `group_for`/`all_groups`、driver スレッディング申し送りは Phase 1 レポート由来（コード未実装）を確認できること。

- [ ] **Step 2: MIGRATION.md を作成**

`docs/MIGRATION.md`（新規）:

```markdown
# plk-memory 移行ガイド（Byteflare Mac 版 → 組織展開 stg）

対象: 組織展開 の担当者が半日で staging に plk-memory を立てるための手順と、
Byteflare 固有の前提を 組織展開 前提へ置き換える差分。設計書 §10/§11 の逆輸入マッピングの実装版。

## 0. 前提の違い（要点）

Byteflare 版は「1 人法人・全クライアントが 1 台の Mac・完全ローカル LLM・GitHub PR 承認・
静的 Bearer・単一レプリカ常駐」で最適化されている。組織展開 stg では少なくとも
「複数人・ECS 複数レプリカ・クラウド LLM/embedder・Slack 承認・OIDC 認証・部署別 namespace」
へ置き換える。置き換えは全て設定または 1 ファイルの差し込みで済むようポート境界化してある。

## 1. 半日セットアップ手順（stg）

1. FalkorDB を Docker で起動（`docker compose up -d falkordb`）か、マネージド Redis+FalkorDB モジュール。
2. `.env` を stg 用に作成（下表の差分を反映）。`uv sync`。
3. データリポジトリ（知識リポジトリ）の stg 用 clone URL を `PLK_DATA_REPO_URL` に設定。
4. LLM/embedder をクラウドに向ける（下表）。
5. `auth_mode=jwt` ＋ IdP の JWKS URI を設定（下表）。
6. 起動して `/healthz` → `/admin/sync` → `plk_search` の順に疎通確認。
7. 昇格フローを 1 往復（propose → 承認 → applied → shared ingest）通す。

## 2. 差分表（Byteflare → 組織展開）

| 論点 | Byteflare 版（現状） | 組織展開 stg での置き換え | 触る場所 |
|---|---|---|---|
| 認証 | 静的 Bearer（`auth_mode=bearer`, `PLK_TOKENS`） | OIDC/Auth0 の JWTVerifier（`auth_mode=jwt`, `PLK_JWKS_URI`, `PLK_JWT_ISSUER`, `PLK_JWT_AUDIENCE`） | `settings.py`・`auth.build_jwt_verifier`（実装済み・Phase 3 で実換装検証）。written_by は JWT `sub` から導出する結合が残る点に注意（下記 §3） |
| 実行形態 | launchd 単一常駐（Mac） | ECS 化。ただし **writer 単一レプリカ必須**（`flock` + `asyncio.Lock`）。多レプリカは WriteSerializer を破る | 代替: Aurora advisory lock / SQS 単一コンシューマ。移行の不変条件（§4） |
| Git 資格情報 | Mac の既存 `gh auth`（PR 用と push 用が同一） | **PAT 2 分離**: push 用 fine-grained PAT（対象リポ限定・`contents:write` のみ）と PR 作成用を分離 | `github_promotion.py` の `gh` 呼び出し／push 用資格情報 |
| グラフ検索の並行性 | 単一 group・`op_lock` で route→操作を直列化 | **`driver=` 引数スレッディングへの移行が required**（多 group・高並行で search が ingest 中ブロックされる。Phase 1 T13 実測の申し送り） | `graphindex.py` の `_route_group`／graphiti driver 渡し方 |
| 構築 LLM | ローカル Ollama `gpt-oss:20b`（`llm_provider=openai-compatible`, $0・壁時計のみ） | クラウド化: `llm_provider=anthropic` + `claude-haiku-4-5`（structured output 第一級）。`ANTHROPIC_API_KEY` は env export（`.env` 禁止） | `settings.py`（`llm_provider`/`anthropic_model`）・`graphindex.py` |
| embedder | ローカル Ollama `bge-m3`（1024 次元） | クラウド化: Voyage/Gemini/OpenAI。次元（`embedding_dim`）と `embedder_base_url`/`embedder_model`/`embedder_api_key` を合わせる。**次元変更時は全 reindex 必須** | `settings.py`・`graphindex.py` |
| group セマンティクス | FalkorDB（group = 物理別グラフ）。単一 group `plk-main` へ畳み込み | Neo4j/Neptune は group = プロパティフィルタ。物理分離前提のコードは差異に注意 | `graphindex.py`・`GraphIndex` ポート |
| namespace/group | `group_mode=single`（全 namespace → `plk-main`＋`plk-quarantine`） | `group_mode=per-namespace`（部署分離 1:1）。`plk-domain-<d>`/`plk-shared`/`plk-quarantine` | `settings.py` の `group_for`/`all_groups`（実装済み・切替は 1 行） |
| group_id 表記 | **ハイフン区切り**（`plk-main`）。namespace はドット（`plk.domain.tax`） | 同一制約が Neo4j でも有効（`validate_group_id` は `^[a-zA-Z0-9_-]+$`）。ドットを group_id に使わない | `settings.py`（変更不要・逆輸入時の落とし穴として明記） |
| 承認 UI | GitHub PR（`GitHubPromotionBackend`） | Slack Block Kit（`SlackPromotionBackend` スケルトンに実 chat.postMessage / interactivity を差し込む）。状態機械は API 側（`promotions.py`）なので UI 差し替えで済む | `slack_promotion.py`（スタブ実装済み） |
| ログ | JSONL ローカル FS（`LogSink`） | CloudWatch Logs / Aurora。`LogSink` IF に実体を差す | `usage_log.py` |
| 公開面 | 127.0.0.1 bind（Tailscale 内） | ALB + WAF。実ホスト名 bind 時は DNS リバインディング allowlist（`PLK_ALLOWED_HOSTS`）必須 | `settings.py`（`allowed_hosts`）・`app.py`（TrustedHostMiddleware） |

## 3. 認証換装の実測（Phase 3 で 1 回実施）

`auth.build_jwt_verifier` は `jwks_uri`（本番 IdP）と `jwt_public_key`（オフライン）の両対応。
Byteflare では自己発行 RSA 鍵＋ローカル JWKS（`scripts/auth/issue_jwt.py`）で JWTVerifier モードを
起動し 4 クライアント接続を確認した。実測工数と摩擦点は `docs/LESSONS.md`「認証換装の実測」に記載。
組織展開 では `jwks_uri` を IdP の JWKS エンドポイントに向けるだけで公開鍵取得は成立する。
**残る摩擦**: written_by の client 名を JWT `sub` から Starlette ミドルウェアで導出しているため、
IdP の sub/claim 設計（`user:x` / `agent:y` の principal 形式）とマッピングを合わせる必要がある。

## 4. 移行の不変条件（破ると壊れる）

- **writer 単一レプリカ必須**。ECS で複数レプリカにすると `flock`＋`asyncio.Lock` の WriteSerializer が
  破れ、SoT（Git remote main）への並行 push でリポジトリが壊れる。レプリカ数は 1、または
  Aurora advisory lock / SQS 単一コンシューマへ writer を外出しする。
- **written_by はサーバー導出**（クライアント申告無視）・**API の source_type 上限は agent**。
- **shared への直接書き込み禁止**（昇格経由のみ）。`shared/` 変更は approving-review 付き merged PR 由来を検証。
- **全 MCP ツールは 60 秒以内応答**（Codex `tool_timeout`）。`/healthz` は即応。
```

- [ ] **Step 3: 差分表の設定キーが実在することを dry-run 検証**

Run: `uv run python -c "from plk_memory.settings import Settings; s=Settings(_env_file=None); [getattr(s,k) for k in ['auth_mode','jwks_uri','jwt_issuer','jwt_audience','group_mode','llm_provider','anthropic_model','embedder_model','embedding_dim','allowed_hosts']]; print('all settings keys exist')"`
Expected: `all settings keys exist`（MIGRATION.md が参照する全設定キーが Settings に存在）

- [ ] **Step 4: コミット**

```bash
git add docs/MIGRATION.md
git commit -m "docs: 組織展開 移行ガイド（半日 stg 立ち上げ手順＋差分表）

設計書 §10/§11 の逆輸入マッピングを実装済み設定キー・ポート境界に紐付けた具体形で文書化。

Claude-Session: https://claude.ai/code/session_01BH2sda1uFhHN1W87V4v1nt"
```

---

### Task 5: 運用知見レポート docs/LESSONS.md（逆輸入の本体資産）

**目的（設計書 §10・§14）**: 発見バグ・実測値・「23 件規模では素の埋め込みで十分＝グラフ層凍結判断」・設計変更履歴・認証換装の実測をまとめる。これが逆輸入の本体。数値は Phase 1 評価レポート（`agent-organization/reports/phase1-eval-report.md`）と一致させる。

**Files:**
- Create: `docs/LESSONS.md`

- [ ] **Step 1: cited 数値・commit の実在を確認（dry-run）**

Run: `git -C /Users/masahiro/dev/byteflare-co/plk-memory log --oneline | grep -E "b5f88df|73627d2|79506c9|d823b13" && echo "cited commits exist"`
Expected: 4 commit 全てが log に存在し `cited commits exist` を表示。

評価数値（Phase 1 レポートと突き合わせ・転記時に一致させる）: embed 素 20/20 MRR1.000 / graph(triplet) 20/20 MRR1.000 / graph(episode) 16/20 MRR0.612 / rg 0/20 / episode 280〜302 秒/件 / triplet 126〜131 秒/件 / コーパス 23 件（active 22・invalidated 1）。

- [ ] **Step 2: LESSONS.md を作成**

`docs/LESSONS.md`（新規）:

```markdown
# plk-memory 運用知見レポート（Phase 0〜3 の実測と判断）

逆輸入の本体資産。Byteflare パイロット（1 人法人・完全ローカル LLM・23 件コーパス）で
実測したバグ・数値・設計判断を、組織展開 が同じ轍を踏まないよう記録する。
数値の一次ソースは `agent-organization/reports/phase1-eval-report.md`。

## 1. 最大の判断: 23 件規模では素の埋め込みで十分＝グラフ層は凍結候補

- **素の埋め込み検索（bge-m3 cosine top5）が 20/20・MRR 1.000**（全て rank1）。
- graph(triplet) も 20/20・MRR 1.000 だが、triplet の fact テキストは statement そのもの＝
  **実質「statement 埋め込み＋RRF」であり、グラフ構造由来の付加価値ではない**。
- graph(episode) は 16/20・MRR 0.612。ローカル 20B のエンティティ抽出（英語混じり・汎用語化）を
  挟むぶん**ベースラインに明確に負ける**。
- ripgrep 字句一致は 0/20（日本語口語クエリは空白を含まず 1 クエリ＝1 トークンになり文全体一致しない）。
- **結論**: 小コーパス（〜50 件）では graphiti を使う積極的理由が検索精度から出ていない。
  グラフ側にしかない機能価値（invalidated の索引除外・group 分離・履歴）は plk 側の仕組みで
  担保されており、embed ベースラインでも active のみ索引にすれば同挙動になる。
  **撤退ライン到達時はグラフ層を凍結し、Git 規約＋CI＋grep/埋め込み読み口のみで運用継続**する
  （Phase 0 成果はそれ自体で残る）。マルチホップ・時間推論・50 件以上での再評価が次の判断材料。

## 2. 発見バグ 6 件

1. **FalkorDriver の group_id グラフルーティング（Phase 1 T13）**: graphiti-core 0.29.2 の
   FalkorDriver は group ごとに別グラフだが、driver 参照を group 用グラフへ付け替えるのは
   `add_episode` のみ。`search`（単一 group）・`add_triplet`・`remove_episode`・`clear_data` は
   付け替えず、新規プロセスからの検索が空の `default_db` を読んで**恒久 0 ヒット**になっていた。
   → `GraphIndex._route_group()` で全操作前に両参照を付け替え、`asyncio.Lock`(op_lock) で
   route→操作を直列化。**申し送り**: 直列化は多 group・高並行でボトルネック。組織展開 では
   `driver=` 引数スレッディングへの移行が required。
2. **triplet モードの検索帰属バグ（T14）**: state に `add_triplet` が返す edge uuid を格納するが、
   `_resolve_hits` が `edge.episodes`（triplet では空）のみで帰属していたため正解エッジが rank1 でも
   全ヒットが破棄され **graph(triplet) が恒久 0/20**。→ `edge.uuid` 経由の帰属を追加（commit `79506c9`・
   回帰テスト付き）。修正後 20/20。
3. **triplet ≠ LLM フリー（T13）**: `add_triplet` は新規ノードごとに `resolve_extracted_nodes`(LLM dedupe)
   を呼ぶ。「triplet なら LLM 呼び出しなし」の想定は不成立で、ローカル 20B で 126〜131 秒/件
   （episode 比約 2.2 倍速というだけ）。
4. **reindex 連打の silent drop（P2→Phase 3 T1 で修正）**: `/admin/reindex` がフラグを背景タスク
   実行時にしか立てないため、連打の 2 件目が check をすり抜け両方 200 'started' を返し 2 件目が
   silent drop。→ `begin_reindex` の atomic check-and-set でルート側フラグ先行セット。
5. **同一 fact 並行 propose の重複レコード（P2→Phase 3 T1 で修正）**: push プリコンディションの await が
   重複チェックと upsert の間にあり、並行 propose で 2 レコード。→ push プリコンディションを重複
   チェック前へ移し「重複チェック→upsert」を await 無しの不可分区間に。
6. **frontmatter 往復正規化による本文破壊 / PR 本文 HTML 除去の過剰マッチ（P2 live）**:
   (a) `frontmatter` の dump が本文表記を正規化して差分を膨らませたため、昇格ブランチの
   namespace 書き換えを**外科的 1 行置換**へ変更（commit `b5f88df`）。(b) PR 本文の HTML 除去正規表現
   `[<>]` 一括除去が平文の `->` や `A > B` の `>` まで潰して rename 行が化けたため、`<[^>]*>`
   （タグの組のみ）へ修正（commit `73627d2`）。

（付随的な narrow edge: PR URL パース失敗の number=0 silent 化け〔P2 T5 で例外化〕・merge-base の
非 rewrite 失敗が HistoryRewritten に化ける〔P1 T4〕も検出・対処済み。）

## 3. ingest コスト実測（完全ローカル・$0・壁時計のみ）

| モード | 秒/件 | 23 件総時間 | 備考 |
|---|---|---|---|
| episode | 280〜302 | 約 1 時間47分〜1時間56分 | ローカル gpt-oss:20b + bge-m3, SEMAPHORE_LIMIT=2 |
| triplet | 126〜131 | 約 48〜50 分 | episode の約 2.2 倍速。ただし LLM フリーではない |
| episode + クラウド Haiku（推定） | 10〜30 | — | 未実測の参考値 |

- **API 費用 $0**（完全ローカル構成・ユーザー決定）。制約は金額でなく壁時計時間。
- 全再構築は夜間ジョブ前提。triplet モードならほぼゼロコスト（LLM dedupe ぶんの時間は残る）。

## 4. 設計変更履歴（なぜ今の形か）

- **昇格 PR の CI チェック: R100（rename 100%・内容変更なし）→ namespace 1 行差分許容**（2026-07-02）。
  当初は「rename のみ・内容差分ゼロ」を要求したが、namespace↔パス一致チェックと構造的に両立不能
  （昇格は `plk.domain.<d>` → `plk.shared` の namespace 行書き換えを伴うため）と Phase 0 最終レビューで
  判明。「rename ＋ frontmatter の `namespace:` 行 1 行のみの差分」を許容する形へ確定。
- **EC2 昇格の延期**（2026-07-03）。既存の小規模 EC2 は t4g.small 2GiB でローカル LLM が載らず、全
  クライアントが 1 台の Mac 上にあるため EC2 化の実益が薄いと判明。Phase 2 は Mac 常駐のまま機能実装し、
  EC2 移行は n8n 連携 or 組織展開 逆輸入直前に実施する方針へ変更。
- **group_id ハイフン制約**（Phase 1 T6）。graphiti の `validate_group_id` が `^[a-zA-Z0-9_-]+$` のみ
  許可しドットを拒否するため、namespace はドット区切り（`plk.domain.tax`）のまま group_id だけ
  ハイフン区切り（`plk-domain-tax`）に分離。逆輸入時の落とし穴。
- **ingest 既定は episode だが triplet≒embed ベースライン**。既定モードの最終確定は精度・壁時計・
  逆輸入先の LLM 予算で判断する（§1 の凍結判断と連動）。

## 5. 認証換装の実測（Phase 3・静的 Bearer → JWTVerifier）

自己発行 RSA 鍵＋ローカル JWKS（`scripts/auth/issue_jwt.py`）で FastMCP JWTVerifier モードを起動し、
4 クライアント（Claude Code / Codex / Hermes / Agent SDK）から接続確認した実測。

- **実作業時間**: （Task 2 Step 11 の記録を転記）
- **変更/追加行数**: （同上。build_jwt_verifier + JWKS ルート + ミドルウェア分岐 + 発行スクリプト）
- **詰まった点**: written_by の client 名が Starlette ミドルウェアに結合しており、JWT `sub` からの
  導出を追加する必要があった（`auth.client_from_jwt`）。JWKS の `kid` 一致・`audience` 設定・
  ローカル JWKS 配信（`/.well-known/jwks.json`）の 3 点は設定で完結。
- **戻し方**: `PLK_AUTH_MODE` を外すと既定 bearer に回帰。鍵は破棄。Mac 運用は静的 Bearer を継続。
- **組織展開 への含意**: `jwks_uri` を IdP に向けるだけで公開鍵取得は成立。残る作業は IdP の
  sub/claim 設計（principal 形式 `user:x`/`agent:y`）と written_by マッピングの整合のみ。

## 6. 検証されていないもの（false green 対策・組織展開 側 PoC の担当）

graph-primary モード・Graphiti テンポラル機構（時点クエリ・矛盾自動検出）・namespace→group 1:1 の
実運用・マルチテナント/RBAC/Auth0 運用・昇格の人間側承認実効性・組織規模のインジェクション攻撃面・
グラフ規模のコスト外挿・単一 writer 前提の破れ（ECS 多レプリカ）。これらは本パイロットで一度も
踏んでいない。逆輸入時に新規検証すること。
```

- [ ] **Step 3: Task 2 の実測値を §5 に転記**

Task 2 Step 11 で記録した実作業時間・変更行数・詰まった点を `docs/LESSONS.md` の §5 の該当行（`（Task 2 Step 11 の記録を転記）`）に埋める。転記後、プレースホルダ文字列が残っていないことを確認:

Run: `grep -n "転記" docs/LESSONS.md || echo "no placeholders left"`
Expected: `no placeholders left`

- [ ] **Step 4: 評価数値が Phase 1 レポートと一致することを dry-run 検証**

Run: `grep -E "20/20|16/20|0.612|302|130" /Users/masahiro/dev/byteflare-co/agent-organization/reports/phase1-eval-report.md | head`
Expected: LESSONS.md に転記した数値（20/20・16/20・MRR 0.612・302・130 前後）が一次レポートに存在する。

- [ ] **Step 5: コミット**

```bash
git add docs/LESSONS.md
git commit -m "docs: 運用知見レポート（発見バグ6件・実測値・グラフ層凍結判断・設計変更履歴）

設計書 §10 の逆輸入本体資産。Phase 1 評価レポートの数値と一致。認証換装の実測を含む。

Claude-Session: https://claude.ai/code/session_01BH2sda1uFhHN1W87V4v1nt"
```

---

### Task 6: README 総仕上げ・DISTRIBUTION.md 実態更新・UI auth 強化の EC2 前必須注記

**目的**: 新規参加者が全体像を掴める README にし、P2 持ち越しの DISTRIBUTION.md 実態更新と UI auth 強化の README §7 注記（実装はしない・注記のみ）を入れる。

**Files:**
- Modify: `README.md`（冒頭に全体像・§7 に UI auth 強化・docs/ への導線）
- Modify: `clients/DISTRIBUTION.md`（動線 3 ファイル配布済みの実態へ）

- [ ] **Step 1: README 冒頭に全体像セクションを追加**

`README.md:3`（`PLK メモリ基盤 — ...` の行）の直後に追記:

```markdown

## 全体像（新規参加者向け）

plk-memory は **Git を SoT（真実の源）とし、graphiti/FalkorDB を再構築可能な派生索引**とする
組織メモリの MCP サーバー。エージェント（Claude Code / Codex / Hermes / 自作）が `plk_search` で
過去の知見を引き、`plk_add` で書き、`plk_propose_promotion` でドメイン知見を全社共有（`shared/`）へ
昇格させる。

- **データの実体**: `agent-organization` リポジトリの `knowledge/`（1 ファクト 1 markdown ファイル）。
- **アーキテクチャ / 設計判断**: `specs/`（設計書）を参照。
- **逆輸入（組織展開 展開）**: 移行手順は `docs/MIGRATION.md`、実測・判断は `docs/LESSONS.md`。
- **ポート境界**: FactStore(Git) / GraphIndex(graphiti) / WriteSerializer(flock) / PromotionBackend
  (GitHub PR・Slack スタブ) / AuthProvider(Bearer・JWT) / LogSink(JSONL)。各境界は設定または
  1 ファイルの差し込みで別実装へ交換できる。
- **クライアント接続**: `clients/` の接続テンプレートと検索動線。
```

- [ ] **Step 2: README §7（EC2/組織展開 持ち越し注記）に UI auth 強化を追記**

`README.md` の §⑧-7（`7. **EC2/組織展開 期への持ち越し注記...`）の項目に、UI auth 強化を EC2 前必須として追記する。該当の段落末尾に以下を追加:

```markdown

   **UI auth の EC2 前必須強化（P2 最終レビューの standing condition・本 Phase では実装しない注記のみ）**:
   read 専用 Web UI は現在 localhost 前提で許容している弱点がある — (a) cookie/パスワード比較が
   非定数時間、(b) cookie トークンが静的、(c) ログインのレート制限なし。127.0.0.1 bind の間は許容だが、
   **EC2/Tailscale 公開前に**定数時間比較・per-session の cookie トークン・ログインのレート制限を
   実装することを必須条件とする。
```

- [ ] **Step 3: DISTRIBUTION.md を配布済みの実態へ更新**

`clients/DISTRIBUTION.md` の配布状況テーブル（17-22 行）を、Phase 2 T10 で「動線 3 ファイルが配布済み」に
なった実態へ更新する。Agent SDK 行はスクリプト内配布済みのまま、Claude Code / Codex / Hermes 行の
状態を実配布状況に合わせる。まず現状の実配布状況を事実確認:

Run: `ls -la ~/.claude/CLAUDE.md ~/.codex/AGENTS.md 2>/dev/null; grep -l "plk_search" ~/.claude/CLAUDE.md ~/.codex/AGENTS.md 2>/dev/null || echo "確認: 各グローバル指示ファイルの現状"`

確認結果に基づき、テーブルの「状態」列と冒頭の「配布方針」節を実態（controller 承認を経て配布済み、
または未配布のいずれか）に更新する。**事実に反する『配布済み』は書かない** — 未配布なら「Phase 3 時点でも
未配布・承認待ち」と正直に記す。冒頭見出しは「（Phase 2 Task 10）」を「（Phase 2 Task 10 / Phase 3 実態更新）」に変える。

- [ ] **Step 4: README のリンク先が実在することを dry-run 検証**

Run: `cd /Users/masahiro/dev/byteflare-co/plk-memory && for f in docs/MIGRATION.md docs/LESSONS.md clients/README.md; do test -f "$f" && echo "OK $f" || echo "MISSING $f"; done`
Expected: 3 ファイル全て `OK`（README が参照する docs/ 導線が実在）

- [ ] **Step 5: 全テスト緑・lint を確認**

Run: `uv run pytest -q && uv run ruff check src/ tests/`
Expected: PASS（テスト全緑・lint クリーン）

- [ ] **Step 6: コミット**

```bash
git add README.md clients/DISTRIBUTION.md
git commit -m "docs: README 総仕上げ・DISTRIBUTION 実態更新・UI auth 強化を EC2 前必須として注記

全体像セクション追加（ポート境界・docs 導線）。P2 持ち越し: 動線配布の実態反映と
UI auth 強化（定数時間比較・per-session cookie・レート制限）の EC2 前必須注記。

Claude-Session: https://claude.ai/code/session_01BH2sda1uFhHN1W87V4v1nt"
```

---

## Self-Review

**1. Spec coverage（Phase 3 スコープ §11 ＋持ち越し）:**

| スコープ項目 | 担当タスク |
|---|---|
| reindex 連打 silent drop（route flag 先行セット） | Task 1a |
| 同一 fact 並行 propose 重複（rev-list を dup チェック前へ） | Task 1b |
| DISTRIBUTION.md 実態更新 | Task 6 Step 3 |
| 認証アダプタ実換装 1 回（自己発行 JWT＋ローカル JWKS で JWTVerifier 起動・4 クライアント接続・静的 Bearer に戻す） | Task 2 |
| Slack 承認アダプタのスタブ＋ゴールデンテスト | Task 3 |
| UI auth EC2 前必須強化を README §7 に明記（実装せず注記のみ） | Task 6 Step 2 |
| 移行ガイド docs/MIGRATION.md（差分表: Auth0/ECS/PAT2分離/driver=/LLM・embedder クラウド化/group_id ハイフン/per-namespace 切替） | Task 4 |
| 運用知見レポート docs/LESSONS.md（発見バグ6件＋実測値＋グラフ層凍結判断＋設計変更履歴） | Task 5 |
| README 総仕上げ | Task 6 Step 1 |

全項目に担当タスクあり。ギャップなし。

**2. Placeholder scan:** LESSONS.md §5 に「（Task 2 Step 11 の記録を転記）」の意図的な埋め込み待ち箇所があるが、Task 5 Step 3 で転記＋残存チェック（grep "転記"）を必須化しているため plan 上のプレースホルダではなく「実手順で埋める指定」。他に TBD/TODO/「適切に」等の曖昧表現なし。全コードステップは完全なコードを含む。

**3. Type consistency:**
- `SyncEngine`: `begin_reindex() -> bool` / `end_reindex() -> None` / `_do_reindex() -> dict` を Task 1 で定義、ルート（app.py）で同名使用。`reindex()` は後方互換維持で既存テストと整合。
- `auth`: `build_jwt_verifier(settings) -> JWTVerifier` / `client_from_jwt(token) -> str | None` を Task 2 で定義、mcp_tools.py と BearerAuthMiddleware で同名使用。`Settings.auth_mode/jwt_issuer/jwt_audience/jwks_uri/jwt_public_key` は Task 2 Step 1 で定義し以降参照。
- `slack_promotion`: `build_approval_blocks(pr) -> list[dict]` / `parse_action_callback(payload) -> tuple[str,str]` / `SlackPromotionBackend.create_pr/merged_state/record_decision` を Task 3 で定義しテストで同名使用。`PromotionBackend` Protocol（create_pr/merged_state）に構造適合。
- `PromotionState`（proposed/approved/rejected/applied）・`transition`・`new_promotion`・`PromotionStore.by_fact` は既存 `promotions.py` の実シグネチャに一致。

不整合なし。計画確定。
