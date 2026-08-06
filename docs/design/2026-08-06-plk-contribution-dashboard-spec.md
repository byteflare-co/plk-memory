# PLK 意思決定貢献ダッシュボード再設計仕様

> Status: implemented
> Date: 2026-08-06
> Scope: Web UI `利用状況` と `/ui/api/metrics` の追加契約

## 1. 結論

`利用状況` の既定画面は、PLK の全機能を並べるダッシュボードではなく、運用責任者が次の3点を判断するための画面にする。

1. PLK を使った判断で、強い影響が継続して報告されているか。
2. その結論を出せるだけの計測がそろっているか。
3. 今週、最初に何を行うべきか。

主画面は `結論 -> 根拠3指標 -> 4週推移 -> 次に行うこと1件` の4ブロックだけにする。検索基盤、検索方式、コーパス管理の情報は、同じ `利用状況` 内の詳細ビューへ分離する。

## 2. 背景と現行課題

現行画面は、次の異なる判断材料を1ページへ混在させている。

- 意思決定への影響
- 計測の定着
- 検索基盤の信頼性
- Graph と Embed の検索品質比較
- コーパスとファクトの管理
- 0件検索や未返却ファクトの改善リスト

その結果、全期間、直近7日、直近4完了週の数値が同列に並び、「PLK は意思決定へ貢献しているか」という問いへの回答が埋もれている。`実運用ゲート 3/5` も、PLK 全体の価値、Graph 層の採否、基盤の健全性を加算可能な単一スコアのように見せてしまう。

現行の継続判定には、表示と実装の不整合もある。運用契約は「4完了週で毎週3件以上、計測欠損なし」を条件とするが、現行実装は4週を完全計測できた場合、1週でも3件以上なら `observed_ok` になり得る。例えば `[0, 1, 3, 0]` も基準内になる。この不整合は画面再編と同時に修正する。

## 3. ユーザーと利用場面

### 主利用者

PLK の運用責任者。

### 主な利用場面

- 週次レビューで、PLK の判断価値を継続観測する。
- 計測不足と価値目標未達を区別する。
- 今週直す対象を1件選ぶ。

### 成功条件

- 10秒以内に「現在の判定」「判定理由」「証拠の確かさ」が分かる。
- 30秒以内に最優先の改善対象へ移動できる。
- 画面を下まで読まなくても主目的を達成できる。

## 4. 表現上の原則

この画面が扱う値は、エージェントが PLK の利用と影響を記録した観測値である。因果効果や判断の正しさを証明するものではない。

主画面には次の注記を常時表示する。

> PLKを使ったことと影響をエージェントが記録した観測値です。因果効果や判断の正しさは示しません。

用語は次のように統一する。

| 避ける表現 | 採用する表現 |
|---|---|
| 効果を証明 | 影響を観測 |
| 採用された判断 | PLK利用報告あり |
| 強い貢献 | 強い影響の報告 |
| 貢献率 | 計測済み判断内の強い影響報告率 |
| 未計測を不採用として扱う | 未計測として分離する |

## 5. 情報構造

上位ナビゲーションの `Facts / 利用状況` は維持する。`利用状況` 内に次の第2階層を設ける。

| ビュー | 役割 | 既定表示 |
|---|---|---|
| 判断価値 | 貢献の観測状態、根拠、次に行うこと | Yes |
| 検索品質 | 返却率、障害、遅延、検索方式評価、0件検索 | No |
| データ状態 | namespace、未返却、ファクト別観測、読み込み状態 | No |

`計測` は独立ビューにしない。観測カバレッジは判断価値の信頼性なので、`判断価値` の概要と詳細に置く。client 別計測状況も `判断価値` の詳細へ含める。

## 6. 既定画面「判断価値」

### 6.1 ヘッダー

- H1: `意思決定への貢献`
- 補足: `PLK検索が、行動変更・誤り防止・確認補強につながったという報告を確認します。`
- 右側: 最終集計日時、低強調の `更新` ボタン
- 判定期間は常に直近4完了週。進行中の週は参考表示に限り、判定へ含めない。

### 6.2 観測状態カード

最も強く表示するのは、PLK 全体の停止可否ではなく、`意思決定価値の観測状態` である。

| API status | 表示 | 条件 | 次の行動 |
|---|---|---|---|
| `observed_sustained` | 4週価値目標を達成（観測上） | 4完了週すべて判定可能で、毎週3件以上 | 観測を継続する |
| `target_not_met` | 4週価値目標は未達 | 4完了週すべて判定可能だが、1週以上が3件未満 | 未達要因を1件改善する |
| `insufficient_data` | データ不足 — 判定保留 | 対象週不足、検索なし、または計測欠損あり | 計測を完成させる |

4週すべてが3件未満でも、この自己申告値だけで PLK 全体の `凍結候補` とは自動判定しない。凍結は、価値目標未達に加えて保守負担超過など独立した根拠があり、人がレビューするときだけ検討する。

状態判定はfail-closedとし、`insufficient_data` を最優先する。4完了週がすべてevaluableな場合だけ、4/4週達成を `observed_sustained`、0〜3/4週達成を `target_not_met` とする。

状態カードには次を表示する。

- 状態ラベル
- 1文の判定理由
- 不足している証拠、または未達条件
- `判定基準を見る` disclosure
- 自己申告値であることの常時注記

現行値を使った表示例は次のとおり。

> データ不足 — 判定保留
> 4完了週のうち、判定可能な週がそろっていません。直近7日の観測カバレッジは365/373（97.9%）です。

### 6.3 根拠3指標

主画面へ置く指標は次の3つだけにする。

| 指標 | 表示例 | 補足 |
|---|---|---|
| 直近7日の観測カバレッジ | `97.9%`、`365 / 373検索` | 全正常ヒット検索が対象 |
| 判定可能な完了週 | `1 / 4週`、`判定不能3週` | 未計測週を0件扱いしない |
| 直近完了週の強い影響報告 | `49件 / 基準3件` | auto-guideline の有効decisionのみ |

総検索数、全期間の採用件数、全期間の強い影響件数、有効ファクト数、実運用ゲートの合算値は置かない。採用率と強い影響報告率も、計測済み判断だけを分母にする選択欠損があるため主画面には置かない。

### 6.4 4週推移

見出しは `週ごとの強い影響の報告` とする。

- 直近4完了週を棒グラフで表示する。
- `行動を変更` と `誤りを防止` を積み上げる。
- 週3件の基準線を表示する。
- 同じ週の観測カバレッジを、グラフ直下の帯または行で表示する。
- 計測欠損週は `0件` と表示せず、`判定不能` と表示する。
- 進行中週を出す場合は破線と `今週途中` を付け、判定へ含めない。
- 二重Y軸は使わない。
- `データ表を表示` で、週、強い影響の内訳、対象検索数、計測済み検索数、カバレッジ、週次判定を確認できる。

### 6.5 次に行うこと

既定表示は最優先の1件だけにする。複数件をカードで並べない。履歴不足の場合は「改善」ではなく、観測継続を次の行動として示す。

優先順位は次のとおり。

1. 計測欠損
2. 4完了週の履歴不足
3. 完全計測できた週の価値目標未達
4. `stale / conflict / insufficient` の不採用理由
5. 再発した0件検索

表示例:

> 最優先: 未計測8件を確認
> 直近7日の観測カバレッジを100%へ近づけると、4週判定を信用できる状態になります。

CTA は1つだけ表示し、`未計測を確認`、`未達週を見る`、`0件検索を見る` など対象に応じて切り替える。ほかの候補は `ほか2件` から詳細へ移動する。

基盤障害が発生中の場合は、この改善カードと混ぜず、ページ上部のグローバル警告として表示する。

## 7. 詳細ビュー

### 7.1 判断価値の詳細

- `changed_action / prevented_error / confirmed / none` の内訳
- 不採用理由
- client 別観測カバレッジ
- 計測欠損と無効レコード
- 期間、分子、分母、サンプル数を明示した補助率

### 7.2 検索品質

- 直近7日の返却率
- failure rate、p50、p95
- Graph / Embed / rg の同一run評価
- 評価日時と期限切れ状態
- 0件検索。既定は再発順の上位5〜10件で、全件は disclosure
- Graph 層の継続・凍結判断はここだけに表示し、PLK 全体の価値判定へ混ぜない

### 7.3 データ状態

- namespace / kind の分布
- 読み込み失敗
- 未返却ファクト
- ファクト別の観測利用
- 既定は上位5〜10件で、全件は disclosure
- ファクトはIDではなく statement を主表示にする

現行のファクト別 `observed_use_rate = used_decisions / returned_searches` は分子と分母の単位が一致しないため、そのまま率として表示しない。将来表示する場合は、分母を「そのファクトが候補に含まれた distinct measured decisions」、分子を「実際に使われた distinct decisions」に変更する。

## 8. API追加契約

既存の `contribution`、`kill_criteria`、`operational_readiness` は後方互換のため当面維持する。UI は文字列化された `gate.current` を解析せず、新しい `decision_value` を使う。

```json
{
  "decision_value": {
    "status": "observed_sustained",
    "primary_reason_code": "complete",
    "blockers": [],
    "scope": {
      "recent_coverage": "all_hit_searches",
      "weekly_value": "auto_guideline_only"
    },
    "observation_started_at": "2026-07-27T00:00:00+09:00",
    "recent": {
      "days": 7,
      "measurable_searches": 373,
      "resolved_searches": 365,
      "measurement_rate": 0.9785,
      "minimum_searches": 10,
      "target_rate": 0.9
    },
    "four_week": {
      "required_weeks": 4,
      "evaluable_weeks": 4,
      "target_met_weeks": 4,
      "weekly_target": 3
    },
    "weekly": [
      {
        "week": "2026-07-27",
        "in_progress": false,
        "auto_measurable_searches": 52,
        "auto_resolved_searches": 52,
        "auto_measurement_rate": 1.0,
        "changed_action_decisions": 24,
        "prevented_error_decisions": 25,
        "strong_decisions": 49,
        "target": 3,
        "target_met": true,
        "evaluable": true,
        "unevaluable_reasons": []
      }
    ],
    "next_action": {
      "code": "record_missing_decisions",
      "count": 8,
      "client": "codex",
      "destination": "decision_measurement"
    }
  }
}
```

`weekly` は、少なくとも次の3状態を区別して返す。

- 正常週: `evaluable=true`、`unevaluable_reasons=[]`
- 未計測週: `evaluable=false`、`unevaluable_reasons` に `measurement_gap`
- 対象検索なし: `evaluable=false`、`unevaluable_reasons` に `no_eligible_searches`

### 8.1 計算定義

- eligible search: `outcome=ok AND hits>0 AND search_idあり`
- 観測カバレッジ: unique resolved `search_id` / unique eligible `search_id`
- strong decision: 有効で一意な `decision_id` かつ `effect` が `changed_action` または `prevented_error`
- 週次strong対象: `reason=auto-guideline` の検索を1件以上linkし、その自動検索が返した `fact_ids` とdecisionの `used_fact_ids` が1件以上交差するdecision
- 週: JSTの月曜00:00以上、翌月曜00:00未満
- 週次判定のcohort: `search.ts` を基準にした自動検索週
- decisionのcohort帰属: linkしたeligible auto searchのうち、そのsearchの `fact_ids` とdecisionの `used_fact_ids` が交差し、かつ `decision.ts` 以下であるsearchから、最も新しい `search.ts` の週
- 1 decisionが複数searchへlinkしても1件
- 1 decisionが複数週のsearchへlinkしても、上記cohortへ1件だけ帰属させる
- 今週は参考値で、4週判定から除外
- missingを `none` や0へ補完しない
- timestamp欠落または無効recordは週次から除外し、データ品質詳細で件数を表示する

週ごとの `evaluable` は、次をすべて満たす場合だけ `true` とする。

```text
auto_measurable_searches > 0
AND auto_resolved_searches == auto_measurable_searches
AND week_scoped_data_quality_blockers == 0
```

対象週のsearchへlinkできる無効decision、または対象週へ帰属し得る競合search IDは、その週のdata quality blockerとして `evaluable=false` にする。週を特定できないlegacy/invalid recordはglobal data quality warningへ出し、根拠なく現在の4週すべてを無効にはしない。直近7日の90%目標は現在の計測運用を監視する補助指標であり、4週価値判定の完全観測条件を緩和しない。

coverage はsearch単位、strongはdecision単位なので、同じ率やファネルとして描かない。decisionは検索週cohortへ帰属させ、週次coverageと同じ観測期間で評価する。`decision.ts` より未来のsearchしかlinkしていないdecisionは無効recordとして除外する。

自動検索をlinkしただけではauto strongへ数えない。その自動検索の返却factが実際の `used_fact_ids` に含まれる場合だけ、自動検索由来の影響として数える。

### 8.2 blockers と primary_reason_code

欠損理由は同時に複数発生し得るため、APIは `blockers[]` にすべて返し、UIの最優先表示用に `primary_reason_code` を1つ返す。blockerは最低限 `{code, count, target}` を持ち、`target` は不要な場合nullとする。

最低限、次のcodeを提供する。

- `complete`
- `insufficient_history`
- `measurement_gap`
- `no_eligible_searches`
- `weekly_target_missed`
- `invalid_timestamp`
- `future_timestamp`
- `duplicate_search_id`
- `duplicate_decision_id`

`primary_reason_code` は、計測不能、履歴不足、価値目標未達の順で選ぶ。具体的な優先順位は次のとおり。

1. invalid/conflicting record
2. measurement gap
3. no eligible searches
4. insufficient history
5. weekly target missed
6. complete

### 8.3 next_action

`next_action` は表示文言ではなくcodeごとのtagged unionとして返し、UI文言はUI側で管理する。

| code | 必須field | 対象 | destination |
|---|---|---|---|
| `record_missing_decisions` | `count`, `client` | 未計測検索 | `decision_measurement` |
| `repair_invalid_records` | `count`, `record_type` | 無効・競合record | `data_quality` |
| `observe_more_weeks` | `weeks_remaining` | 完了週不足 | `decision_value` |
| `verify_auto_search_flow` | `weeks`, `observation_started_at` | 観測開始後の対象検索なし | `decision_measurement` |
| `inspect_below_target_week` | `week`, `strong_decisions`, `target` | 価値目標未達週 | `decision_breakdown` |
| `review_no_use_reason` | `reason`, `count` | stale/conflict/insufficient | `decision_breakdown` |
| `review_repeated_zero_hits` | `count` | 再発0件検索 | `search_quality` |
| `none` | なし | 優先対応なし | null |

`next_action` は1件だけ返す。優先順位は、無効record、計測欠損、履歴不足、価値目標未達、不採用理由、再発0件検索の順とする。

### 8.4 record正規化と時間境界

- 同一 `search_id` の完全に同一な再記録は1件に正規化する
- 同一 `search_id` でpayloadが競合する場合は、そのIDを判定対象から除外しblockerへ記録する
- 同一 `decision_id` の完全に同一なreplayは1decisionに正規化する
- 同一 `decision_id` でpayloadが競合する場合は、そのIDを判定対象から除外しblockerへ記録する
- `generated_at` より5分を超えて未来のtimestampは判定対象から除外しblockerへ記録する
- timestamp欠落またはparse不能recordは判定対象から除外しblockerへ記録する
- UIのstaleは、最後に成功したfetchから15分を超えた状態と定義する。自動で成功値を更新したようには見せず、`15分以上更新されていません` と再読込を表示する
- 再発0件検索は、直近30日で同一query hashが2回以上0件になったものと定義する。件数降順、同数なら最終発生日時の新しい順とする
- `insufficient_history` は、明示的な `observation_started_at` から完了週が4週経過していない場合だけ使う
- `observation_started_at` は、search/decision telemetry契約を有効化した時刻をmigrationまたは設定値で固定する。最初に偶然記録されたevent時刻から推測しない
- 観測開始後の完了週にeligible auto searchが0件なら `no_eligible_searches` とし、`verify_auto_search_flow` を返す
- 観測開始前の週は4週判定の値を0件にせず、`pre_observation` として判定対象外にする

## 9. PLK全体の継続判断との分離

`decision_value.status` は意思決定価値の観測状態であり、PLK 全体の継続・停止判定ではない。

PLK 全体の継続判断には、少なくとも次が必要である。

- 意思決定価値の観測状態
- 保守負担
- 検索基盤の信頼性
- 必要に応じて検索方式ごとの費用対効果

現時点では保守時間が計測されていないため、総合継続判定を自動表示しない。詳細に `保守負荷: 未計測` と明示する。保守時間、個別decisionドリルダウン、任意期間切替は今回の非スコープとする。

## 10. レスポンシブとアクセシビリティ

- 961px以上: 根拠3指標を3列
- 721〜960px: 2列
- 720px以下: 1列
- 主KPIと改善カードは横スクロールさせない
- 詳細表だけoverflowを許可する。可能なら狭幅ではカードへ変換する
- 第2階層タブは `role=tablist` とし、Left/Right/Home/Endを実装する
- 色だけで状態を伝えず、文言と記号を併記する
- 更新状態は `aria-live` で通知する
- チャートには `title / desc` と同値のデータ表を用意する
- 操作対象は44px以上を目安にする
- `prefers-reduced-motion` を尊重する
- 200% zoomで主要内容が欠落しない
- 実装後にキーボード、読み上げ順、コントラストを実ブラウザで確認する

## 11. 状態とエラー

最低限、次を明示的に設計する。

- loading: 画面構造を保ったskeletonまたは短い読込表示
- empty: 検索データなし。利用開始条件を説明する
- insufficient: データはあるが4週判定不能。不足理由を示す
- error: 前回値を残す場合は、全指標へ `更新失敗` と最終成功時刻を付け、取得失敗と再試行を示す
- stale: 最終集計日時が一定期間を超えた場合に警告する

## 12. 成果物

今回の実装成果物は次の5点とする。

1. この仕様書を設計のSoTとして更新する。
2. desktop 1440pxとmobile 390pxの高忠実度モックを作る。
3. `decision_value` の純粋集計と後方互換なAPI追加を実装する。
4. `判断価値 / 検索品質 / データ状態` の3ビューへUIを再編する。
5. 単体テスト、Web UI契約テスト、実ブラウザ確認の証跡を残す。

モックは少なくとも `データ不足` と `4週価値目標を達成（観測上）` の2状態を含める。Figmaは共同編集が必要になった場合だけ使用し、今回の必須成果物にはしない。既存のdark theme、CSS token、素DOM/SVG実装を維持し、視覚ブランドの刷新は行わない。

### 実装段階

- Phase A: 既存APIのまま画面を3ビューへ再編し、不要な主画面情報を退避する
- Phase B: `decision_value` を追加し、正しい3状態、週次内訳、次の改善を表示する
- Phase AとBを今回の完成範囲とする
- Phase C: 保守時間、個別decisionドリルダウン、任意期間切替。別案件とする

## 13. 受入条件

### 情報設計

- 1280pxの初期viewportで、状態、根拠3指標、4週推移の冒頭が見える
- 既定画面に全期間の累積値、実運用ゲート表、全件テーブルを置かない
- 最優先の改善は1件だけ表示する
- PLK全体、Graph層、検索基盤の判定を混ぜない
- すべての数値に期間を示し、率には分子・分母を併記する

### 計算

- `[3, 3, 3, 3]` かつ全週完全計測だけが `observed_sustained`
- `[0, 1, 3, 0]` かつ全週完全計測は `target_not_met`
- いずれかの週に計測欠損があれば `insufficient_data`
- 0件と未計測を区別する
- 進行中週を4週判定へ含めない
- 複数searchへlinkした同一decisionを1件だけ数える
- 複数週のsearchへlinkしたdecisionを、最も新しい有効なauto searchの週へ1件だけ帰属させる
- auto searchの返却factと `used_fact_ids` が交差しないdecisionをauto strongへ含めない
- `confirmed` は利用報告へ含めるがstrongへ含めない
- `none` と未計測を混ぜない
- タイムゾーン境界をJSTでテストする
- 直近7日90%と4完了週100%の役割を混同しない
- search/decisionの重複IDについて、同一replayと競合payloadを区別する
- 5分を超える未来timestampとparse不能timestampを判定から除外する
- 直近30日で同一query hashが2回以上のときだけ再発0件検索とする

### UIとアクセシビリティ

- 3状態、loading、empty、error、staleをfixtureで確認する
- 390pxと720pxで主内容に横スクロールが発生しない
- タブをキーボードだけで移動できる
- グラフと同じ情報をテキストまたは表で取得できる
- 状態は色なしでも識別できる
- 更新中と取得失敗を支援技術へ通知できる
- 実ブラウザでdesktop/mobileのスクリーンショットを取得し、保存した画像を確認する

### 後方互換性

- 既存metricsレスポンスのfieldを削除しない
- 既存の空レスポンスと認証動作を維持する
- 既存テストを文言依存から、構造、データ契約、安全なDOM、aria中心へ更新する

## 14. 非スコープ

- 因果推論やA/Bテストによる効果証明
- PLK全体の自動停止判定
- 保守時間の収集UI
- 個別decisionの生ログ表示
- 任意期間セレクター
- Figma共同編集ボード
- ビジュアルブランドの刷新

## 15. サブエージェント間の主要な裁定

| 論点 | 採用した結論 | 理由 |
|---|---|---|
| 主KPI | coverage、判定可能週、直近完了週strong | 率の誤読と累積値の肥大を避ける |
| 採用率/strong率 | 詳細へ退避 | 計測済み判断だけが分母で選択欠損がある |
| 画面構造 | 判断価値 / 検索品質 / データ状態 | 貢献、検索方式、コーパス管理を分離する |
| 計測ビュー | 独立させない | 判断価値の信頼性として同じ文脈で読むため |
| 保守時間 | 価値statusへ含めない | 価値観測と費用対効果は別軸のため |
| 凍結候補 | 自動判定しない | 自己申告値だけで停止を促さないため |
| 既存3/5 | 主画面から除外 | 異質なゲートの合算が誤解を生むため |
| 今回の範囲 | Phase A+B | 見やすさだけでなく判定定義の不整合も直すため |
