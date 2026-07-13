# plk-memory セットアップ・運用ガイド

PLK メモリ基盤 — Git互換backend / PostgreSQL組織backend + Graphiti派生索引。

## 全体像

> 基盤全体のアーキテクチャ・規約・現在地は [`../README.md`](../README.md) を参照。

plk-memory は個人互換modeでは **Git**、複数writerの組織modeでは **PostgreSQL** を正本とし、
graphiti/FalkorDB を再構築可能な派生索引とする組織メモリの MCP サーバー。エージェント（Claude Code / Codex / Hermes / 自作）が `plk_search` で
過去の知見を引き、`plk_add` で書き、`plk_propose_promotion` でドメイン知見を全社共有（`shared/`）へ
昇格させる。

- **データの実体**: Git backendは `agent-organization/knowledge/`、PostgreSQL backendはtenant RLS配下のimmutable revision。
- **アーキテクチャ / 設計判断**: 設計書（SoT）は [`design/`](design/)（入口は [`../README.md`](../README.md)）を参照。
- **組織展開**: 移行手順は [`MIGRATION.md`](MIGRATION.md)、実測・判断は [`LESSONS.md`](LESSONS.md)。
- **ポート境界**: FactStore(Git) / GraphIndex(graphiti) / WriteSerializer(flock) / PromotionBackend
  (GitHub PR・Slack スタブ) / AuthProvider(Bearer・JWT) / LogSink(JSONL)。各境界は設定または
  1 ファイルの差し込みで別実装へ交換できる。
- **クライアント接続**: [`../clients/`](../clients/) の接続テンプレートと検索動線。

## ①前提

- [uv](https://docs.astral.sh/uv/)
- Docker（FalkorDB コンテナ用）
- Ollama（埋め込み・ingest LLM 用）— `ollama pull bge-m3`（埋め込み）と `ollama pull gpt-oss:20b`（ingest LLM。既に導入済みの環境もある）でモデルを取得しておく
- `ANTHROPIC_API_KEY`（`PLK_LLM_PROVIDER=anthropic` を選ぶ場合のみ必要。既定の ingest LLM はローカル Ollama で Anthropic API を消費しない。使う場合は **`.env` には書かず、シェル環境で `export` して継承する**）
- `agent-organization` リポジトリ（データリポジトリ = SoT）への ssh アクセス

## ②セットアップ

```bash
cp .env.example .env
# PLK_ADMIN_TOKEN / PLK_TOKENS 用のトークンを生成する例
openssl rand -hex 16

docker compose up -d falkordb
uv sync
```

`.env` を編集し、`PLK_DATA_REPO_URL`（データリポジトリの ssh URL）、`PLK_TOKENS`（クライアント別トークン）、
`PLK_ADMIN_TOKEN` を設定する。ingest LLM は既定でローカル Ollama（`PLK_LLM_PROVIDER=openai-compatible`）を使うため
追加設定不要。`PLK_LLM_PROVIDER=anthropic` を選ぶ場合のみ `ANTHROPIC_API_KEY` が必要（`.env` に書かず、シェル環境で `export` する）。

## ③起動

```bash
uv run uvicorn plk_memory.app:create_app --factory --host 127.0.0.1 --port 8735
```

### PostgreSQL-primary local runtime

API roleとworker roleは本番では必ず分離する。以下の同一owner credential例はlocal smoke専用で、
RLS分離を検証しない。RLS/IAM authの検証は設計書のproduction gateに従い、stagingで別roleを使う。

```bash
docker compose --profile postgres up -d postgres falkordb
PLK_DATABASE_URL=postgresql://plk:plk@127.0.0.1:5432/plk \
  uv run alembic upgrade head

export PLK_STORAGE_BACKEND=postgres
export PLK_DATABASE_URL=postgresql://plk:plk@127.0.0.1:5432/plk
export PLK_WORKER_DATABASE_URL=postgresql://plk:plk@127.0.0.1:5432/plk
export PLK_DEFAULT_ORGANIZATION_ID=00000000-0000-0000-0000-000000000001

# terminal 1: API（local smokeではowner。productionはNOBYPASSRLS role）
uv run uvicorn plk_memory.app:create_app --factory --host 127.0.0.1 --port 8735

# terminal 2: index worker（local smokeではowner。productionは専用worker role）
uv run plk-index-worker
```

`/healthz` はDBへ接続できない場合503。Graphiti/Ollama停止時はDB writeを維持し、検索だけdegradedになる。
workerはGraphへの外部副作用をDB leaseだけではfenceできないため1件ずつclaimし、同一factのrevisionを
順番に処理する。max attempts到達後はdead letterへ移す。

## ④動作確認

```bash
curl -s localhost:8735/healthz
# => {"ok":true}

curl -s -X POST localhost:8735/admin/sync -H "Authorization: Bearer $PLK_ADMIN_TOKEN"
```

## ⑤Git backendのみ: 単一レプリカ必須の注意

データリポジトリへの書き込みは専用 clone 経由の単一 writer（`flock`）を前提としている。
同一マシンでの多重起動やレプリカの複数同時稼働はロック取得に失敗して起動が失敗する仕様。
プロセスを止める際は必ず終了させてから次を起動すること（flock が残ったままだと以後の起動も失敗する）。

## ⑥MCP クライアント登録

Claude Code / Codex / Hermes / Agent SDK からの接続テンプレートと検索動線は `clients/` を参照。

## ⑦縮退動作

FalkorDB や Ollama が停止していても、Git backendはGitへのfact保存、PostgreSQL backendはDBへのfact保存を継続する。
どちらも正本は生きたまま、グラフ索引が未接続の場合は `plk_search` が `degraded: true` を返し、検索のみ縮退する。

## ⑧常駐運用（launchd）

Mac 上で `plk-memory-api` を launchd 常駐化する運用手順（`deploy/com.byteflare.plk-memory.plist`）。
本番エントリは `plk_memory.app:create_prod_app`（`enable_github_promotion=True`）。plist の `uv` パスは
`which uv` の実パスに合わせて調整すること（環境によって `/opt/homebrew/bin/uv` ではなく
`~/.local/bin/uv` 等になる）。

1. **起動**

   ```bash
   mkdir -p ~/.plk/logs
   cp deploy/com.byteflare.plk-memory.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.byteflare.plk-memory.plist
   ```

2. **停止**（KeepAlive ごと止まる）

   ```bash
   launchctl bootout gui/$(id -u)/com.byteflare.plk-memory
   ```

3. **再起動**

   ```bash
   launchctl kickstart -k gui/$(id -u)/com.byteflare.plk-memory
   ```

4. **ログ**: `~/.plk/logs/plk-memory.{out,err}.log`（`tail -f` で追う）

5. **前提サービス**: Docker（このマシンでは OrbStack。FalkorDB `restart: unless-stopped`）・Ollama 常駐
   （`ollama serve` / メニューバーアプリ）。どちらか停止時は `plk_search` が degraded 応答（書き込みと
   SoT は生存）。ログイン時自動起動（Docker Desktop／OrbStack のいずれか）が OFF の環境では手動 ON 化を
   検討すること。

6. **単一レプリカ**: writer flock により二重起動は fail-fast（`AnotherInstanceRunning`）。`workers=1` 固定。
   launchd 管理プロセスの終了時は OS が flock を解放するため、KeepAlive の再起動ループには陥らない。

7. **EC2・組織展開期への持ち越し注記（設計書 §7 準拠）**: Tailscale 内限定公開・push 用 fine-grained
   PAT（contents:write）と PR 用資格情報の 2 分離・実ホスト名 bind 時の DNS リバインディング allowlist
   （`PLK_ALLOWED_HOSTS`）は本 Phase では未実施。Mac 常駐期は 127.0.0.1 bind＋既存 ssh/gh 認証で運用する。

   **UI auth の EC2 前必須強化（P2 最終レビューの standing condition・本 Phase では実装しない注記のみ）**:
   read 専用 Web UI は現在 localhost 前提で許容している弱点がある — (a) cookie/パスワード比較が
   非定数時間、(b) cookie トークンが静的、(c) ログインのレート制限なし。127.0.0.1 bind の間は許容だが、
   **EC2/Tailscale 公開前に**定数時間比較・per-session の cookie トークン・ログインのレート制限を
   実装することを必須条件とする。

## ⑨トラブルシューティング

### 検索が 0 ヒットを返し続ける場合

`plk_search` が全クエリで 0 ヒットになる障害は、「正本（Git/state.json）は健全なのに
グラフ索引だけが空・不整合」というパターンが典型（2026-07-10〜12 に実際に発生。
`plk_status` の `index_stale` は state.json の台帳と Git HEAD の比較でしかなく、
グラフ実体の消失・不整合は検知できなかった）。診断は上流から順に:

1. **plk_status を見る** — `graph_empty_mismatch: true` なら「台帳にはファクトがあるのに
   グラフが空」で確定。手順 4 の reindex へ。`degraded` が非 null なら FalkorDB / Ollama の
   死活をまず確認する。`graph_edges` で group ごとのエッジ実数も確認できる。

2. **グラフ実体をノード数で直接確認する** —

   ```bash
   docker exec plk-memory-falkordb-1 redis-cli GRAPH.LIST
   docker exec plk-memory-falkordb-1 redis-cli GRAPH.QUERY plk-main "MATCH (n) RETURN count(n)"
   docker exec plk-memory-falkordb-1 redis-cli GRAPH.QUERY plk-quarantine "MATCH (n) RETURN count(n)"
   ```

   - **count が 0 / グラフが無い** → グラフ実体の消失。RDB 永続化を確認（手順 3）した上で
     reindex で復旧（手順 4）。
   - **count > 0 なのに 0 ヒット** → データはある。疑うのは (a) state.json の episode_uuids と
     グラフ側 uuid の不整合（検索は当たっているが fact_id への帰属で全部捨てられる —
     サーバーログの `skipped N edges with no fact attribution` が証拠）、
     (b) ドライバの group ルーティング不良（`default_db` にノードが入っていないかも確認）。
     いずれも reindex（手順 4）で台帳とグラフが同時に再構築され解消する。

3. **FalkorDB の永続化を確認する** —

   ```bash
   docker exec plk-memory-falkordb-1 redis-cli CONFIG GET dir      # => /var/lib/falkordb/data
   docker exec plk-memory-falkordb-1 redis-cli INFO persistence | grep -E 'rdb_last_bgsave_status|aof_enabled'
   docker exec plk-memory-falkordb-1 ls -la /var/lib/falkordb/data  # dump.rdb / appendonlydir
   docker logs plk-memory-falkordb-1 2>&1 | grep -E 'Loading RDB|Done loading'
   ```

   マウント先はイメージの `FALKORDB_DATA_PATH`（= redis `--dir`）と同じ
   `/var/lib/falkordb/data` であること。起動ログに `Done loading RDB` と各グラフの
   ノード数が出ていれば、再起動でのデータ消失は起きていない。

4. **reindex で復旧する** —

   ```bash
   curl -s -X POST localhost:8735/admin/reindex -H "Authorization: Bearer $PLK_ADMIN_TOKEN"
   ```

   グラフ全 group の clear → state.json リセット → Git 正本から全件再 ingest が走る
   （バックグラウンド実行。実行中は `plk_add` 等が maintenance 応答を返す）。
   完了後に `plk_status` で `indexed_facts` と `graph_edges` が復元されたことを確認する。

### 2026-07-10 事故の記録（教訓）

コンテナ再起動後に `plk_search` が 2 日間全クエリ 0 ヒットになった。当初は「グラフデータ
全消失」と見えたが、コンテナログでは再起動時に RDB から plk-main 372 ノードが正常ロード
されており、**FalkorDB の永続化は機能していた**（マウント先も正しかった）。真因はグラフより
上のアプリ層（当時進行中だった大規模リファクタ期間中の台帳とグラフの不整合）で、
`/admin/reindex` により解消。この事故を受けて (a) `plk_status` に `graph_edges` /
`graph_empty_mismatch`（台帳とグラフ実体の乖離検知）を追加、(b) AOF を有効化
（`docker-compose.yml` の `REDIS_ARGS: "--appendonly yes"`）した。
