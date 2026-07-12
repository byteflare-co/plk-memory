# Task 3: Protocol の ports.py 集約と命名・設定修正

## ゴール

`postgres/worker.py` にローカル定義された 4 つの Protocol を `ports.py` に集約し、
`ports.py` のデッド Protocol（実装と乖離した `ChangeFeed` / `IndexStateRepository`）を
worker の実態に合わせて置き換える。あわせて誤解を招く命名と設定ファイルの不整合を直す。

## 触ってよいファイル（これ以外は変更禁止）

- Modify: `src/plk_memory/ports.py`
- Modify: `src/plk_memory/postgres/worker.py`
- Modify: `src/plk_memory/postgres/graph_adapter.py`
- Modify: `alembic.ini`（1 行のみ）

tests/ は変更禁止（テストは具象クラスのみ参照しており Protocol 名に依存しない。
`grep -rn "LegacyGraphIndex\|WorkerChangeFeed" tests/` が空であることを最初に確認すること）。

## 背景（現状の乖離）

- `ports.ChangeFeed`（ports.py:115-128）は参照ゼロのデッド。worker はローカルの
  `WorkerChangeFeed`（worker.py:33-48）を使い、こちらには `renew()` がある。
  実装 `PostgresChangeFeed`（outbox.py:19）は worker 版に準拠。
- `ports.IndexStateRepository`（ports.py:131-136）も参照ゼロのデッド。`mark_failed()` を
  要求するが、worker のローカル `ProjectionState`（worker.py:51-54）は
  `get` / `put_if_newer` のみ。実装 `PostgresIndexStateRepository`（outbox.py:207）に
  `mark_failed` が存在するかを確認して整理方針を決める。

## 手順

### Step 1: `ports.py` の Protocol を worker 実態に統一

- `ChangeFeed` に `renew(self, claim, *, lease_until) -> None` を追加し、
  worker.py の `WorkerChangeFeed` と完全同一のメソッド面にする
- `IndexStateRepository`: 実装 `PostgresIndexStateRepository` に `mark_failed` が
  **存在する場合**は ports 版をそのまま残し worker の要求面（get / put_if_newer）を包含して
  いることを確認、**存在しない場合**は `mark_failed` を削除して worker の
  `ProjectionState` と同一メソッド面にする
- worker.py の `FactReader`（get のみ）と `ProjectionIndex`（upsert のみ）を ports.py へ移動する
  （名前は `FactReader` / `ProjectionIndex` のまま。既存 `FactRepository` / `SearchIndex` の
  サブセットである旨を docstring 1 行で書く）

### Step 2: `worker.py` のローカル Protocol を削除

ローカルの `FactReader` / `WorkerChangeFeed` / `ProjectionState` / `ProjectionIndex` を削除し、

```python
from plk_memory.ports import ChangeFeed, FactReader, IndexStateRepository, ProjectionIndex
```

に置き換える（`WorkerChangeFeed` → `ChangeFeed`、`ProjectionState` → `IndexStateRepository`
への参照書き換えを含む）。`__init__` の引数名・実行ロジックは一切変えない。

### Step 3: `LegacyGraphIndex` を改名

`graph_adapter.py:25` の `class LegacyGraphIndex(Protocol)` は Git/Postgres 両バックエンドの
現行検索エンジン（graphindex.GraphIndex）の Protocol であり「Legacy」は誤解を招く。
`GraphIndexLike` に改名し、同ファイル内の参照（82 行付近）を更新する。
src 全体で `grep -rn LegacyGraphIndex src/` が空になることを確認する。

### Step 4: `alembic.ini` の fallback URL 修正

5 行目付近の

```
sqlalchemy.url = postgresql+asyncpg://postgres:postgres@localhost:5432/plk_memory
```

を docker-compose.yml の実構成（user/pass/DB すべて `plk`）に合わせて

```
sqlalchemy.url = postgresql+asyncpg://plk:plk@localhost:5432/plk
```

に変更する（`alembic/env.py` は `PLK_DATABASE_URL` を最優先するため、これは未設定時の
fallback の整合修正のみ）。

### Step 5: 検証

```bash
uv run ruff check .
uv run pyright
uv run pytest -q
```

Expected: エラーゼロ / 160 passed, 16 deselected

### Step 6: コミット

```bash
git add -A src/plk_memory/ alembic.ini
git commit -m "refactor: unify worker protocols into ports and fix naming"
```

## 完了報告に含めること

- `PostgresIndexStateRepository.mark_failed` の有無と、それに基づく IndexStateRepository の整理方針
- ports.py の最終的な Protocol 一覧
- 判断に迷って現状維持にした箇所（あれば）
