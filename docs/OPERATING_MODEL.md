# PLK メモリ 実運用モデル

> Status: active operating contract
> Baseline: 2026-07-31
> Architecture: [`BLUEPRINT.md`](BLUEPRINT.md)

> [!IMPORTANT]
> 2026-08-20以降、検索・decision・operation traceの指標は基盤の健康診断として継続するが、
> PLKの実務価値はそれだけで判定しない。主評価は、人間レビュー済みの実務ケースで
> 想起・取得・適用・行動・改善を追う[`EVALUATION_MODEL.md`](EVALUATION_MODEL.md)へ移行する。
> v2 pilotのbaselineが揃うまで、以下の自己申告ベースの貢献目標は参考値として扱う。

Chrome profile pilotの継続・見直し・rollbackは`workflow_review.py pilot-status`で、5件の人間レビュー、variant coverage、Tier A行動証拠、failure→change→同一variant replayを確認してから判断する。Git/Markdownがprimary、PostgreSQLはtarget/alternate backendであり、reviewed E2Eを価値の主評価、旧telemetryを基盤健康の補助評価として扱う。rollbackは表示の判断を戻すだけで、private review JSONLを削除・上書きしない。

## 1. 理想状態

理想のPLKは「たくさん覚えているデータベース」ではない。次の状態を満たす判断補助系である。

- **必要な場面で自動的に呼ばれる**: 人が検索を思い出さなくても判断前に動く。
- **判断を変える**: 返却件数ではなく、行動変更・誤り防止・確認補強が観測できる。
- **選択的に覚える**: 一般知識や可変値を溜めず、再発し判断差分を生む最小主張だけを残す。
- **一次情報に従う**: PLKはSoTの代替ではなく、どこを確認しどう判断するかを導く。
- **壊れても業務を止めない**: 検索・計測はfail-soft、正本と外部操作はfail-closedにする。
- **自分で劣化を示す**: 未計測、古い評価、0結果、遅延、dead letterを隠さない。
- **価値がなければ軽くする**: Graph層が単純埋め込みに勝たなければ凍結し、知識規約と動線は残す。

North Starは、**計測可能な自動検索のうち、強い貢献へつながった最終判断が週次で継続すること**。
ファクト数や検索回数そのものはNorth Starにしない。

## 2. 実運用ゲート

| ゲート | 目標 | 意味 |
|---|---:|---|
| 検索→最終判断の計測 | 直近7日で90%以上、最低10ヒット検索 | 未計測を未使用と誤認しない |
| client定着 | 3回以上使った各clientで計測率90%以上 | Codexだけの局所成功にしない |
| 強い貢献 | 4完了週で毎週3件以上、計測欠損なし | 利用量でなく判断価値を確認する |
| reliability | 直近7日 failure 1%以下、p95 5秒以下 | 判断動線を遅く・不安定にしない |
| retrieval eval | 30日以内、同一runでgraphがembed以上 | 複雑な検索層の存在理由を証明する |
| index health | stale=false、dead letter=0 | 正本と派生索引の乖離を残さない |
| content contract | eval expectedの100%がactive | 無効factを正解とするfalse greenを防ぐ |

Web UIの「実運用スコアカード」は上5項目を継続表示する。index healthとcontent contractは
`plk_status`と評価実行時のfail-closed検証で確認する。

## 3. 2026-07-31 baseline

| 指標 | 実測 | 判定 |
|---|---:|---|
| service / index | health 200、stale=false、dead letter 0 | 基盤は正常 |
| corpus | active 40、invalidated 36 | 件数は参考値 |
| 検索 | 全期間443、直近7日82 | 日常利用あり |
| 直近7日結果返却率 | 100% | relevanceとは別。過信しない |
| 直近7日p95 | 4,867ms | 5秒目標内 |
| 直近7日計測率 | 49/82 = 59.8% | 90%未達 |
| client別 | Codex 49/75、Hermes 0/6、Claude Code 0/1 | 配布・実地確認が未完了 |
| 全期間の強い貢献 | 19 decisions | 価値の兆候あり |
| 評価契約 | 20 expected中17 invalidated | 旧評価は無効 |
| eval history | 0 runs | 検索品質を時系列比較できない |

このbaselineから、最初の改善単位を「評価契約100% active化」「評価履歴1 run以上」
「7日計測率90%」「利用中clientの計測定着」とする。

## 4. 運用ループ

### 判断ごと

1. 対象領域なら自動検索する。
2. 使ったfactと効果を最終判断時に1回記録する。
3. `none`が続くfactは、検索表現・適用条件・保存価値を見直す。

### 毎週10分

1. Metricsの実運用ゲートと前週差を見る。
2. 未計測clientを最初に直す。
3. 0結果の再発query、`stale/conflict/insufficient`、failureを確認する。
4. 改善は1件だけ選び、翌週同じ指標で効果を見る。
5. `plk_status`でstale、dead letter、promotion待ちを確認する。

### 月次30分以内

1. rg / embed / graphを同じquery set・同じcorpus revisionで評価する。
2. graphがembed未満なら原因を1回だけ調査し、改善根拠がなければGraph凍結候補にする。
3. 観測採用率の低いfact、長期間返却されないfact、重複・矛盾をレビューする。
4. preview retention、ログサイズ、復旧runbookを確認する。
5. 保守が週換算30分を継続して超えるなら、複雑性を削る。

## 5. 改善ロードマップ

### Now: 証拠を信用できる状態にする

- current / target / historicalを分けたブループリントを正本化する。
- invalidated factを含む評価セットをfail closedにし、現行active corpusへ更新する。
- 実運用ゲートをAPI/UIへ表示する。
- Codex / Claude Code / Hermesで検索→decision記録を各1件実地確認する。

### Next: 価値を4週間観測する

- 7日計測率90%以上を維持する。
- `none`理由と低観測採用factを需要駆動で改善・無効化する。
- 月次evalを最低1回実行し、graph vs embedを同一runで比較する。
- reindex復旧時間を実測し、runbookへ残す。

### Later: 必要になった拡張だけ行う

- 複数writerまたはtenant分離が必要になった時だけPostgreSQL cutover gateへ進む。
- stagingでRLS/IAM、two API + two worker、backup/restore、RTO/RPOを実証する。
- GitとPostgreSQLのdual writer運用は行わない。

## 6. 目標レビュー

この目標設定でPLKが実運用へ近づくと判断する。

理由は、現時点ですでに保存・検索・索引・承認・telemetryの主要機構があり、未解決なのは
「使われたか」「判断を変えたか」「複雑な検索層に価値があるか」を継続的に判定する閉ループだからである。
上記ゲートは各未解決点を観測可能にし、改善・維持・凍結の次の行動へ直接結び付く。

反対に、PostgreSQL移行、ファクト件数増加、UI機能追加だけを目標にしても、判断価値は証明できない。
したがって現在は価値検証を優先し、組織スケールの構成は明確な需要が出るまで拡張境界として保持する。

## 7. 継続・凍結判断

- **PLK全体を止める条件**: 判断前の検索動線自体が不要、または保守負担が判断価値を継続的に上回る。
- **Graphだけを凍結する条件**: 現行active corpusの同一評価でgraphがembedを継続的に上回らず、
  graph固有の利用価値も観測できない。
- **継続条件**: 計測率を満たしたうえで週3件以上の強い貢献が4週続き、保守が週30分以内。
- **判定保留**: 計測率未達、client未配布、評価期限切れ。データ不足を失敗または成功へ丸めない。

Graphを凍結しても、fact規約、Git/PostgreSQL正本、検索動線、decision telemetryは残せる。

## 8. 2026-07-31 初回改善の実測

| 改善項目 | 変更前 | 変更後 | 意味 |
|---|---:|---:|---|
| 現行ブループリント | current/target/historyの単一正本なし | 必須8領域を1文書に統合 | READMEと日付付き設計の役割を分離 |
| eval expectedのactive率 | 3/20 = 15% | 20/20 = 100% | invalidated factを正解にするfalse greenを除去 |
| eval contract | stale expectedでも実行可能 | missing/invalidated/重複queryを開始前に拒否 | 今後の再発をtestで防止 |
| eval history | 0 run | 1 run | 検索品質の時系列比較を開始 |
| 実運用ゲート表示 | 個別指標のみ | 5 gate + blockerをAPI/UI表示 | 次の改善対象を一画面で選べる |

現行20 query・active 40 factでの初回同条件評価:

| runner | hit@5 | MRR |
|---|---:|---:|
| rg | 0/20 = 0% | 0.000 |
| embed (`bge-m3`) | 20/20 = 100% | 1.000 |
| graph (`triplet`) | 19/20 = 95% | 0.925 |

Graphはembedを下回ったため、検索品質ゲートは未達である。初回観測だけで即時撤去せず、
次回の同条件評価でも上回らず、Graph固有価値も説明できなければ凍結する。
運用スコアカードの初期値は5ゲート中1ゲート達成見込みで、reliabilityのみ達成、
計測定着・client coverage・4週価値証明・retrieval evalは未達または観測不足である。
