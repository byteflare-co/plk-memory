# 2026-07-12 構造リファクタリング計画

> **For agentic workers:** 各タスクは `goal-task-N-*.md` をゴールファイルとして持つ。
> 担当タスクのゴールファイルだけを読み、そこに書かれたファイル以外は変更しないこと。

**Goal:** 挙動を一切変えずに、肥大化したモジュールの分割・デッド Protocol の整理・クラス跨ぎ private 参照の解消・テストヘルパーの整理を行う。

**Architecture:** plk-memory は Git backend（現行本番・launchd 常駐）と PostgreSQL backend（実装済み・cutover 前）の 2 バックエンドを `settings.storage_backend` で切り替える。両方とも現役であり、削除・退役は本リファクタリングのスコープ外。

**Tech Stack:** Python 3.12 / FastAPI / FastMCP / SQLAlchemy(asyncio) / pytest / ruff / pyright / uv

## Global Constraints（全タスク共通・厳守）

- **挙動を変えない。** API レスポンスの形・エンドポイント・MCP ツールの入出力・環境変数名・SQL・トランザクション境界・例外型は一切変更しない。
- 公開シンボルの import パス互換を守る。既存の `from plk_memory.app import AppServices, _build_services`（scripts/eval/measure_ingest.py が使用）と `from plk_memory.app import create_app`（tests 多数）は動き続けること。
- 検証は既存テストがグリーンのままであること（新規テストは原則書かない。移動に伴う import 修正のみ可）。
- 完了条件: `uv run ruff check .` / `uv run pyright` / `uv run pytest -q` がすべてエラーゼロ（ベースライン: 160 passed, 16 deselected）。
- コメント・docstring は既存の日本語スタイルに合わせる。移動したコードのコメントは保持する。
- コミットは Conventional Commits（`refactor: ...`）。担当 worktree のブランチにコミットする。

## タスク一覧（ファイル単位で互いに素・並列実行可能）

| # | タスク | ゴールファイル | ブランチ |
|---|---|---|---|
| 1 | app.py 分割（Git ファサード / コンポジション / ASGI 結線） | goal-task-1-app-split.md | refactor/task-1 |
| 2 | postgres 書き込み層の共有ヘルパ化 | goal-task-2-postgres-write-layer.md | refactor/task-2 |
| 3 | Protocol の ports.py 集約と命名・設定修正 | goal-task-3-ports-unification.md | refactor/task-3 |
| 4 | tests 整理 | goal-task-4-tests-cleanup.md | refactor/task-4 |

## 検証と統合（オーケストレーター実施）

1. 各タスクブランチを `refactor/structure-cleanup` に順次マージ（ファイルが互いに素なので自動マージ）
2. `uv run ruff check .` / `uv run pyright` / `uv run pytest -q`
3. `docker compose --profile postgres up -d postgres` のうえ `PLK_TEST_DATABASE_URL=postgresql://plk:plk@127.0.0.1:5432/plk uv run pytest -m postgres`（Task 2 の repository.py 変更は既定 suite でカバーされないため必須）
4. 実機確認: `launchctl kickstart -k gui/$(id -u)/com.byteflare.plk-memory` 後に `/healthz` と MCP `plk_status` / `plk_search`
5. PR 作成 → マージ → main で実機再起動

## スコープ外（今回やらないと決めたこと）

- Git/Postgres 両バックエンドの検索フィルタロジック統一（挙動差リスクがあるため見送り）
- `settings.py` のネスト分割(環境変数名が変わるリスク)
- `tool_history` の重複キー削除・レスポンススキーマ統一（API 互換性）
- `slack_promotion.py` の削除（意図されたスケルトン）
- Git backend 系コードの退役（Postgres cutover 完了後の棚卸しで実施）
