# plk-memory 運用知見レポート（Phase 0〜3 の実測と判断）

逆輸入の本体資産。Byteflare パイロット（1 人法人・完全ローカル LLM・23 件コーパス）で
実測したバグ・数値・設計判断を、組織展開 が同じ轍を踏まないよう記録する。
数値の一次ソースは `agent-organization/reports/phase1-eval-report.md`。

## 1. 最大の判断: 23 件規模では素の埋め込みで十分＝グラフ層は凍結候補

- **素の埋め込み検索（bge-m3 cosine top5）が 20/20・MRR 1.000**（全て rank1）。
- graph(triplet) も 20/20・MRR 1.000 だが、triplet の fact テキストは statement そのもの＝
  **実質「statement 埋め込み＋RRF」であり、グラフ構造由来の付加価値ではない**。
- graph(episode) は 16/20・MRR 0.612。ローカル 20B のエンティティ抽出（英語混じり・汎用語化）を
  挟むぶん**ベースラインに明確に負ける**。ただし測定はローカル 20B（gpt-oss:20b）＝
  **graphiti の品質下限条件**であり、Haiku 等クラウド LLM なら抽出品質（日本語→英語混じり・
  汎用語化の劣化）に改善余地がある。「明確に負ける」は条件付きの結果。
- ripgrep 字句一致は 0/20（日本語口語クエリは空白を含まず 1 クエリ＝1 トークンになり文全体一致しない）。
- **結論**: 小コーパス（〜50 件）では graphiti を使う積極的理由が検索精度から出ていない。
  グラフ側にしかない機能価値（invalidated の索引除外・group 分離・履歴）は plk 側の仕組みで
  担保されており、embed ベースラインでも active のみ索引にすれば同挙動になる。
  **撤退ライン到達時はグラフ層を凍結し、Git 規約＋CI＋grep/埋め込み読み口のみで運用継続**する
  （Phase 0 成果はそれ自体で残る）。マルチホップ・時間推論・50 件以上での再評価が次の判断材料。
- **交絡条件 2 つ（一次レポート §5 の但し書き）**: (a) **23 件コーパスは参考値であり、撤退ライン
  判定はコーパス 50 件以上で実施する取り決め**。本数値は判定に使わない。(b) 上記の通り測定は
  ローカル 20B ＝品質下限条件。**凍結判断はこの 2 条件込みの暫定判断**である。

## 2. 発見バグ 6 件

1. **FalkorDriver の group_id グラフルーティング（Phase 1 T13）**: graphiti-core 0.29.2 の
   FalkorDriver は group ごとに別グラフだが、driver 参照を group 用グラフへ付け替えるのは
   `add_episode` のみ。`search`（単一 group）・`add_triplet`・`remove_episode`・`clear_data` は
   付け替えず、新規プロセスからの検索が空の `default_db` を読んで**恒久 0 ヒット**になっていた。
   → `GraphIndex._route_group()` で全操作前に両参照を付け替え、`asyncio.Lock`(op_lock) で
   route→操作を直列化（commit `d823b13`）。**申し送り**: 直列化は多 group・高並行でボトルネック
   （並行クライアント下で search が ingest 中ブロックされる）ため、**組織展開 で required なのは
   op_lock 直列化の解消**。第一候補は graphiti の `driver=` 引数スレッディングだが、実測では
   `Graphiti.search` のみ `driver=` 対応で、`add_triplet`/`remove_episode` は非対応 →
   graphiti upstream の対応確認または改修が必要。代替案は group ごとに Graphiti インスタンスを
   分離保持する方式（upstream 非依存）。`clear_data` は driver 第一引数で対応済み。
   詳細は `docs/MIGRATION.md` §2「グラフ検索の並行性」行。
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
4 クライアント（Claude Code / Codex / Hermes / Agent SDK 相当の 4 JWT: sub=claude-code/codex/hermes/custom-agent）
から接続確認した実測（commit `8a1f3c5`、レビュー対応 `68cbf05`）。

- **実作業時間**: タスク全体（API 検証〜TDD〜実測〜コミット）が **約 5 分 40 秒**（11:39:45〜11:45:23）。
  うち本番切替の実地検証（`launchctl bootout` → JWT モード起動 → JWKS 配信確認 → 4 クライアントのトークン
  検証 → 静的 Bearer への復旧確認）は **約 80 秒**（launchd bootout→bootstrap のみで完結）。レビュー対応
  （拒否経路を middleware の完全検証へ集約、ASGI e2e テスト 5 本追加）は launchd 再切替なしのコード修正のみ。
- **変更/追加行数**: 初回実装 `8a1f3c5` は `.env.example` +7 / `app.py` +15 / `auth.py` +44-4 /
  `mcp_tools.py` +5-1 / `settings.py` +9（新規 `scripts/auth/issue_jwt.py` 62行・`tests/test_jwt_auth.py`
  52行込みで合計 **8 files changed, 194 insertions(+), 5 deletions(-)**）。レビュー対応 `68cbf05` は
  `app.py` +8-1 / `auth.py` +20-10 / `tests/test_jwt_auth.py` +98（**3 files changed, 126 insertions(+), 11 deletions(-)**）。
- **詰まった点**: written_by の client 名が Starlette ミドルウェアに結合しており、JWT `sub` からの
  導出を追加する必要があった（`auth.client_from_jwt`）。JWKS の `kid` 一致・`audience` 設定・
  ローカル JWKS 配信（`/.well-known/jwks.json`）の 3 点は設定で完結。加えてレビューで判明した点として、
  初版は「middleware は unsigned decode のみ、署名検証は FastMCP 内部の別レイヤ」という二重処理構成
  だったため拒否応答の形式が層ごとに変わりうる罠があり、`68cbf05` で middleware 側に完全検証
  （署名・issuer・audience・expiry）を集約し 401 応答を一本化した。`RSAKeyPair.private_key` が
  pydantic `SecretStr`（brief は str 記載）で、`.get_secret_value()` を忘れると壊れた鍵ファイルになる
  罠も実機確認で発見。
- **戻し方**: `PLK_AUTH_MODE` を外すと既定 bearer に回帰。鍵は破棄。Mac 運用は静的 Bearer を継続。
  本番切替では plist は恒久変更せず、`launchctl bootout`→手動起動→検証→`launchctl bootstrap` のみで
  完全復旧を実地確認済み。
- **組織展開 への含意**: `jwks_uri` を IdP（Auth0 等）に向けるだけで公開鍵取得は成立し、`build_jwt_verifier`
  のコード変更は不要。残る作業は IdP 側の API/Application 登録・スコープ設計、sub/claim 設計
  （principal 形式 `user:x`/`agent:y`）と written_by マッピングの整合、鍵ローテーション時の JWKS
  キャッシュ（1 時間 TTL）による kid 不一致対策、そして上記「二重処理」箇所を「middleware に検証を一本化」
  する方向へのリファクタ判断（追加工数半日〜1日程度と見積もり）。

## 6. 検証されていないもの（false green 対策・組織展開 側 PoC の担当）

graph-primary モード・Graphiti テンポラル機構（時点クエリ・矛盾自動検出）・namespace→group 1:1 の
実運用・マルチテナント/RBAC/Auth0 運用・昇格の人間側承認実効性・組織規模のインジェクション攻撃面・
グラフ規模のコスト外挿・単一 writer 前提の破れ（ECS 多レプリカ）。これらは本パイロットで一度も
踏んでいない。逆輸入時に新規検証すること。
