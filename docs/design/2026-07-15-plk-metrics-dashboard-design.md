# plk-memory メトリクスダッシュボード設計（Phase 1）

日付: 2026-07-15
ステータス: 設計承認待ち
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

1. 集計モジュール `src/plk_memory/metrics.py`（純粋関数）
2. Web UI エンドポイント `GET /ui/api/metrics`
3. フロントエンド: 既存 UI に「Metrics」ビューを追加（外部ライブラリなし、SVG 直描画）
4. `run_eval.py` の結果を `~/.plk/eval-history.jsonl` へ追記し、時系列表示できるようにする

### 非スコープ

- 引用計測・引用率表示（Phase 2）
- 週次通知・Slack/Notion 連携（指標が固まってから判断）
- usage.jsonl のローテーション（当面 280 行、10MB 到達は数年先。§9 に運用メモのみ）
- PostgreSQL backend の usage 記録。現状 `PostgresAppServices` は UsageLog を書いておらず、
  本ダッシュボードは Git backend のローカル運用（現行構成）を前提とする。
  postgres 移行時は usage 記録の実装とともに集計元を差し替える（metrics.py は入力が
  レコード list なので集計ロジックは再利用可）。

## 3. データソース

### 3.1 usage.jsonl（既存・変更なし）

```json
{"ts": "2026-07-15T03:16:36+00:00", "client": "codex", "tool": "plk_search",
 "query": "...", "hits": 10, "latency_ms": 400, "reason": "auto-guideline",
 "fact_ids": ["01KW..."]}
```

- `tool` は `plk_search` 以外（history/invalidate 等）も混在する。検索系集計は `tool == "plk_search"` のみ対象
- 壊れた行・ts 欠落行は skip（`curation.read_usage` / `_parse_ts` の既存挙動を踏襲）
- `reason == "auto-guideline"` を auto、それ以外を manual と分類（既存 curation と同一定義）

### 3.2 facts（既存・変更なし）

`FactService.list_posts()` の frontmatter を使う。参照フィールド: `id` / `namespace` / `kind` / `status` / `created_at` / `invalidated_at` / `statement`。

### 3.3 eval-history.jsonl（新規）

`run_eval.py` 実行時に 1 ランナーにつき 1 レコード追記する:

```json
{"ts": "2026-07-15T10:00:00+09:00", "runner": "graph(triplet)",
 "queries": 25, "hit5": 21, "hit5_rate": 0.84, "mrr": 0.71,
 "corpus_active": 48, "corpus_total": 55}
```

- パスは `Settings.eval_history_path: Path = Path.home() / ".plk" / "eval-history.jsonl"`
- `run_eval.py` に `--no-history` フラグを追加（デフォルトは追記する）。既存の `--out` / stdout 出力は不変
- 集計値は既存 `render_markdown` 内の agg と同じ計算（hit@5 数・率・平均 MRR）を関数に切り出して共用する

## 4. 指標定義

すべて `metrics.py` の `build_metrics(usage: list[dict], posts, eval_history: list[dict], *, now: datetime) -> dict` が返す。
時刻バケットはサーバーのローカルタイムゾーン（実運用は JST）に変換してから日付で切る。週は月曜始まり（ISO week）。

### ① 利用実態（`search`）

| 指標 | 定義 |
|---|---|
| 週別検索数 | 直近 12 週。auto / manual の積み上げ |
| 週別ヒット率 | `hits > 0` の件数 ÷ 検索数（検索 0 の週は null） |
| クライアント別内訳 | 全期間の `client` 別検索数 top 10 |
| レイテンシ | 直近 7 日と全期間それぞれの p50 / p95（`latency_ms` 欠落は除外） |

### ② ゼロヒットクエリ（`zero_hit`）

- `tool == "plk_search"` かつ `hits == 0` のレコードを新しい順に最大 50 件
- 同一 query 文字列は 1 行にまとめ `count` と最終発生時刻を持つ
- 各行: `query` / `count` / `last_ts` / `clients`（発生クライアントの集合）

### ③ コーパス健全性（`corpus`）

| 指標 | 定義 |
|---|---|
| ステータス別件数 | active / invalidated |
| namespace 別件数 | active のみ、件数降順 |
| kind 別件数 | active のみ（philosophy / logic / knowhow） |
| 週別追加数 | `created_at` を週で切った直近 12 週 |
| 未参照ファクト | curation と同一定義（usage に fact_id が一度も現れない active）。件数と最大 30 件の一覧 |

### ④ キル基準との距離（`kill_criteria`）

- 直近 4 週それぞれの「ヒットあり検索数」（週次）と閾値 3 を返す
- `threshold_weekly_hits = 3` は `metrics.py` の定数とし、`run_report.py` の KILL 文言とコメントで相互参照する
- 4 週連続で閾値未満なら `breached: true`

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
    "weekly": [{"week": "2026-07-13", "auto": 12, "manual": 3, "hit": 13, "total": 15}],
    "clients": [{"client": "codex", "count": 180}],
    "latency": {"last7d": {"p50": 400, "p95": 3400, "n": 21}, "all": {"p50": 380, "p95": 2900, "n": 268}}
  },
  "zero_hit": [{"query": "...", "count": 3, "last_ts": "...", "clients": ["codex"]}],
  "corpus": {
    "status": {"active": 48, "invalidated": 7},
    "namespaces": [{"namespace": "plk.domain.tax", "count": 12}],
    "kinds": {"philosophy": 3, "logic": 20, "knowhow": 25},
    "weekly_added": [{"week": "2026-07-13", "count": 4}],
    "unreferenced": {"count": 9, "items": [{"id": "...", "namespace": "...", "statement": "..."}]}
  },
  "kill_criteria": {"threshold_weekly_hits": 3, "weeks": [{"week": "2026-06-22", "hits_searches": 5}], "breached": false},
  "eval": {"graph(triplet)": [{"ts": "...", "hit5_rate": 0.84, "mrr": 0.71, "corpus_active": 48}]}
}
```

- エラー処理: usage / eval-history が存在しない場合は空扱いで 200 を返す（500 にしない）。
  facts 読込失敗はファイル単位 skip（`list_posts` 既存挙動）

## 6. モジュール設計

### 6.1 `src/plk_memory/metrics.py`（新規）

```
read_eval_history(path: Path) -> list[dict]        # read_usage と同型の寛容パース
build_metrics(usage, posts, eval_history, *, now) -> dict
  ├─ _search_stats(usage, now)
  ├─ _zero_hit_queries(usage)
  ├─ _corpus_stats(posts, usage)     # 未参照判定は curation の referenced 抽出を関数化して共用
  └─ _kill_criteria(usage, now)
```

- 全関数純粋（I/O なし、`now` 注入）でユニットテスト可能にする
- `curation.py` からは「referenced fact_ids 抽出」を `metrics.py` 側の共通関数
  `referenced_fact_ids(usage) -> set[str]` に移し、curation が import する
  （aggregate の外部仕様・レポート出力は不変。既存 curation テストで回帰確認）
- `read_usage` は curation.py に既存のものを import して使う（移動しない）

### 6.2 `webui.py`

- `build_ui_router` に `GET /ui/api/metrics` を追加
- ハンドラは `settings.usage_log_path` と `settings.eval_history_path` を読んで `build_metrics` に渡す
- facts メタデータは status を問わず全件必要（`ui_list_facts` は表示用整形のため不適）なので、
  facade に `ui_metrics_posts()`（frontmatter dict の list を返す薄いメソッド）を追加する。
  `AppServices`（Git backend）は `FactService.list_posts()` を返し、
  `PostgresAppServices` は空 list を返すスタブとする
  （UI は corpus ブロックだけ「backend 未対応」表示にし、usage 由来の他ブロックは表示する）

### 6.3 `scripts/eval/run_eval.py`

- 集計計算を `compute_summary(queries, runner_results) -> dict[runner, {hit5, hit5_rate, mrr}]` に切り出し、
  `render_markdown` と履歴追記の両方から使う
- `main()` 末尾で `--no-history` でなければ `settings.eval_history_path` に追記

### 6.4 フロントエンド（`static/index.html` / `static/app.js`）

- ヘッダーに「Facts / Metrics」のビュー切替を追加（タブ。既存の一覧＋詳細パネルは Facts ビューとしてそのまま）
- Metrics ビューは初回表示時に `/ui/api/metrics` を 1 回 fetch し、再取得ボタンを置く
- 描画コンポーネント（すべて素の SVG / DOM。外部ライブラリ禁止を維持）:
  - スタットタイル行: 総検索数・直近 7 日ヒット率・active ファクト数・キル基準ステータス
  - 積み上げ棒: 週別検索数（auto/manual）
  - 折れ線: 週別ヒット率、eval hit@5 率 / MRR（runner 別系列）
  - 横棒: namespace 別件数、クライアント別件数
  - テーブル: ゼロヒットクエリ、未参照ファクト
- **XSS**: query 文字列・statement は必ず `textContent` で挿入する（innerHTML 禁止。
  既存 UI の facts 描画と同方針）
- 空状態: eval 未実行・usage なしの各ブロックに案内文を出す

## 7. テスト計画

- `tests/test_metrics.py`（新規）
  - 週バケット境界（月曜始まり・タイムゾーン変換・ts 欠落 skip）
  - ヒット率・p50/p95・auto/manual 分類
  - ゼロヒットの dedup と count
  - 未参照判定が curation と一致すること（同一 fixture で両方を呼ぶ）
  - キル基準: 4 週連続未満で breached、3 週なら false
- `tests/test_webui.py` に追加
  - 認証（ui_password 設定時に cookie なし → 401）
  - usage / eval-history 不在で 200 + 空構造
- `tests/test_eval_history.py`（新規）
  - `compute_summary` の値が従来 render_markdown の集計と一致
  - 追記形式と `--no-history`
- 回帰: 既存 curation テスト一式（referenced 抽出の移動に対して）

## 8. Phase 2 布石（引用計測 — 本フェーズでは実装しない）

- MCP ツール `plk_cite(fact_ids: list[str], context: str | None)` を追加し、
  エージェント動線（CLAUDE.md ガイドライン）に「検索結果を実際に判断へ使ったら plk_cite する」を追記する
- usage.jsonl に `{"tool": "plk_cite", "fact_ids": [...], "client": ...}` を追記（スキーマ拡張不要）
- ダッシュボードは §4 に「引用率（cited 検索 ÷ ヒットあり検索）」「ファクト別引用 top/ワースト」を追加
- これによりキル基準の「引用が週 3 回未満」が実測になり、§4④ の `hits_searches` を `citations` に置換する

## 9. 運用メモ

- usage.jsonl は追記専用で全読みしている。1 万行を超えた頃（目安 数 MB）に月次ローテーションを検討
- eval は手動実行のまま（Ollama + reindex 前提のため cron 化しない）。コーパスが大きく変わったら回す運用
