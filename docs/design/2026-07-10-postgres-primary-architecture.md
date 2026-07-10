# PostgreSQL-primary PLK アーキテクチャ

> Status: foundation implemented, runtime cutover not started  
> Decision date: 2026-07-10

## 1. 結論

複数人・複数サービスが同時に書き込む組織版 PLK では、PostgreSQL/Aurora を正本にする。
Git/Markdown は人間が読む snapshot と review/export の派生物、検索エンジンは候補抽出用の派生索引とする。

現行 Git-primary を誤りとはしない。1人・少数 writer では、差分レビュー、可搬性、手作業での復旧が安価という
明確な利点がある。一方、複数 writer で必要な transaction、idempotency、行ロック、tenant isolation、
低遅延 read-after-write を Git rebase/push で再現するのは、DB を使うより複雑になる。

## 2. 境界

```mermaid
flowchart LR
    C["Human / Agent / Service"] --> API["PLK API"]
    API -->|"transaction"| DB[("PostgreSQL / Aurora: SoT")]
    DB --> REV["Immutable revisions + audit"]
    DB --> OUT["Transactional outbox"]
    OUT --> W["Index worker"]
    W --> IDX[("Search index: derived")]
    API -->|"candidate IDs"| IDX
    API -->|"rehydrate + auth + current status"| DB
    DB --> EXP["Snapshot exporter"]
    EXP --> GIT["Git / Markdown: derived review artifact"]
```

不変条件は次の通り。

- 更新可能な正本は PostgreSQL だけ。Git と DB の双方向同期、API の dual-write は行わない。
- fact head、immutable revision、relation、audit、outbox は同一 transaction で更新する。
- 検索結果は index の本文をそのまま返さず、fact ID を DB から再取得して RLS・権限・status・revision を確認する。
- namespace は分類であり tenant 境界ではない。tenant 境界は `organization_id`。
- index worker は at-least-once。`organization_id + fact_id + revision` で冪等にし、
  ack/fail は claim ごとの lease token で fencing する。

## 3. 実装済みの foundation

### Storage contract

- `domain.py`: storage-neutral な actor、fact、revision、command、outbox、index model
- `ports.py`: `FactRepository`、`ChangeFeed`、`IndexStateRepository`、`SearchIndex`
- Git/Markdown、SQLAlchemy、Graphiti の型を core contract に持ち込まない

### PostgreSQL schema

Alembic revision `0001` は次を作成する。

| Table | 役割 |
|---|---|
| `knowledge_facts` | 現行 head と optimistic revision |
| `knowledge_fact_revisions` | 内容・status・actor・理由の immutable revision |
| `knowledge_relations` | `supersedes` / `related_to` |
| `idempotency_records` | request hash と確定 response の replay |
| `outbox_events` | index/export への transactional change feed |
| `approval_requests`, `approval_decisions` | revision 固定の承認フロー |
| `search_projection_state` | backend ごとの indexed revision |
| `audit_events` | metadata 操作監査 |

全 table の primary/foreign key に `organization_id` を含める。全 table で RLS を有効にし、transaction-local の
`app.current_organization_id` を `USING` と `WITH CHECK` の両方で検証する。revision と audit は trigger で
UPDATE/DELETE を拒否する。

### Write semantics

- 同一 idempotency key + 同一 request hash: 最初の確定 response を返す
- 同一 key + 異なる request: `IdempotencyConflict`
- invalidate/supersede: `expected_revision` を要求
- 複数 supersede: fact ID 順に head を `FOR UPDATE` し、deadlock を避ける
- transaction commit 後に外部 API を直接呼ばない。outbox worker が処理する
- DB 経路も Git CI と同じ `plk-validator` を通し、actor role で philosophy/user/shared の書き込みを制限する

`READ COMMITTED` で row lock 待機後に revision を別 query で再取得する。head と revision を一度に join して
lock すると、待機前 snapshot のため更新後 row が消えて見える場合があるためである。この競合は統合テストで固定した。

## 4. Database role

role は migration で作らず、infra で環境ごとに作る。

| Role | 用途 | RLS |
|---|---|---|
| `plk_app` | API request | `NOBYPASSRLS`。必ず organization context を設定 |
| `plk_worker` | cross-organization outbox/index worker | `BYPASSRLS`。API から使用禁止 |
| `plk_migrator` | Alembic one-off task | schema DDL owner |

table owner は通常 RLS を bypass する。アプリ role を owner にしない。`FORCE ROW LEVEL SECURITY` は、
worker の `BYPASSRLS` を実環境で確認してから別 migration で有効化する。

API と worker は別々の `PostgresDatabase` / credential / connection pool を使う。worker transaction は
`allow_cross_organization=True` で明示生成した instance でしか開始できない。Aurora IAM auth では
`async_creator` を渡し、新しい物理 connection ごとに token を生成する。静的な15分 tokenを pool 全体へ
使い回さない。

## 5. Local verification

```bash
docker compose --profile postgres up -d postgres
PLK_DATABASE_URL=postgresql://plk:plk@127.0.0.1:5432/plk uv run alembic upgrade head
PLK_TEST_DATABASE_URL=postgresql://plk:plk@127.0.0.1:5432/plk \
  uv run pytest -m postgres tests/test_postgres_repository.py
```

通常の `pytest` は Docker 不要で、PostgreSQL suite を除外する。

## 6. Git-primary からの切替

双方向同期や長期間の dual-write は採らない。

1. Git snapshot を staging DB へ shadow importする。
2. fact count、content hash、status、supersedes chain、検索 hit を比較する。
3. API を短時間 write freeze し、最後の Git commit を確定する。
4. final import と再比較を行う。
5. API write/read を DB-primary に切り替える。
6. outbox worker を起動し、index lag がゼロになるまで追従させる。
7. Git writer を無効化し、DB→Git snapshot export のみ許可する。

rollback window 中も DB→Git export は行うが、Git を再び writer にする場合は明示的な運用判断と再importが必要。

Shadow parity のみを確認する importer は次で実行する。

```bash
PLK_DATA_REPO_PATH=/path/to/frozen/git-snapshot \
PLK_DATABASE_URL=postgresql://... \
uv run python -m scripts.migration.shadow_import_git \
  --organization-id 00000000-0000-0000-0000-000000000001
```

同じ Git commit からの再実行は deterministic idempotency key で replay される。supersedes chain は
old-to-new の topological order で投入する。これは current content/status/relation の比較専用で、Git の
historical timestamp を再構成しないため final production cutover には使用しない。import は dirty working
tree を拒否し、記録した commit の blob を `git show` で直接読む。parity は全 payload、content hash、status、
invalidation reason、supersedes relation を照合する。

## 7. SQUEEZE へ逆輸入する際の対応

- Aurora PostgreSQL Serverless v2、IAM DB auth、RDS-managed secret を前提にする。
- API/worker ごとに別 role と engine を作り、`async_creator` で接続時に IAM token を再発行する。
- SQLAlchemy asyncio / asyncpg / Alembic の version は SQUEEZE と揃えている。
- API session は `expire_on_commit=False`, `autoflush=False`。
- migration は service 起動時でなく one-off task で実行する。
- Aurora engine minor version と拡張は staging で検証後に固定する。local compose の major pin を本番指定として流用しない。

## 8. 残作業と cutover gate

foundation があるだけでは production cutover しない。以下が gate。

- 現行 MCP/API を storage-neutral application service に接続
- JWT claim から `organization_id`, principal, role を導出
- outbox index worker と lag/dead-letter metrics
- Git snapshot importer/exporter と parity report
- approval API の実装
- two API replicas + two workers の負荷/障害試験
- backup/restore、PITR、RTO/RPO の実証
- SQUEEZE staging Aurora で RLS/IAM auth/migration を実証
