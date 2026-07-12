# Task 2: postgres 書き込み層の共有ヘルパ化

## ゴール

`postgres/repository.py`（715 行）から行マッパと書き込み共通処理（冪等・outbox emit・audit）を
専用モジュールへ抽出し、`approvals.py` が `PostgresFactRepository._audit` / `._emit` を
**クラス跨ぎで private 参照している密結合**を解消する。
SQL・トランザクション境界・例外型・戻り値・ハッシュ計算は一切変えない。

## 触ってよいファイル（これ以外は変更禁止）

- Modify: `src/plk_memory/postgres/repository.py`
- Modify: `src/plk_memory/postgres/approvals.py`
- Create: `src/plk_memory/postgres/mappers.py`
- Create: `src/plk_memory/postgres/write_ops.py`

tests/ は変更禁止（テストは具象クラスの公開メソッドのみ参照しており影響しないはず）。

## 手順

### Step 1: `mappers.py` を作成

`repository.py` から以下を移動し、モジュール関数にする（classmethod/staticmethod を外す）:

| 移動元（repository.py） | 移動先の関数名 |
|---|---|
| `_canonical_hash`（49 行付近） | `canonical_hash` |
| `_payload_hash`（56 行付近） | `payload_hash` |
| `_revision_values`（60 行付近） | `revision_values` |
| `PostgresFactRepository._record`（620 行付近, classmethod） | `record_from_row` |
| `PostgresFactRepository._payload`（635 行付近, staticmethod） | `payload_from_row` |
| `PostgresFactRepository._revision`（650 行付近, classmethod） | `revision_from_row` |

`_record` が `_payload` を呼ぶ内部参照はモジュール関数呼び出しに書き換える。
docstring・コメント・ロジックは保持する。

### Step 2: `write_ops.py` を作成

`repository.py` から以下をモジュール関数として移動する。第一引数に
接続（現在 `self._database` 経由で使っている connection / session 相当）を明示的に取る形へ
機械的に変換し、**SQL 文・パラメータ・例外の送出条件を一切変えない**:

| 移動元（repository.py） | 移動先の関数名 |
|---|---|
| `_begin_idempotent`（506 行付近） | `begin_idempotent` |
| `_finish_idempotent`（547 行付近） | `finish_idempotent` |
| `_emit`（567 行付近） | `emit_event` |
| `_audit`（598 行付近） | `record_audit` |

### Step 3: `repository.py` を更新

- 移動したメソッド・関数を削除し、`mappers` / `write_ops` からの import と呼び出しに置き換える
- 公開メソッド（`list` / `get` / `get_many` / `create` / `invalidate` / `history`）の
  シグネチャ・挙動は不変

### Step 4: `approvals.py` を更新

- `PostgresFactRepository._audit` / `._emit` への直接参照（124, 297, 315 行付近）を
  `write_ops.record_audit` / `write_ops.emit_event` の呼び出しに置き換える
- `approvals.py` 内の冪等ヘルパ（351〜401 行付近）が `write_ops.begin_idempotent` /
  `finish_idempotent` と **SQL・挙動が完全に同一の場合のみ** write_ops 呼び出しへ統合する。
  少しでも差分（対象テーブル・カラム・例外文言・ハッシュ対象）があれば統合せず現状のまま残し、
  完了報告に差分内容を記載する。**迷ったら統合しない。**

### Step 5: 検証

```bash
uv run ruff check .
uv run pyright
uv run pytest -q
```

Expected: エラーゼロ / 160 passed, 16 deselected

注意: `tests/test_postgres_repository.py` は `-m postgres`（実 DB 必要）のため既定 suite では
走らない。統合検証でオーケストレーターが実行するので、このタスク内では上記 3 コマンドで足りる。

### Step 6: コミット

```bash
git add -A src/plk_memory/postgres/
git commit -m "refactor: extract postgres mappers and shared write helpers"
```

## 完了報告に含めること

- repository.py / approvals.py の削減行数、新モジュールの行数
- approvals.py の冪等ヘルパを統合したか否か、その根拠（差分の有無）
- SQL・例外挙動に変更がないことの確認方法
