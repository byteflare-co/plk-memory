# Task 4: tests 整理

## ゴール

`tests/conftest.py` に同居する git-sync 専用ヘルパーの分離、重複ヘルパー定義の解消、
関数内 import の整理を行い、テストコードの見通しを良くする。
テストの検証内容・カバレッジは一切変えない（アサーションの追加・削除・変更は禁止）。

## 触ってよいファイル（tests/ 配下のみ。src/ は変更禁止）

- Modify: `tests/conftest.py`
- Create: `tests/gitsync_helpers.py`
- Modify: `tests/test_sync.py`
- Modify: `tests/test_graphindex_mapping.py`
- Modify: `tests/test_jwt_auth.py`
- Modify: `tests/test_app.py`, `tests/test_gitstore.py`, `tests/test_webui.py`,
  `tests/test_app_promotion.py`, `tests/test_slack_promotion.py`（import 整理のみ）
- Modify: `tests/test_postgres_application.py`, `tests/test_postgres_worker.py`（docstring 追記のみ）

## 手順

### Step 1: git-sync 専用ヘルパーを分離

`tests/conftest.py`（52〜133 行付近）の git-sync 専用ヘルパー 6 関数
（`write_valid_fact` / `modify_statement` / `rename_with_namespace` / `set_invalidated` /
`delete_file` / `push`）を新規 `tests/gitsync_helpers.py` へ移動する。
モジュール docstring は「git-sync 統合テスト用のリポジトリ操作ヘルパー」の趣旨。
conftest.py には汎用ヘルパー（`sh` / `make_settings` / `make_store` と fixture 類）のみ残す。
移動対象を使用している全テスト（`grep -rn "write_valid_fact\|modify_statement\|rename_with_namespace\|set_invalidated\|delete_file\|push" tests/` で確認）の import を更新する。

### Step 2: ローカル `make_settings` の重複解消

- `tests/test_graphindex_mapping.py:46` のローカル `make_settings`: conftest 版と定義を比較し、
  同一なら削除して conftest 版を import、役割が異なるなら `make_graph_settings` 等の
  固有名に改名して衝突を解消する
- `tests/test_jwt_auth.py`: conftest 版を `make_app_settings` に別名 import した上で
  別のローカル `make_settings`（22 行付近）を定義している。ローカル版を `make_jwt_settings`
  等の固有名に改名し、紛らわしい別名 import を整理する

### Step 3: 関数内 import の整理

以下の関数内 `from tests.conftest import ...` / `from tests.fakes import ...` /
`from plk_memory.app import create_app` をトップレベル import に移動する:

- `tests/test_app.py:153-157`
- `tests/test_gitstore.py:126,136,152`
- `tests/test_webui.py:16-18`
- `tests/test_app_promotion.py:7-10`
- `tests/test_slack_promotion.py:98-101`

**注意:** 移動後に該当テストファイルを個別実行し、1 つでも挙動が変わる
（環境変数や monkeypatch のタイミングに依存して失敗する）場合は、そのファイルの
移動を取り消して関数内 import のまま残し、完了報告に理由を記載する。

### Step 4: postgres fake テストの明示

`tests/test_postgres_application.py` と `tests/test_postgres_worker.py` の
モジュール docstring に「fake（in-memory）実装ベースのため実 DB 不要。
`-m postgres` marker の付く実 DB 統合テストは test_postgres_repository.py /
test_postgres_runtime.py を参照」の趣旨を追記する（既存 docstring があれば追記、
なければ新規作成）。コード変更は禁止。

### Step 5: 検証

```bash
uv run ruff check .
uv run pyright
uv run pytest -q
```

Expected: エラーゼロ / 160 passed, 16 deselected（テスト数が増減しないこと）

### Step 6: コミット

```bash
git add -A tests/
git commit -m "refactor: separate gitsync test helpers and tidy test imports"
```

## 完了報告に含めること

- conftest.py の残存ヘルパー一覧と gitsync_helpers.py へ移動した関数一覧
- make_settings 重複の解消方法（統一 or 改名）
- 関数内 import のまま残した箇所とその理由（あれば）
