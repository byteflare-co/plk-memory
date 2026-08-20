# PLK 評価・改善モデル

> Status: active pilot
> Date: 2026-08-20
> Scope: PLK が実務の判断と行動を改善したかを、人間レビューから段階的に自動評価へ育てる運用契約

## 1. 結論

PLK の主評価単位を、検索イベントやエージェントの自己申告ではなく、**実務上の1つの判断場面**へ変更する。

1つの評価ケースについて、次の5段階を順番に確認する。

1. **想起**: この場面で PLK を参照すべきだと認識できたか。
2. **取得**: 必要な fact が返ったか。
3. **適用**: fact を状況に合わせて正しく解釈したか。
4. **行動**: 実際の行動が期待結果と一致したか。
5. **改善**: 失敗原因を1つの改善先へ割り当て、同じケースで変更前後を比較できたか。

既存の検索件数、hit@5、MRR、decision effect、operation trace、failure、latency は廃止しない。ただし、これらは主に**検索・計測基盤の健康診断**であり、PLK が役立った証拠として単独では使わない。

## 2. なぜ現行評価だけでは足りないか

現行基盤は、検索が呼ばれたこと、返却 fact、エージェントが申告した影響、action の実行成否を記録できる。一方で、次は判定できない。

- intent 自体を記録しなかった操作で、PLK 検索が必要だったか。
- 何かが返っただけでなく、その場面に必要な fact が返ったか。
- fact を使ったという自己申告が、正しい解釈と行動につながったか。
- ツールが成功しただけでなく、業務結果が正しかったか。
- 失敗時に、trigger、retrieval、fact、適用、実行のどこを直すべきか。

したがって、現行の `changed_action` / `prevented_error` は価値の兆候として残すが、人間レビューまたは独立した外部証拠がない限り「実務価値を確認済み」とは扱わない。

## 3. 評価データの単位

### 3.1 Workflow case

評価の正本は `scripts/eval/workflow_cases.yaml` とする。各ケースには最低限、次を持たせる。

- 実務で再発する状況
- PLK 検索が必要か
- 期待する fact
- 期待する行動と、禁止する行動
- 判定に必要な証拠
- 失敗段階ごとの改善先
- ケースの出典と人間レビュー状態

静的な検索 query は workflow case の一部であり、評価全体ではない。

### 3.2 Episode

実際に発生した1回の操作、または同じ入力を使った再実行を episode と呼ぶ。episode は workflow case に紐付け、各段階を `pass` / `fail` / `unknown` / `not_applicable` で記録する。

`unknown` を失敗や成功へ丸めない。特に action の証拠がない場合、検索や自己申告が良好でも行動品質は `unknown` とする。

workflow case には期待値だけを置き、実際の episode 証拠はprivate telemetryまたはローカルreview storeへ分離する。
cookie、token、ページ本文、個人情報をcaseやreviewへ複写せず、必要最小限の構造化属性と参照IDだけを保持する。

### 3.3 証拠の強さ

| tier | 証拠 | 用途 |
|---|---|---|
| A | 実 UI・API read-back、人間確認、外部システムの確定結果 | 行動と業務結果の判定 |
| B | trace、返却 fact、構造化 action 属性 | 想起・取得・適用・実行経路の判定。業務結果の成功判定には使わない |
| C | エージェントの effect 自己申告 | 改善候補の抽出。単独で成功判定しない |

## 4. 失敗分類と改善先

| 最初に失敗した段階 | 意味 | 最初に直す対象 |
|---|---|---|
| `trigger` | 検索すべき場面を認識しなかった | client 指示、operation 分類、preflight guard |
| `retrieval` | 検索したが必要 fact が返らなかった | query bridge、fact 表現、namespace、retriever |
| `knowledge` | 必要な知識が存在しない、曖昧、矛盾、古い | fact の追加・更新・無効化 |
| `application` | fact は返ったが解釈・選択を誤った | `how_to_apply`、競合解消、agent instruction |
| `action` | 判断は正しいが実操作が違った | tool guard、引数検証、実行前確認、read-back |
| `evidence` | 正否を判定できる証拠がない | telemetry、構造化属性、review 動線 |

改善は最初に失敗した段階を1件だけ選ぶ。同時に複数層を変えると、どの変更が効いたか判断できない。

## 5. 主指標

主画面で扱う指標は、レビュー済み workflow episode に限定する。

- **E2E 成功率**: 全必須段階が `pass` の reviewed episode / 判定可能 episode
- **想起率**: 検索が必要な episode のうち、行動前に適切な検索を開始した割合
- **取得成功率**: 想起できた episode のうち、期待 fact が返った割合
- **適用成功率**: 期待 fact が返った episode のうち、期待判断へ至った割合
- **行動成功率**: 期待判断へ至った episode のうち、Tier A 証拠で期待行動と業務結果を確認した割合
- **再発率**: 改善後に同じ failure stage で再び失敗した割合
- **改善リードタイム**: 人間の訂正から、変更後の同一ケース再評価までの時間

分母、`unknown` 件数、client、workflow case、評価期間を必ず併記する。全体率だけで client 差やケース偏りを隠さない。

既存指標は次の補助ビューへ分離する。

- **計測の健康**: trace coverage、decision linkage、欠損、client 定着
- **検索器の健康**: expected fact recall、順位、latency、failure、graph vs embed
- **知識の健康**: stale、conflict、repeated none、未返却、重複

## 6. 人間介入型の改善ループ

### 随時

人間が誤りを発見したら、回答や操作結果だけを直して終わらせず、次を1件の候補として残す。

1. どの workflow case だったか。
2. 期待行動と実際の行動は何だったか。
3. 最初に失敗した段階はどこか。
4. 判定に使った証拠は何か。

新しい fact の追加は自動実行しない。失敗原因が `knowledge` の場合だけ、既存の assess、重複確認、正規化、人間承認へ渡す。

### 週次 15 分

1. 新しい失敗または `unknown` episode を最大10件レビューする。
2. 再発性と影響が高い1ケースだけ選ぶ。
3. failure stage に対応する1箇所だけ変更する。
4. 同じケースを変更前後で再実行する。
5. 改善しなければ変更を戻すか、原因分類を見直す。

### 月次 30 分

1. workflow case の偏り、古さ、重複をレビューする。
2. 実務頻度の高いケースが不足していれば追加する。
3. 静的 retrieval eval を同じ corpus revision で再実行する。
4. E2E と補助指標が逆方向なら、E2E を優先して原因を調べる。

## 7. 最初の pilot

最初のケースは、既に誤りが観測され、期待行動が明確な Chrome profile 選択とする。

- Byteflare の手続き操作では、操作前に profile 一覧を取得する。
- 指定名と大文字小文字を区別せず完全一致する1件だけを選ぶ。
- Byteflare 業務では `byteflare.co` を使い、private profile へフォールバックしない。
- 一致しない、または一意でない場合は操作を止める。
- search trace、返却 fact、選択 profile、停止または操作結果を証拠として残す。
- ground truthとなるvariant定義は評価器だけが読み、評価対象clientのpromptへ答えを混ぜない。

pilot の完了条件は「評価ケースを作った」ことではなく、最低5 episode を人間がレビューし、少なくとも1回、失敗分類から変更、同一ケース再評価までを完了することとする。初期しきい値は、その5 episodeを見てから決める。根拠のない成功率目標を先に固定しない。

## 8. 段階的な自動化

### Phase 0: 人間が正解を作る

- 実務上の訂正・失敗から workflow case を作る。
- 人間が期待行動、証拠、failure stage を確定する。
- Chrome pilot を5 episodeレビューする。
- reviewは`~/.plk/workflow-reviews.jsonl`へ0600で追記し、case/variant、段階判定、Tier A証拠参照、
  failure stage、client/model/instruction/retriever/corpus revision、変更ID、再評価元を保持する。

### Phase 1: 改善ワークベンチ

- trace と action を case 単位でまとめた review queue を作る。
- 人間ラベルをimmutableに保存し、再判定はrevisionとして残す。
- failure stage から改善対象を1件推薦する。
- episode証拠はprivate storeへ保存し、workflow caseのGit正本へ生データを混ぜない。

### Phase 2: 再実行と比較

- reviewed case を replay 可能な評価セットへ変換する。
- client、model、prompt、retriever、fact revisionを固定して比較する。
- 変更前後で同じケースを実行し、stage別の差分を出す。

### Phase 3: AIによる提案

- AIは失敗分類、改善案、追加候補を提案する。
- 人間が一定期間の一致率を確認するまで、factの追加・更新・無効化は承認制を維持する。
- 自動化後もTier C自己申告だけで成功判定しない。

## 9. 継続・停止条件

- **継続**: reviewed episode が増え、同じ failure stage の再発が減り、改善リードタイムが短くなる。
- **見直し**: review queue が溜まるだけ、`unknown` が減らない、同じ改善を繰り返す。
- **簡素化**: E2E 成功に寄与しない検索層・ダッシュボード・収集項目は削る。
- **停止**: 人間レビューの負担が継続的に実務価値を上回り、代表ケースでも改善を再現できない。

E2E pilot完了前は、旧ゲートを基盤健全性のblockerとして使い、新評価を価値継続・停止の主判定に使う。
両者が不一致なら、基盤が不健全な場合は判定保留、基盤が健全でもE2Eが失敗ならPLK価値未達とする。

## 10. CI の契約

GitHub Actions の `Workflow evaluation contract` は、外部 API、secret、`~/.plk`、既存 DB を使わず、
リポジトリの fixture と task 固有の一時環境だけで次を検証する。

- lint、今回の workflow-evaluation Python の format、型、pytest、dashboard JavaScript 構文
- 正常な disposable corpus fixture を使った CLI validator
- 重複 case / variant、expected fact の欠落・invalidated・content hash 不一致の fail-closed test

実運用 corpus との照合は live data に接続しない。正本の hash と active status は、実運用の
改善手順で別途確認し、CI の fixture 成功を実務価値の成功判定に使わない。
