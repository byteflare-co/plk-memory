# Loop Flow Config（orchestrator 専用正本）

対象 repo: `plk-memory`（Byteflare 自社 repo）。
正本関係: `loop-review-core/CONTRACT.md`、`loop-engineering/PERMISSIONS.md`、BYT-12（tracker connector）、BYT-21（モデル配分・予算）。

## Tracker connector

- provider / MCP: Plane / `plane-byteflare`
- workspace / project: `byteflare` / `Byteflare`（identifier: `BYTEF`）
- ラベル体系: `loop:ready-for-intake` / `loop:in-loop` / `loop:ready` / `loop:escalated` / `loop:security-required`
- 状態マッピング: intake=Todo、implementing/testing=In Progress、reviewing/ready=In Review、escalated=Todo。Done は人間専管
- コメント書式: `[loop-ledger]` / `[loop-round]` / `[loop-notify]`、epic は `[epic-plan]` / `[epic-progress]`

### 現行 Phase

基本 Phase は **1**（BYT-12 §4）。tracker の読み取りと live read-back は行うが、課題・コメント・ラベル・状態・親子関係・blockedBy を含む **tracker mutation はすべて文面提示のみ**とする。ただし、Phase A 承認後の approved-plan/v1 hash が下記 allowlist と完全一致する場合に限り、その plan の approved epic lifecycle として `allowed_mutations` に列挙した Plane control-plane mutation を許可する。それ以外の個別 run の承認では Phase 2 以上へ拡張しない。

```yaml
# approved-epic-lifecycle/v1
approved_epic_lifecycle:
  default: deny
  approved_plan_hashes:
    - dc7f685c837f7bbebfd39353f1fb84ff5ff100139528e37123702f5a67dcd95e
  allowed_mutations: [epic_create, child_create, description_exact, parent, blocked_by, loop_label, orchestrator_declaration, writer_declaration, ledger, round, progress, non_terminal_state]
  forbidden_mutations: [done, canceled, delete, archive, scope_expansion, main_merge, production_write, customer_write, external_business_write]
```

- 課題本文・コメント・状態・関連 PR は読み取ってよい
- allowlist 不一致時は、課題登録、コメント投稿、ラベル付替え、状態遷移、親子・blockedBy 設定を実行せず、文面を人間へ提示する
- allowlist 一致時も description は approved plan と完全一致する内容に限定し、scope expansion は禁止する。Done / Canceled 遷移、削除・archive、main へのマージは人間専管

## ブランチ運用

- 単発 run: `codex/<issue-id>-<english-slug>`（ASCII、小文字 kebab-case）、base は `main`
- epic run: `epic/<epic-id>`、子課題 branch / PR の base は epic branch
- epic branch への子 PR マージは epic-flow orchestrator に許可する
- main への直コミット・merge・force-pushは禁止。統合 PR は draft 作成までとし、ready 化・main へのマージは人間専管

## CI 現在地と intake gate

2026-08-21 現在、この repo に `.github/workflows/` の実 CI workflow は存在しない。epic-flow Phase A では **C0: loop 設定と今回の変更領域を検証する CI の整備**を DAG の先頭に置く。C0 が main または承認済み epic base に取り込まれるまでは、ローカルハーネス結果を実 CI green と呼ばず、CI gate は未充足として扱う。

## permissions（厳格化上書き）

- production・customer resource、外部 business service への書き込み、通知・投稿・送信は禁止。これは business / customer / production API の禁止であり、上記 allowlist に一致する approved epic lifecycle の Plane control-plane mutation は禁止しない
- reviewer / tester は production DB、customer data、credential、既存外部サービス、運用中プロセスへ接続しない
- `~/.plk` 配下の live data はレビューで原則使用禁止。repo 内 fixture、テストが作る一時領域、`mktemp` で作成した task 固有領域だけを使う
- PostgreSQL が必要なテストは task 固有の disposable instance に限定し、既存 DB を使わない
- secret は表示・保存しない。必要な通常実装 run ではユーザーグローバルの `op-cached` 契約に従うが、reviewer run では secret を取得しない
- migration、promotion、outbox、GitHub / Slack integration、business / customer / production 向け MCP write API は fixture / fake / tmp のみ。live 実行は禁止。上記 allowlist に一致する Plane tracker lifecycle はこの禁止の対象外

## 予算 / ハードストップ

```yaml
# loop-budget/v1
budget:
  max_rounds: 4
  max_flow_hours: 6
  max_agent_minutes: { developer: 90, tester: 60, reviewer: 30, security_full: 45, triage: 10 }
  max_ci_reruns_per_sha: 1
  max_security_full_per_issue: 3
  max_heartbeat_scan_items: 20
```

## 通知設計

通知理由は、完了、統合承認待ち、エスカレーション、予算超過、権限境界、セキュリティ blocking の6種に限定する。

```yaml
# loop-notify-allowlist/v1
notify:
  allowed_notify_markers: [READY, ESCALATED, QUESTION]
```

## orchestrator

- 能力クラス: `high-reasoning`（実 ID は `docs/loop/review-config.md` の `loop-model-allocation/v1` を参照）
- ローカル補助記録: `docs/loop/runs/`（非コミット。SoT は Plane）
- developer report 保存先: `docs/loop/reports/round-<n>-developer.md`（非コミット）
