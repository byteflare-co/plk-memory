# plk-memory 移行ガイド（Byteflare Mac 版 → 組織展開 stg）

対象: 組織展開 の担当者が半日で staging に plk-memory を立てるための手順と、
Byteflare 固有の前提を 組織展開 前提へ置き換える差分。設計書 §10/§11 の逆輸入マッピングの実装版。

## 0. 前提の違い（要点）

Byteflare 版は「1 人法人・全クライアントが 1 台の Mac・完全ローカル LLM・GitHub PR 承認・
静的 Bearer・単一レプリカ常駐」で最適化されている。組織展開 stg では少なくとも
「複数人・ECS 複数レプリカ・クラウド LLM/embedder・Slack 承認・OIDC 認証・部署別 namespace」
へ置き換える。置き換えは全て設定または 1 ファイルの差し込みで済むようポート境界化してある。

## 1. 半日セットアップ手順（stg）

**前提**: `pyproject.toml` の `[tool.uv.sources]` により `plk-validator` は
`../agent-organization/tools/validator` へのパス依存（editable）。**agent-organization リポジトリを
plk-memory の兄弟ディレクトリに clone していないと `uv sync` が失敗する**。
組織展開 側でリポジトリ名・配置が変わる場合は `[tool.uv.sources]` のパスを書き換えること。

1. FalkorDB を Docker で起動（`docker compose up -d falkordb`）か、マネージド Redis+FalkorDB モジュール。
2. `.env` を stg 用に作成（下表の差分を反映）。`uv sync`。
3. データリポジトリ（知識リポジトリ）の stg 用 clone URL を `PLK_DATA_REPO_URL` に設定。
4. LLM/embedder をクラウドに向ける（下表）。
5. `auth_mode=jwt` ＋ IdP の JWKS URI を設定（下表）。
6. 起動して `/healthz` → `/admin/sync` → `plk_search` の順に疎通確認。
   `/admin/sync` は `Authorization: Bearer $PLK_ADMIN_TOKEN` が必須。`plk_search` の疎通は
   jwt モードでは発行済み JWT、bearer モードではクライアントトークン（`PLK_TOKENS`）を使う。
7. 昇格フローを 1 往復（propose → 承認 → applied → shared ingest）通す。

## 2. 差分表（Byteflare → 組織展開）

| 論点 | Byteflare 版（現状） | 組織展開 stg での置き換え | 触る場所 |
|---|---|---|---|
| 認証 | 静的 Bearer（`auth_mode=bearer`, `PLK_TOKENS`） | OIDC/Auth0 の JWTVerifier（`auth_mode=jwt`, `PLK_JWKS_URI`, `PLK_JWT_ISSUER`, `PLK_JWT_AUDIENCE`） | `settings.py`・`auth.build_jwt_verifier`（実装済み・Phase 3 で実換装検証）。written_by は JWT `sub` から導出する結合が残る点に注意（下記 §3） |
| 実行形態 | launchd 単一常駐（Mac） | ECS 化。ただし **writer 単一レプリカ必須**（`flock` + `asyncio.Lock`）。多レプリカは WriteSerializer を破る | 代替: Aurora advisory lock / SQS 単一コンシューマ。移行の不変条件（§4） |
| Git 資格情報 | Mac の既存 `gh auth`（PR 用と push 用が同一） | **PAT 2 分離**: push 用 fine-grained PAT（対象リポ限定・`contents:write` のみ）と PR 作成用を分離 | `github_promotion.py` の `gh` 呼び出し／push 用資格情報 |
| グラフ検索の並行性 | 単一 group・`op_lock` で route→操作を直列化 | **op_lock 直列化の解消が required**（並行クライアント下で search が ingest 中ブロックされるため、直列化のまま 組織展開 規模へ行くことは不可。Phase 1 T13 実測の申し送り）。**第一候補は graphiti の `driver=` 引数スレッディング**だが、`Graphiti.search` は `driver=` を受ける一方 `add_triplet`/`remove_episode` は受けない（実測確認済み）ため、graphiti upstream の対応確認または改修が必要。**代替案**: group ごとに Graphiti インスタンスを分離保持する方式（upstream 非依存） | `graphindex.py` の `_route_group`／graphiti driver 渡し方 |
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
