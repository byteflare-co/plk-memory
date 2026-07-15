# plk-memory メトリクスダッシュボード設計（Phase 1）

日付: 2026-07-15
ステータス: 設計承認待ち（codex レビュー指摘反映済み: 2026-07-15）
関連: [2026-07-02 設計書 §9/§11](2026-07-02-plk-memory-design.md)、[scripts/curation/run_report.py](../../scripts/curation/run_report.py)、[scripts/eval/run_eval.py](../../scripts/eval/run_eval.py)

## 1. 背景と目的

plk-memory には利用ログ（`~/.plk/usage.jsonl`）・月次キュレーションレポート・オフライン検索評価（hit@5 / MRR）が既にあるが、
これらを時系列で眺める手段がなく、「PLK がちゃんとワークしているか」を日常的に確認できない。
また設計書 §11 のキル基準は「動線経由 plk_search の**引用**が週 3 回未満」だが、引用（ヒットしたファクトが実際に判断を変えたか）は未計測である。

本設計は 2 フェーズ構成の Phase 1 として、**既存データの可視化（ダッシュボード）** を既存 Web UI に追加する。
引用計測（`plk_cite`）は Phase 2 とし、本書 §8 に布石だけ定義する。

PDCA への対応:

- **Check**: ダッシュボードを開けば利用実態・コーパス健全性・キル基準との距離が一目で分かる
- **Act**: ゼロヒットクエリ一覧 =「欠けている知識」のシグナルから、ファクト追加・規約見直しにつなげる

## 2. スコープ

### 対象（Phase 1）

1. 集計モジュール `src/plk_memory/metrics.py`（集計関数は純粋。JSONL reader は I/O）
2. Web UI エンドポイント `GET /ui/api/metrics`
3. フロントエンド: 既存 UI に「Metrics」ビューを追加（外部ライブラリなし、SVG 直描画）
4. `run_eval.py` の結果を `~/.plk/eval-history.jsonl` へ追記し、時系列表示できるようにする
5. **検索ログの拡張**（codex レビュー must-fix 反映）:
   - `outcome`（`ok` / `degraded` / `error`）を記録し、「知識が欠けているゼロヒット」と
     「インフラ障害によるヒット 0」を区別可能にする。失敗経路でも `latency_ms` を記録する
   - `search_id`（ULID）を検索ログレコードと `plk_search` 応答の両方に付与する。
     Phase 2 の `plk_cite` が検索と引用を一意に対応付けるための相関 ID（§8）

### 非スコープ

- 引用計測・引用率表示（Phase 2）
- 週次通知・Slack/Notion 連携（指標が固まってから判断）
- usage.jsonl のローテーション（当面 280 行、10MB 到達は数年先。§9 に運用メモのみ）
- PostgreSQL backend の usage 記録。現状 `PostgresAppServices` は UsageLog を書いておらず、
  本ダッシュボードは Git backend のローカル運用（現行構成）を前提とする。
  postgres 移行時は usage 記録の実装とともに集計元を差し替える（metrics.py は入力が
  レコード list なので集計ロジックは再利用可）。

## 3. データソース

### 3.1 usage.jsonl（フィールド追加あり・後方互換）

```json
{"ts": "2026-07-15T03:16:36+00:00", "client": "codex", "tool": "plk_search",
 "query": "...", "hits": 10, "latency_ms": 400, "reason": "auto-guideline",
 "fact_ids": ["01KW..."],
 "search_id": "01KY...", "outcome": "ok"}
```

- `search_id` / `outcome` を新設（§2 対象 5）。`git_services.tool_search` の全経路
  （正常・graph 未接続の degraded・例外）で `outcome` と `latency_ms` を記録する。
  `UsageLog.log` にはキーワード引数を追加するだけで既存レコードとは後方互換
- 旧レコード（`outcome` なし）は集計時に `outcome: "ok"` とみなす（現状 280 行の実績を捨てない。
  障害由来のヒット 0 が混在しうることは §4② の注記として UI にも表示する）
- `tool` は `plk_search` 以外（history/invalidate 等）も混在する。検索系集計は `tool == "plk_search"` のみ対象
- **境界での型検証**: reader は「JSON として parse でき、かつ object（dict）である」行のみ採用し、
  それ以外（`null` / 配列 / 文字列など）は行ごと skip する。採用後も各フィールドは型チェックし、
  型不正は当該フィールドを欠落扱いにする（`curation.read_usage` の構文エラー skip だけでは
  1 行の破損で集計全体が落ちるため）。`ts` 欠落・不正の行は時系列バケットからのみ除外し、
  全期間集計（クライアント別・レイテンシ全期間など）には含める
- `reason == "auto-guideline"` を auto、それ以外を manual と分類（既存 curation と同一定義）

### 3.2 facts（既存・変更なし。ただし読み方に注意）

参照フィールド: `id` / `namespace` / `kind` / `status` / `created_at` / `invalidated_at` / `statement`。

- `FactService.list_posts()` は壊れた YAML で**例外を投げる**（[facts.py:69](../../src/plk_memory/facts.py) は
  無例外処理で `frontmatter.load` する）ため、metrics 経路では使わない。facade の
  `ui_metrics_posts()`（§6.2）がファイル単位で try/except し、壊れたファイルは skip して
  frontmatter メタデータの `list[dict]` を返す。skip 件数もレスポンスに含めて UI に出す
- `created_at` は **YAML datetime と ISO 文字列の両方**が現行契約として存在する。
  週別追加数の集計では両型を `datetime` に正規化する（文字列専用 `_parse_ts` をそのまま使わない）

### 3.3 eval-history.jsonl（新規）

`run_eval.py` 実行時に 1 ランナーにつき 1 レコード追記する:

```json
{"ts": "2026-07-15T10:00:00+09:00", "run_id": "01KY...", "runner": "graph(triplet)",
 "queries": 25, "queries_hash": "sha256:ab12...", "hit5": 21, "hit5_rate": 0.84, "mrr": 0.71,
 "corpus_active": 48, "corpus_total": 55, "corpus_revision": "354d0f8", "corpus_scope": "domains",
 "embed_model": null, "llm_model": "qwen2.5:14b", "graph_mode": "triplet"}
```

- パスは `Settings.eval_history_path: Path = Path.home() / ".plk" / "eval-history.jsonl"`
- **provenance を必ず保存する**: 系列の同一性は runner 名だけでは決まらないため、
  `run_id`（同一実行の全ランナーで共通の ULID）、`queries_hash`（クエリセットの sha256）、
  使用モデル、`graph_mode`、コーパスの Git revision（`git -C data-repo rev-parse --short HEAD`）、
  コーパス範囲（eval は `domains/` のみ対象である事実）を記録する。
  UI は `queries_hash` が異なる点を同一折れ線で結ばず、系列を分ける
- `run_eval.py` に `--no-history` フラグを追加（デフォルトは追記する）。既存の `--out` / stdout 出力・
  終了コードは不変とし、**履歴追記の失敗（read-only FS・権限不足等）は stderr 警告のみで
  評価自体は成功させる**（CI 互換）
- 集計値は既存 `render_markdown` 内の agg と同じ計算（hit@5 数・率・平均 MRR）を関数に切り出して共用する

## 4. 指標定義

すべて `metrics.py` の `build_metrics(usage: list[dict], posts: list[dict], eval_history: list[dict], *, now: datetime, tz: ZoneInfo) -> dict` が返す。

- タイムゾーンはホスト依存にせず `Settings.metrics_timezone: str = "Asia/Tokyo"` を新設し、
  `ZoneInfo` で変換してから日付で切る
- 週は `[月曜 00:00, 翌月曜 00:00)`（ISO week・半開区間）。進行中の週はグラフでは
  「進行中」と明示し、キル基準判定（④）には**完了した週のみ**を使う

### ① 利用実態（`search`）

| 指標 | 定義 |
|---|---|
| 週別検索数 | 直近 12 週。auto / manual の積み上げ |
| 週別**結果返却率** | `outcome == "ok"` かつ `hits > 0` の件数 ÷ `outcome == "ok"` の検索数（検索 0 の週は null）。「関連する結果が返った」ことまでは保証しないため「ヒット率」とは呼ばない |
| 週別障害数 | `outcome` が `degraded` / `error` の件数。返却率の分母から除外し、独立の系列として表示 |
| クライアント別内訳 | 全期間の `client` 別検索数 top 10 |
| レイテンシ | 直近 7 日と全期間それぞれの p50 / p95（nearest-rank 法。`latency_ms` 欠落は除外） |

### ② ゼロヒットクエリ（`zero_hit`）

- `tool == "plk_search"` かつ `outcome == "ok"` かつ `hits == 0` のレコードが対象。
  障害由来（`degraded` / `error`）は「欠けている知識」ではないため含めず、①の障害数で扱う
- **全期間のレコードを query 文字列で group してから**、`last_ts` 降順に最大 50 グループを返す
  （先に 50 件へ切ってから dedup しない）
- 各行: `query` / `count` / `last_ts` / `clients`（発生クライアントの集合）
- 旧レコード（`outcome` なし）は ok 扱いのため混入しうる旨を UI に注記する（§3.1）

### ③ コーパス健全性（`corpus`）

| 指標 | 定義 |
|---|---|
| ステータス別件数 | active / invalidated |
| namespace 別件数 | active のみ、件数降順 |
| kind 別件数 | active のみ（philosophy / logic / knowhow） |
| 週別追加数 | `created_at`（datetime / 文字列の両型を正規化）を週で切った直近 12 週 |
| **未返却ファクト** | usage に fact_id が一度も現れない active。件数と最大 30 件の一覧。検索結果に含まれた事実しか測れず「実際に使われたか」は Phase 2 の引用計測まで不明なため、「未参照」ではなく「未返却」と呼ぶ |

### ④ キル基準との距離（`kill_criteria`）— **proxy 表示**

設計書 §11 の正式なキル基準は「Phase 2 完了後」「動線経由の**引用**が週 3 回未満」「保守週 30 分超過との OR」であり、
Phase 1 のデータでは確定判定できない。よって本ブロックは **proxy（参考値）** として表示する:

- 直近 4 **完了**週それぞれの「`outcome == "ok"` かつ `hits > 0` の auto（動線経由）検索数」と閾値 3 を返す
- `threshold_weekly_hits = 3` は `metrics.py` の定数とし、`run_report.py` の KILL 文言とコメントで相互参照する
- 判定は 3 値: 完了週が 4 週分観測できていなければ `"inconclusive"`、
  4 完了週連続で閾値未満なら `"proxy_breached"`、それ以外は `"proxy_ok"`。
  `breached: true/false` の断定値は返さない（false green / 早期 breach の両方を防ぐ）
- UI には「正式判定は Phase 2（引用計測）以降。保守時間は本ダッシュボードの対象外」と明記する

### ⑤ 検索品質（`eval`）

- eval-history.jsonl を runner 別にグルーピングし、`{runner: [{ts, hit5_rate, mrr, corpus_active}]}` の時系列を返す
- 履歴が空なら空 dict（UI 側は「未実行。`uv run python scripts/eval/run_eval.py` で計測」と案内表示）

## 5. API 設計

### `GET /ui/api/metrics`

- ガード: `_require_cookie`（read 専用。既存の `/ui/api/facts` と同等）。write ガード・CSRF は不要
- クエリパラメータなし（期間固定: 週次系は 12 週、キル基準は 4 週。パラメータ化は必要になってから）
- 都度計算。usage 280 行 + facts 数十件では数 ms であり、キャッシュは入れない
- レスポンス（概形）:

```json
{
  "generated_at": "2026-07-15T12:00:00+09:00",
  "search": {
    "weekly": [{"week": "2026-07-13", "in_progress": true, "auto": 12, "manual": 3,
                "returned": 13, "ok_total": 15, "failures": 1}],
    "clients": [{"client": "codex", "count": 180}],
    "latency": {"last7d": {"p50": 400, "p95": 3400, "n": 21}, "all": {"p50": 380, "p95": 2900, "n": 268}}
  },
  "zero_hit": [{"query": "...", "count": 3, "last_ts": "...", "clients": ["codex"]}],
  "corpus": {
    "available": true,
    "skipped_files": 0,
    "status": {"active": 48, "invalidated": 7},
    "namespaces": [{"namespace": "plk.domain.tax", "count": 12}],
    "kinds": {"philosophy": 3, "logic": 20, "knowhow": 25},
    "weekly_added": [{"week": "2026-07-13", "count": 4}],
    "unreturned": {"count": 9, "items": [{"id": "...", "namespace": "...", "statement": "..."}]}
  },
  "kill_criteria": {"threshold_weekly_hits": 3, "verdict": "proxy_ok",
                    "weeks": [{"week": "2026-06-22", "auto_returned_searches": 5}]},
  "eval": {"graph(triplet)": [{"ts": "...", "hit5_rate": 0.84, "mrr": 0.71,
                                "corpus_active": 48, "queries_hash": "sha256:ab12..."}]}
}
```

- エラー処理: usage / eval-history が存在しない・全行破損の場合も空扱いで 200 を返す（500 にしない）。
  facts 読込失敗はファイル単位 skip（`ui_metrics_posts` §6.2。skip 件数を `corpus.skipped_files` で返す）。
  PostgresAppServices では `corpus.available: false`

## 6. モジュール設計

### 6.1 `src/plk_memory/usage_records.py`（新規・共有下層）と `src/plk_memory/metrics.py`（新規）

`curation.py` と `metrics.py` が相互 import すると循環依存になるため、共有処理は
依存を持たない下層モジュール `usage_records.py` に置き、両者が一方向に import する:

```
usage_records.py                     # 依存なしの共有下層（I/O は read_* のみ）
  read_usage(path) -> list[dict]     # curation.py から移動。object 行のみ採用する型検証を追加（§3.1）
  read_eval_history(path) -> list[dict]
  referenced_fact_ids(usage) -> set[str]
  parse_ts(value) -> datetime | None # curation._parse_ts を移動・公開化

metrics.py                           # usage_records を import。集計関数はすべて純粋（now/tz 注入）
  build_metrics(usage, posts, eval_history, *, now, tz) -> dict
    ├─ _search_stats(usage, now, tz)
    ├─ _zero_hit_queries(usage)
    ├─ _corpus_stats(posts, usage)   # 未返却判定は usage_records.referenced_fact_ids を使用
    └─ _kill_criteria(usage, now, tz)

curation.py                          # usage_records を import（metrics には依存しない）
```

- `curation.read_usage` / `_parse_ts` は `usage_records` へ移動し、curation.py には
  後方互換の re-export を残す（`run_report.py` の import 文は不変。
  aggregate の外部仕様・レポート出力も不変で、既存 curation テストで回帰確認）

### 6.2 `webui.py`

- `build_ui_router` に `GET /ui/api/metrics` を追加
- ハンドラは `settings.usage_log_path` と `settings.eval_history_path` を読んで `build_metrics` に渡す
- facts メタデータは status を問わず全件必要（`ui_list_facts` は表示用整形のため不適）なので、
  facade に `ui_metrics_posts() -> tuple[list[dict], int]`（frontmatter メタデータ dict の list と
  skip 件数）を追加する。`AppServices`（Git backend）は knowledge 配下の `*.md` を
  **ファイル単位で try/except しながら** `frontmatter.load` する（`FactService.list_posts()` は
  壊れた YAML で全体が例外になるため直接使わない。§3.2）。
  `PostgresAppServices` は `([], 0)` を返すスタブとする
  （UI は corpus ブロックだけ「backend 未対応」表示にし、usage 由来の他ブロックは表示する）

### 6.3 `scripts/eval/run_eval.py`

- 集計計算を `compute_summary(queries, runner_results) -> dict[runner, {hit5, hit5_rate, mrr}]` に切り出し、
  `render_markdown` と履歴追記の両方から使う
- `main()` 末尾で `--no-history` でなければ `settings.eval_history_path` に追記。
  追記は try/except で包み、失敗は stderr 警告のみ（評価の stdout / `--out` / 終了コードに影響させない）。
  provenance フィールド（`run_id` / `queries_hash` / モデル / `corpus_revision` / `corpus_scope`）は §3.3 のとおり

### 6.4 フロントエンド（`src/plk_memory/static/index.html` / `src/plk_memory/static/app.js`）

- ヘッダーに「Facts / Metrics」のビュー切替を追加（タブ。既存の一覧＋詳細パネルは Facts ビューとしてそのまま）
- Metrics ビューは初回表示時に `/ui/api/metrics` を 1 回 fetch し、再取得ボタンを置く
- 描画コンポーネント（すべて素の SVG / DOM。外部ライブラリ禁止を維持）:
  - スタットタイル行: 総検索数・直近 7 日結果返却率・active ファクト数・キル基準ステータス（proxy）
  - 積み上げ棒: 週別検索数（auto/manual）
  - 折れ線: 週別結果返却率、eval hit@5 率 / MRR（runner × queries_hash 別系列）
  - 横棒: namespace 別件数、クライアント別件数
  - テーブル: ゼロヒットクエリ、未返却ファクト
- **XSS**: query / statement に限らず、**サーバー由来の全動的文字列**（client、runner、namespace、
  SVG 内の title / label を含む）を `textContent` / `createTextNode` で挿入する。
  `innerHTML` と SVG 文字列連結は禁止（sanitize 済み本文 `body_html` のみ例外、既存方針どおり）
- 空状態: eval 未実行・usage なしの各ブロックに案内文を出す

## 7. テスト計画

- `tests/test_usage_records.py`（新規）
  - 型検証: 非 object 行（null / 配列 / 文字列）・構文エラー行の skip、型不正フィールドの欠落扱い
  - `parse_ts` / `referenced_fact_ids` の挙動が旧 curation 実装と一致
- `tests/test_metrics.py`（新規）
  - 週バケット境界（月曜始まり半開区間・`Asia/Tokyo` 変換・ts 欠落行は時系列のみ除外）
  - 結果返却率・障害数の分離（outcome 別）・旧レコード（outcome なし）の ok 扱い
  - p50/p95（nearest-rank）・auto/manual 分類
  - ゼロヒット: outcome=ok のみ対象、全件 group 後に last_ts 降順 50 件
  - `created_at` の YAML datetime / ISO 文字列両型の正規化
  - 未返却判定が curation の referenced 抽出と一致（同一 fixture）
  - キル基準 3 値判定: 完了週 4 週未満で inconclusive、4 完了週連続未満で proxy_breached、進行中の週を含めない
- `tests/test_webui.py` に追加
  - 認証（ui_password 設定時に cookie なし → 401）
  - usage / eval-history 不在・全行破損で 200 + 空構造
  - 壊れた YAML ファクト 1 件が混在しても 200（skipped_files に計上）
- `tests/test_eval_history.py`（新規）
  - `compute_summary` の値が従来 render_markdown の集計と一致
  - 追記形式（provenance フィールド含む）と `--no-history`、追記失敗時に評価が成功すること
- `tool_search` の outcome 記録: 正常 / degraded / 例外の各経路で outcome と latency_ms が記録されること
- 回帰: 既存 curation テスト一式（read_usage / referenced 抽出の移動に対して）

## 8. Phase 2 布石（引用計測 — 本フェーズでは実装しない）

- MCP ツール `plk_cite(search_id: str, fact_ids: list[str], context: str | None)` を追加し、
  エージェント動線（CLAUDE.md ガイドライン）に「検索結果を実際に判断へ使ったら plk_cite する」を追記する。
  `search_id` は Phase 1 で検索ログと `plk_search` 応答に導入済み（§2 対象 5）の相関 ID を**必須**で渡す。
  これにより「複数検索後の遅延引用」「1 検索に対する複数 cite」を重複なく検索へ対応付けられる
- usage.jsonl に `{"tool": "plk_cite", "search_id": "...", "fact_ids": [...], "client": ...}` を追記
- ダッシュボードは §4 に「引用率（cite された search_id 数 ÷ ヒットあり検索数）」
  「ファクト別引用 top/ワースト」「返却済み未引用ファクト」を追加
- これによりキル基準の「引用が週 3 回未満」が実測になり、§4④ の proxy 表示を
  `citations` ベースの正式判定（保守時間の入力手段は Phase 2 で別途検討）に置換する

## 9. 運用メモ

- usage.jsonl は追記専用で全読みしている。1 万行を超えた頃（目安 数 MB）に月次ローテーションを検討
- eval は手動実行のまま（Ollama + reindex 前提のため cron 化しない）。コーパスが大きく変わったら回す運用
