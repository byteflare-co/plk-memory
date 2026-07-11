# Byteflare 版 PLK メモリ基盤（plk-memory）設計書 v1.0

> 日付: 2026-07-02
> 状態: 敵対的レビュー反映済み（7視点 52 指摘 → must-fix 3 / should-fix 26 を反映）。ユーザーレビュー待ち。
> 前提資料: 組織展開「全社 AI エージェント・メモリ基盤」（社内設計資料 社内設計資料）／個人版 v3 設計書（同ディレクトリ 2026-06-27-personal-cross-agent-memory-design-v3.md）

## 1. 目的と位置づけ

**一言で**: Byteflare のエージェント群（Claude Code・Codex・Hermes・自作エージェント）が読み書きする組織メモリ基盤 `plk-memory` を建て、実運用で型（規約・namespace・昇格フロー・運用）とコード（FastAPI + graphiti-core + MCP）を検証し、**コードごと 組織展開 に逆輸入する**。

- 本設計 = v3 Track B の正式な前倒し着手（「事業展開が実際に予定された時」の条件が 組織展開 逆輸入の計画化で成立）。
- v3 の false green 教訓は継承: 何を de-risk し何をしないかを §10 で正直に固定。
- 7/2 決定との整合: 「士業ノウハウ = Git 知識ベース（frontmatter 規約）」は覆さず、**Git 知識ベースがそのまま PLK ストアの永続層（SoT）に昇格**。
- **設計境界**: 会話横断検索（Track A）はスコープ外・別系統。PLK markdown は Track A の索引対象にも含める（読み口の統一）。会社ファクトの SoT は Notion（複製せず `source` 参照）。

## 2. 確定済みの設計判断

| 論点 | 決定 | 補足（レビュー反映） |
|---|---|---|
| 逆輸入の形 | コードごと（方法論＋実装＋運用知見） | **組織展開 へは git-primary 構成（知識リポジトリ＋派生索引）自体を正式提案として持ち込む**。graph-primary への差し替えは本パイロットでは未検証と §10 に明記（「アダプタで差し替え可能」という中間的な言い方をやめ、ポート定義のみ骨格に残す） |
| 技術スタック | Python + FastAPI + graphiti-core + FalkorDB + MCP Streamable HTTP | 組織展開 §10.1/§11 と一致 |
| 永続層 | Git=SoT、Graphiti=再構築可能な派生索引 | **SoT の定義 = リモート main**（§6）。Graphiti のテンポラル機構（bi-temporal エッジ無効化・時点クエリ）は**使わない**設計判断を明文化: 履歴は Git 側、グラフは検索索引に徹する |
| 置き場所 | ローカル Docker Compose → 既存の小規模 EC2 EC2 | EC2 期も**公開面ゼロ**（Tailscale 内限定）。GitHub webhook は捨ててポーリングに（§6）。**※2026-07-03 改訂: EC2 昇格は延期**（既存の小規模 EC2 は t4g.small 2GiB でモデルが載らず、全クライアントが Mac 上のため実益薄と判明。Phase 2 は Mac 常駐のまま機能実装し、EC2 移行は n8n 連携 or 組織展開 逆輸入直前に実施） |
| 昇格承認 | **PromotionRequest を API 内の第一級リソース**とし、GitHub PR はそのバックエンド実装 | Slack Block Kit 差し替えを「UI アダプタ交換」で済ませるための状態機械の置き場所修正（レビュー指摘） |
| UI | **Phase 1 は GitHub / Obsidian をそのまま読み口に。専用 Web UI は Phase 2 で追加** | レビュー指摘（Phase 1 のクリティカルパスから複雑性を排除）とユーザー要望（PLK を見やすく）の折衷。UI は read 専用 REST のみに接続・sanitize＋CSP 必須・Bearer をブラウザに持ち込まない |

## 3. 全体アーキテクチャ

```
┌─ クライアント ─────────────────────────────────────────────┐
│ Claude Code / Codex / Hermes（ローカル、HTTP MCP + Bearer）   │
│ 自作エージェント（Agent SDK、HTTP MCP or REST）／ n8n（REST）  │
└──────────────┬────────────────────────────────────────────┘
               │ MCP Streamable HTTP / REST（同一ツールサーフェス）
┌──────────────▼────────────────────────────────────────────┐
│ plk-memory-api（FastAPI、単一プロセス・単一レプリカ必須）        │
│  ・MCP mount（FastMCP 3.x）＋ REST ＋（Phase 2〜）Web UI      │
│  ・規約バリデーション / シークレットスキャン / 利用ログ          │
│  ・WriteSerializer（asyncio.Lock＋repo ファイルロック）        │
│  ・PromotionRequest 状態機械（proposed/approved/rejected/applied）│
├──────────────┬──────────────────────┬─────────────────────┤
│ FactStore     │ GraphIndex（派生）     │ LogSink              │
│ =GitStore実装  │ graphiti-core 0.29+   │ 利用ログ JSONL        │
│ サーバー専用clone│ + FalkorDB            │ （シンクはIF化、       │
│ 1ファクト1ファイル│ Byteflareはgroup畳込み │  ECSではCW Logs等へ） │
└──────────────┴──────────────────────┴─────────────────────┘
        │ fetch→rebase→push          │ ingest 時のみ LLM
   GitHub リモート main（=SoT）    Anthropic API（Haiku 系）
   （PR 昇格 / 人間編集の入口）     + embedder（Phase 1 で比較選定）
```

- **コードリポジトリ**: `plk-memory`（新規）。Byteflare 固有値は設定に追い出す。
- **データリポジトリ**: `agent-organization` の `knowledge/`。ただし **plk-memory-api は専用 clone（例: `~/.plk/data-repo`）を持ち、人間の編集ディレクトリと物理分離**する（人間の編集は必ず GitHub 経由で取り込む。エディタ保存や git 操作がロック外から作業ツリーを壊す事故の遮断）。
- **ディレクトリ構造 = 組織展開 互換の namespace 表現**: `knowledge/shared/`（昇格済みのみ）、`knowledge/domains/{tax,legal,shaho,dev,backoffice,biz}/`、`knowledge/quarantine/`（external-untrusted 隔離）。
- **group_id マッピングは設定制（レビュー must-fix 反映）**:
  - ※実装知見（2026-07-02 Phase 1）: graphiti の `validate_group_id` は `[a-zA-Z0-9_-]+` のみ許可（ドット不可）。**group_id はハイフン区切り**（`plk-main`/`plk-quarantine`/`plk-domain-tax`）で実装。namespace（frontmatter）はドット区切りのまま。
  - **Byteflare モード**: 全 namespace → 単一 group `plk-main` ＋ 隔離 `plk-quarantine` の 2 group。namespace は frontmatter メタデータ＝検索フィルタとしてのみ機能。理由: CC/Codex/Hermes は全員汎用で「自 namespace」が存在せず、ドメイン横断の質問（1人法人で頻出）がデフォルトで引ける必要がある。FalkorDB の fan-out 問題も消える。
  - **組織展開 モード**: namespace → group 1:1（部署分離）。この構成の実運用検証は 組織展開 側 PoC の担当（§10）。
- **認可は read / write / admin の 3 種に簡略化**。「write:自部署」の粒度は 組織展開 側検証項目へ（§10）。不変条件「shared への直接書き込み禁止（昇格経由のみ）」は namespace 紐付けなしで執行可能なので全段階で維持。

### ポート定義（実装は Git 版のみ。graph-primary は未実装・未検証と明記）

| ポート | Byteflare 実装 | 組織展開 逆輸入時 |
|---|---|---|
| FactStore（read/write/list/history） | GitStore（専用 clone＋subprocess git） | 同一（git-primary を提案）。graph-primary は要新規実装 |
| GraphIndex（ingest/search/rebuild） | graphiti-core + FalkorDB | Neo4j/Neptune 差し替え時は group セマンティクス差異に注意（FalkorDB は group=物理別グラフ、Neo4j はプロパティフィルタ） |
| WriteSerializer | asyncio.Lock＋ファイルロック。**起動時に workers>1 を検出したら fail-fast** | ECS 多レプリカでは破れる。移行ガイドに「writer 単一レプリカ必須」を不変条件として明記（代替: Aurora advisory lock / SQS 単一コンシューマ） |
| PromotionBackend | GitHub PR | slack-bolt（Block Kit）。状態機械は API 側にあるため UI 差し替えで済む |
| AuthProvider | 静的 Bearer（クライアント別） | FastMCP JWTVerifier / RemoteAuthProvider（Auth0、RFC 9728）。**Phase 3 で実換装を1回実施して工数を実測**（§11） |
| LogSink | JSONL（ローカルFS） | CloudWatch Logs / Aurora |

### 技術選定（2026-07-02 検証済みファクトに基づく）

| 部品 | 選定 | 根拠 |
|---|---|---|
| graphiti-core | 0.29.2（>=0.28.2 必須） | 0.28.2 未満に Cypher injection 脆弱性。`clear_data(driver, group_ids)` で group 単位全削除 → 派生索引再構築が API で成立 |
| グラフDB | FalkorDB Docker 単一コンテナ | 1人規模最軽量（FalkorDBLite は実績薄、Kuzu は deprecated） |
| 構築 LLM | Anthropic claude-haiku-4-5 系 | structured output 第一級サポート（forced tool use 実装） |
| embedder | **Phase 1 で Voyage / Gemini / OpenAI を同一評価セットで比較して決定** | Voyage は multilingual 明記だが「ベンダー1本増」の運用軸も判断に含める。embedding API 停止時は検索不能→縮退（§8） |
| reranker | **Phase 1 は cross-encoder なし（RRF/MMR）で開始** | BGE ローカルは torch＋モデルで Docker イメージ 3〜5GB 級・EC2 メモリ未評価のため。rerank が精度上必要と実証されたら Voyage rerank API → BGE（optional-extra 分離）の順で比較 |
| MCP 層 | FastMCP 3.x ＋ `mcp>=1.27,<2` ピン | v2.0.0b1 が既出のため上限ピン必須。lifespan 配線（session_manager 相当）は実リクエストまで通す統合テストで検証（起動成功・初回リクエストのみ失敗する既知の罠） |
| Git 操作 | subprocess git CLI | GitPython は常駐プロセス非推奨と公式明言 |
| シークレット検知 | detect-secrets（in-process 一次）＋自前パターン（`sk-ant-`, `tskey-`, freee OAuth 等）＋ CI 側 gitleaks（二次） | detect-secrets はルール更新停滞のため自前プラグイン必須。スキャナは IF 化（Betterleaks 移行余地） |

## 4. データモデルと規約（規約 v1）

### 保存適格性

「新しく分かった」「確定した」「組織として決めた」だけでは保存しない。最上位の保存条件は、
**将来どの状況で取得され、どの判断または行動をどう変えるかを具体的に説明できること**とする。
現在構成、ADR、作業履歴、実装上の選択は、それだけではPLKに複製せず既存SoTに残す。過去の
意思決定を保存できるのは、その理由が将来起こりうる具体的な意思決定を変える場合に限る。
そのうえで候補は、(1) 将来の別セッションでも再利用する規範・判断ルール・検証可能な事実/手順、(2) 一過性でない、
(3) 一次情報・再現実験・人間の明示決定で確定、(4) 既存 SoT の生データ・可変値の複製でない、
(5) 特定顧客・特定セッションだけに閉じない、(6) P/L/K のいずれかに分類可能、(7) 独立して
invalidate できる最小の主張、の全条件を満たすこと。長い手順は既存 SoT に置き、PLK は入口と
適用条件を指す。

提案前に候補を `statement` / `kind` / `namespace` へ正規化し、`plk_search` で重複・更新対象を
確認する。同じ active ファクトがあれば提案しない。一般的な「PLK に追加しますか？」ではなく、
正規化した候補、新規・更新の別、将来の取得状況、取得しない場合と比べて変わる判断・行動を提示する。
候補がなければ PLK に言及しない。運用上の完全な
判定基準・除外例はデータリポジトリ `knowledge/CONVENTIONS.md` を正とする。

1ファクト1ファイル。frontmatter:

```yaml
---
id: 01J...                 # ULID。API 採番。CI で repo 全体の一意性＋既存 id/created_at の不変性を検証
kind: knowhow               # philosophy / logic / knowhow
statement: "..."            # 要旨（上限 200 字・最小 20 字）
why: "..."                  # 根拠・経緯（最小文字数＋定型文ヒューリスティックで形骸化を拒否）
how_to_apply: "..."         # 適用条件（同上。「状況に応じて」だけは拒否）
source: "..."               # 形式検証必須（URL / Notion ID / セッション ID の正規表現、複数可）。tax/legal/shaho は一次情報 source 1 件以上
source_type: agent          # user / agent / external-untrusted。**API 書き込みでは user 指定不可**（user は人間の PR 直編集のみ、CI で強制）
namespace: plk.domain.tax   # ディレクトリと一致（CI 検証）。検索フィルタとして機能
status: active              # active / invalidated
invalidation_reason: null   # plk_invalidate が必須で書き込む（git commit メッセージ任せにしない）
written_by: claude-code     # **サーバーがトークン identity から導出**。クライアント申告値は無視（不一致はエラー）。書式は principal 形式（組織展開 では user:x/agent:y に拡張予定）を予約
created_at: 2026-07-02T...
invalidated_at: null
superseded_by: null
tags: []                    # triplet ingest モード時は 1 件以上必須
---
（本文: 詳細・経緯・具体例。上限 2,000 字）
```

- 強制はツールレベル（組織展開 原則）: `plk_add` がバリデーション・シークレット検知・上限で**書き込み自体を拒否**。人間の直接編集はデータリポジトリ CI（同一バリデータ＋gitleaks）で同一規約を強制。
- `kind: philosophy` の API 書き込みは拒否し、人間の PR 直編集のみ許可する。
- `source_type: external-untrusted` は `quarantine/` に置き、検索デフォルト除外＋自動昇格禁止。**帰属の限界を明記**: 同一 Mac 上では全エージェントが他クライアントのトークンを env から読めるため、ローカル期の written_by は「ベストエフォート帰属」。組織展開 でのホスト分離で初めて実効化される（§10）。

### ingest 設計（日本語対策込み）

- 1 ファイル = 1 エピソード。**エピソード本文は日本語自然文テンプレートにレンダリング**（`知見: {statement}。根拠: {why}。適用条件: {how_to_apply}。{本文}`）。id/namespace/kind 等の識別子は episode name / source_description 側に退避し、エンティティ抽出対象から外す（英語プロンプトの graphiti に YAML を食わせる構造ノイズ対策）。
- `custom_extraction_instructions` に「エンティティ・事実は日本語のまま抽出」「識別子・フィールド名をエンティティ化しない」を明示。
- **content_hash は正規化後の意味フィールド**（frontmatter の canonical JSON ＋本文）に対して計算（表記揺れ・一括整形での無駄な再 ingest を防ぐ）。
- **ingest モードは設定制**: `episode`（LLM 抽出。既定）/ `triplet`（add_triplet 直挿入。LLM 抽出なし・ゼロコスト。tags を topic に使用）。Phase 1 で両モードを同一評価セットで比較し、既定を実測で確定する（検証済みファクト: add_episode は 1 件あたり十数回の LLM 呼び出し＋日本語 MinHash dedupe 不全で増幅。構造化済み入力に LLM 抽出の付加価値があるかは未知数）。
- **invalidated ファクトはグラフ索引から削除**。`plk_search` の既定は status=active のみ。無効履歴の照会は Git 側（`plk_history` / UI）。

## 5. ツールサーフェス（組織展開 §12.4 互換＋拡張）

| ツール | 機能 | 認可 |
|---|---|---|
| `plk_search` | ハイブリッド検索（query, namespace[], kind, status, 期間）。**Byteflare 既定 = 全 namespace（単一 group）** | read |
| `plk_add` | 知見追加。**`supersedes: [id]` オプションで旧ファクトの invalidate まで同一 commit でアトミックに実行** | write |
| `plk_propose_promotion` | PromotionRequest 作成 → GitHub PR 生成。**push 完了（local==origin/main）がプリコンディション** | write |
| `plk_invalidate` | 無効化（`invalidation_reason` 必須 → frontmatter へ書き込み → commit ＋ グラフから削除） | write |
| `plk_history` | 変遷照会。**path でなく frontmatter id をキー**に（rename で履歴が切れない） | read |
| `plk_status` | 索引鮮度（last_ingested_commit と HEAD の差・dead-letter 件数）・**未 push commit 数**・件数・未処理 PromotionRequest 一覧 | read |
| REST `/admin/reindex` | group 単位/全体の再構築。**非同期ジョブ＋メンテナンスモード（実行中の書き込みは 503）**で並行書き込みとの競合を遮断 | admin（write とは別トークン） |
| REST `/healthz` | 即応（Codex の起動ブロック 10 秒問題対策: 落ちている時はハングでなく即時拒否） | なし |

- 全 MCP ツールは 60 秒以内に応答（Codex tool_timeout の最小制約）。
- FastAPI ルート順序: REST → MCP mount → （Phase 2）静的 UI catch-all。
- Web UI（Phase 2）: read 専用 REST のみに接続（ブラウザから MCP を直接叩かない＝Bearer をブラウザに持ち込まない）。markdown レンダリングは sanitizer＋CSP 必須（本文は非信頼入力）。閲覧トークンは HttpOnly cookie。

## 6. 書き込みパスと整合性

**SoT の定義 = GitHub リモート main。** ローカル commit は「push 完了までは耐久化された意図」にすぎない。

1. `plk_add` → バリデーション → シークレットスキャン（in-process 同期）
2. WriteSerializer 取得 → 専用 clone にファイル書き込み → commit → **fetch → rebase → push のリトライループ**（コンフリクト時は黙って分岐させず呼び出し元にエラー）
3. **ingest は level-triggered 同期が一次機構**: group 単位の `last_ingested_commit` SHA を永続化し、起動時＋定期（10 分毎）＋書き込み直後に `git diff --find-renames <SHA>..HEAD` で差分同期。ジョブは「id X を HEAD の内容に同期せよ」という宣言型（実行時に HEAD から読み直す）。per-id 直列化・coalesce。add 前に `{id}@*` の既存エピソードを照会して差分適用（冪等化）。恒久失敗は per-file の dead-letter として `plk_status` と定期レポートに出す。
4. 人間の編集・PR merge の取り込み: **GitHub webhook は使わない**（Tailscale 内限定と両立しないため。レビュー指摘採用）。上記の定期ポーリング（pulls API で merged_at 確認＋level-triggered 同期）で拾う。1人法人の昇格頻度では 1〜5 分間隔で十分。
5. **昇格（rename）**: `--find-renames` で明示処理。組織展開 モード（group 1:1）では「旧 group から `{id}@*` 削除＋新 group へ追加」を単一同期ジョブに。不変条件チェック（同一 id のエピソードは namespace と一致する group にのみ存在）をリコンシリエーションに含める。
6. **non-fast-forward / force-push 検出時は自動 reset せず停止**して人間介入を要求（未 push commit の黙殺防止）。ハードデリート runbook に「API 停止 → filter-repo → サーバー clone 再作成 → 全 reindex」の順序を明記。
7. 全再構築: `clear_data(group_ids)` → 全ファイル再 ingest。夜間ジョブとして実行（§12 の壁時計コスト参照）。

## 7. 認証・セキュリティ

| 段階 | 認証 | 経路 |
|---|---|---|
| Phase 1（ローカル） | **クライアント別静的 Bearer（4 個、env 参照）** — written_by 導出のため Phase 1 から個別化（レビュー指摘採用） | 127.0.0.1 bind |
| Phase 2（EC2） | 同上＋定期ローテーション（失効リスト機構は作らない。漏洩時はローテで対応） | **Tailscale 内限定・公開面ゼロ**（webhook 廃止により成立）。TLS は Tailscale が担保 |
| 逆輸入時 | FastMCP JWTVerifier / RemoteAuthProvider（Auth0、OAuth 2.1 / RFC 9728）。現行 MCP 仕様（2025-11-25）で認可は OPTIONAL のため静的 Bearer は仕様違反ではない | ALB + WAF |

- **記憶汚染ゲートの実効化**（レビュー指摘採用）: written_by はサーバーがトークンから導出（申告無視）。API 経由の source_type 上限は `agent`（`user` は人間の PR 直編集のみ・CI 強制）。「上方向の偽装」をツールレベルで遮断。
- **shared 直 push バイパス対策**: ingest 側を信頼アンカーにする。`shared/` 配下の変更は「approving review 付き merged PR 由来」を GitHub API で検証してから ingest。直 push 由来の shared/ 変更は隔離＋アラート。API の push 用資格情報は fine-grained PAT（対象リポ限定・contents:write のみ）とし、PR 作成用と分離。
- **昇格 PR の CI 必須チェック**: (a) 変更は `domains/*→shared/*` の rename・1 ファイルのみ・内容差分は frontmatter の `namespace:` 行 1 行（`plk.domain.<d>` → `plk.shared`）のみ許容（※当初案「rename 100%・内容変更なし」は namespace↔パス一致チェックと構造的に両立不能なことが Phase 0 実装の最終レビューで判明し、2026-07-02 にこの形へ確定） (b) source_type ≠ external-untrusted (c) PR 本文は固定テンプレート生成・HTML コメント/生 HTML 除去。運用規約「承認判断は PR 本文でなく Files changed を正とする」。
- **ハードデリート runbook（改訂）**: 手順 1 = **該当シークレットの失効・ローテーション**（Anthropic/Tailscale/freee 各コンソール）。手順 2 以降 = API 停止 → `git filter-repo` → GitHub 側残存（dangling commit・PR diff キャッシュ）は「鍵失効済みのため許容」or Support へ purge 依頼を選択 → 全クライアント re-clone → 全 reindex。**利用ログは本文を記録しない**（コンテンツハッシュ＋メタデータのみ。消せない残存箇所を作らない）。
- EC2 デプロイ注意（検証済み）: MCP SDK の DNS リバインディング保護 → 実ホスト名では transport_security の allowlist 必須。リバースプロキシは /mcp でエラー時も HTML を返さない（Hermes の content-type プリフライト対策）。

## 8. 障害・縮退（v3 §9.5 のオフライン契約）

- 接続テンプレートに「タイムアウト → メモリなしで続行」を明記。**Codex は無応答サーバーで初回ターンが 10 秒ブロックされる既知課題**（issue #19556）→ /healthz 即応・落ちている時は接続拒否（ハング禁止）・`enabled=false` の一時無効化手順をテンプレートに記載。
- グラフDB 停止時: `plk_search` は「索引不可」を返す。読み口の代替 = GitHub / grep（SoT は markdown）。
- **embedding API 停止時**: クエリ埋め込み不能 → グラフの BM25/全文系のみに縮退 or「検索縮退中」を返す（ベンダー依存の障害点として §13 に記載）。

## 9. 運用設計

- **検索を呼ぶ動線（must-fix 反映・Phase 1 成果物）**: 各クライアントの設定/スキルに 1 行を配布 — 「税務・社保・法務・過去の意思決定に関わる判断の前に plk_search を引く」。CLAUDE.md / Codex config / Hermes プロンプト / スキル化。利用ログに「自発（プロンプト誘導）か人間の明示指示か」を記録し、チェックポイント判定は動線導入後の期間のみを対象にする。
- **昇格フロー**: `plk_propose_promotion` → PromotionRequest（proposed）→ PR 自動作成 → 人間が GitHub でレビュー・merge → ポーリング検知 → applied ＋ ingest。却下 = クローズ＋理由（rejected）。未処理一覧は `plk_status` から。
- **キュレーション**: 週次でなく**月次 or 需要駆動**（オンデマンドレポート生成）。矛盾・重複検出は**コーパス 100 件到達まで無効**（小コーパス期の誤検知によるアラート疲れ防止）。レポートは markdown としてデータリポジトリに commit（GitHub がそのまま閲覧・通知導線 = Phase 1 の UI 代替）。
- **監査**: 別建て監査ストアは作らない（1人運用で読者不在）。書き込み監査 = push 済み git 履歴。読み取り = 利用ログ JSONL。LogSink IF だけ定義し、実体は 組織展開 側で CloudWatch/Aurora に。

## 10. 逆輸入マッピングと「検証されないもの」（false green 対策）

**そのまま持ち上がる**: MCP ツールサーフェス（**汎用 MCP/REST クライアントに限る** — v3 §11 の但し書きを復活）、規約＋バリデータ＋CI、GraphIndex ラッパー（ingest/検索/再構築/リコンシリエーション）、PromotionRequest 状態機械、日本語評価セット＋実測値（精度・ファクト単価・ベースライン対照）、テストコード（合成シナリオ含む）。

**設計提案として持ち込む**: **git-primary 構成そのもの**（知識リポジトリ＋派生索引。監査・巻き戻し・ハードデリートの解決策込み）。組織展開 参照アーキテクチャ（graph-primary）に対する変更提案として扱う。

**このパイロットでは検証されない（組織展開 側 Phase 1 PoC の担当）**:
- **graph-primary モード**（ポート定義のみ提供。書き込み・履歴・監査・削除の graph 側実装は新規開発）
- **Graphiti のテンポラル機構**（graph-native invalidation・時点クエリ・矛盾自動検出。本設計は索引を削除→再追加で使うため一度も踏まない）
- namespace→group 1:1（部署分離）モードの実運用・「write:自部署」粒度の認可
- マルチテナント分離・多人数同時書き込み・RBAC・Auth0 運用（認証アダプタの実換装 1 回だけ Phase 3 で実施し工数を実測）
- **昇格の承認判断の人間側実効性**（自己承認のため機械配管のみ検証。Slack Block Kit UI も未検証 — スタブ＋ゴールデンテストまで）
- 組織展開 実エージェント経路（専用エージェント経路）
- 組織規模のプロンプトインジェクション攻撃面・グラフ規模のコスト外挿
- 単一 writer 前提の破れ（ECS 多レプリカ）— 「writer 単一レプリカ必須」を移行ガイドの不変条件に

## 11. 段階導入計画

| Phase | 期間目安 | 成果物 | 完了条件 |
|---|---|---|---|
| **0: 規約とデータ基盤** | 半日〜1日 | `knowledge/` 構造＋規約 v1＋CI バリデータ（id 一意性・namespace 一致・シークレット・昇格 PR チェック）＋シード知見棚卸し | 実ノウハウ 20 件以上が規約準拠で存在（**人工矛盾系列**: 同一トピックの update 連鎖を含める） |
| **1: PoC（ローカル）** | 1〜2週間（片手間） | compose（api＋FalkorDB）、plk_add/search/invalidate/history/status、level-triggered 同期、reindex、クライアント別トークン、**検索動線の配布**、**日本語評価セット** | ①**ベースライン対照**: 同一 20 クエリを plk_search vs 非グラフ検索（ripgrep＋素の埋め込み検索）で比較 ②episode vs triplet モード比較 ③ファクト単価・全再構築コスト実測 ④動線導入後の実利用記録 |
| **チェックポイント** | Phase 1 完了時（コーパス 50 件以上到達後に精度評価） | 実測レポート | 継続 or 撤退判断（下記の数値基準） |
| **2: 運用機能（Mac 常駐）** | 1〜2週間 | ※EC2 デプロイは延期（上記 §2 改訂）。launchd 常駐化、昇格フロー、月次キュレーションレポート、**Web UI（read 専用）** | 昇格パイプ（PR 作成→merge 検知→ingest）が 1 往復する。全クライアント（CC/Codex/Hermes/自作1体）接続 |
| **3: 逆輸入パッケージ** | 数日 | ポート境界リファクタ、**認証アダプタ実換装 1 回**（自己発行 JWT＋JWKS or Auth0 無料枠で JWTVerifier モードを起動し 4 クライアント接続確認・工数実測）、Slack 承認アダプタのスタブ＋ゴールデンテスト、README・移行ガイド・運用知見レポート | 組織展開 の誰かが半日で stg に立てられる状態 |

**撤退ライン（数値化・レビュー反映）**:
- 構築期: Phase 1 実働 2 週間超過／**グラフ検索がベースライン（ripgrep＋素の埋め込み）を precision@5 で上回らない**（評価はコーパス 50 件以上で実施。届かない場合の代替指標 =「行動につながった検索の週次件数」）／ファクト単価上限 **¥30/件・全再構築 ¥5,000** 超過 → グラフ層凍結、Git 規約＋CI＋grep/Track A 読み口のみで運用継続（Phase 0 成果は 7/2 決定の実装としてそれ自体で残る。triplet モードは凍結前の中間オプション）
- **運用期（レビュー指摘で追加）**: Phase 2 完了後、4 週間連続で実利用（動線経由の plk_search でヒットを実際に引用）が週 3 回未満、または保守が週 30 分超過 → グラフ層凍結・EC2 から撤去。月次レポートにこの数値と判定ルールを毎回印字。

## 12. コスト概算（レビュー指摘で数値化）

- ingest（episode モード）: 1 ファクト ≈ 十数 LLM 呼び出し（日本語 dedupe 不全で増幅）→ Haiku 系で **≈ $0.05〜0.10/件**。200 件全再構築 ≈ **$10〜30、壁時計 1.5〜3 時間**（group 内逐次投入の公式推奨のため）。→ 「使い捨て索引」は金額よりも壁時計が制約。再構築は夜間ジョブ・triplet モードならほぼゼロ。
- embedding 従量: 全再構築でも数十セント未満（無視できる。問題はベンダー追加の運用面）。
- インフラ: ローカル $0 → EC2 相乗いで追加ほぼ $0（FalkorDB は Redis ベース。**reranker を載せない構成にしたので**メモリ試算が現実的に）。
- 組織展開 比（月 $70〜120 + LLM）に対し桁で安い。

## 13. リスク表

| リスク | 対策 |
|---|---|
| graphiti-core の破壊的変更 | 派生索引＝いつでも再構築。GraphIndex IF で隔離。`mcp<2`・`falkordb<2` ピン |
| ingest コスト（日本語で増幅） | Haiku＋逐次投入＋単価実測＋triplet モード＋撤退ライン数値 |
| 日本語抽出品質 | 日本語テンプレート化 ingest＋custom_extraction_instructions＋評価セット（precision@5 に加え、エンティティ抽出の目視スポットチェック 10 件） |
| **グラフの付加価値が幻想**（ベースラインに勝てない） | Phase 1 の対照比較で判定。負けたらその事実を逆輸入レポートの一級知見にして凍結 |
| ゴミ知見・形骸化 | 内容ヒューリスティック（定型文拒否・最小文字数・source 形式検証）＋shared 承認制＋月次キュレーション |
| 秘密情報混入 | 書き込み時スキャン＋CI＋runbook（失効が第一手順） |
| 記憶汚染 | written_by サーバー導出＋source_type 偽装遮断＋quarantine＋shared の merged-PR 由来検証 |
| 単一障害点化 | graceful degradation 契約＋SoT=markdown＋Codex 対策（即時拒否） |
| 作って使わない（最恐） | **検索動線の配布を Phase 1 成果物に**＋自発/指示の区別ログ＋運用期キル基準 |
| SoT と索引の乖離 | level-triggered SHA 同期＋dead-letter＋plk_status の正直な鮮度表示 |
| ベンダー障害（Voyage 等） | 縮退動作定義＋embedder は設定差し替え可能 |

## 14. テスト戦略

- 規約バリデータ（境界値・欠落・上限・**意味的に空のフィールド**）
- シークレットスキャンのゴールデンテスト（実パターン注入）
- ingest 冪等性（同一入力→同一エピソード集合・リトライ二重登録なし・順序逆転）・reindex 競合（メンテナンスモード）
- **合成シナリオ**（v3 §8.3 の処方を復活・Phase 3 パッケージに同梱）: 並行書き込み・矛盾連鎖・汚染注入（external-untrusted の昇格試行）
- 日本語検索評価セット（20 クエリ＋期待ヒット、ベースライン対照込み）— 回帰テスト兼 組織展開 引き継ぎ資産
- 縮退テスト（グラフ停止・embedding API 停止・non-fast-forward 検出）
- MCP 統合テスト（実リクエストまで通す — lifespan 配線漏れは初回リクエストのみ失敗する既知の罠）

## 15. 検証済みファクトの出典

- graphiti-core 0.29.2 / Anthropic first-class / clear_data(group_ids) / FalkorDB group=物理別グラフ / 日本語 MinHash dedupe 不全（PR #1357）/ プロンプト英語のみ（issue #1141）/ add_episode コスト / 同梱 MCP サーバー experimental 継続: github.com/getzep/graphiti（2026-07-02 参照）
- MCP SDK v1.28.1 / mcp<2 ピン / lifespan（issue #1367）/ DNS リバインディング保護 / FastMCP 3.4.2 / 認可仕様 2025-11-25: modelcontextprotocol/python-sdk・gofastmcp.com・modelcontextprotocol.io
- クライアント仕様（Claude Code v2.1.198 / Codex 0.142.x — 直書きトークン拒否・起動ブロック issue #19556 / Hermes v0.18.0 実機ソース / Agent SDK）: 各公式 docs
- detect-secrets/gitleaks/Betterleaks/git filter-repo/GitPython 非推奨/webhook merged 判定/python-frontmatter: 各公式リポジトリ・docs.github.com

## 付録: 敵対的レビューの記録

2026-07-02 実施。7 視点（false-green / security / ops-yagni / data-quality / org-port / cost-perf / consistency）52 指摘 → 反駁検証を経て must-fix 3・should-fix 26 を本書に反映。全文はセッション 2ea8548a の `tasks/wwtyzda3u.output`。主な棄却済み指摘: 「v3 付録A の staging→レビュー方式の縮退」（事実誤認）等 2 件。
