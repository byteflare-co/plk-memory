# Loop 運用メトリクス（loop-metrics/v1）

本ファイルは `plk-memory` の loop run 集計ビューである。SoT は Plane の `[loop-ledger]` / `[loop-round]` / `[epic-progress]` と、正確な SHA に紐づく CI 証拠。矛盾時は一次データが勝つ。

記録者は run 終端時に追記文面を生成し、コミットは人間が行う。初期 bootstrap 時点では完了 run がないため、集計値を推測せず空テンプレートから開始する。

## run 記録（1 run = 1行）

| 記録日 (UTC) | run | 課題 | 終端 | rounds/max | blocking 評価内訳 (spec/code/実CI/security) | resume | READY→人間判断 |
|---|---|---|---|---|---|---|---|

## epic 記録（1 epic = 1行）

| 記録日 (UTC) | epic | 壁時計 | 子課題数 | rounds 合計 | PR 総数 | プロセス起因 PR | escalation | 終端 |
|---|---|---|---|---|---|---|---|---|

## 集計

- M1 平均周回数: データなし
- M2 周回上限到達率: データなし
- M3 確認担当別 blocking 評価: データなし
- M5 再開成功率: データなし
- M6 人間チェックポイント差し戻し率: データなし

## M4 advisory 滞留スナップショット（review-sweep 実行ごと）

| sweep 実行日 (UTC) | 滞留件数 | 内訳 |
|---|---:|---|

## 出典

- Plane `byteflare` workspace / `Byteflare` project（identifier: `BYT`）の対象課題
- 対象課題の `[loop-ledger]` / `[loop-round]` / `[epic-progress]`
- exact SHA に紐づく GitHub Actions logs（CI 整備後）
