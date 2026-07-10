# 検索動線の配布記録（Phase 2 Task 10 / Phase 3 実態更新）

`guideline-line.md` の 1 行をどこまで配布したかの記録。

## 配布方針（controller のスコープ制限 → Phase 3 時点で解消）

Phase 2 Task 10 時点では「ユーザーのグローバル CLAUDE.md への動線追記」は本タスクの実行範囲外（controller が
ユーザー承認を取ってから別途実行）としていた。同じ理由で、Codex のグローバル `~/.codex/AGENTS.md`（`CLAUDE.md`
と同様、全プロジェクト・全セッションに常時ロードされるユーザーのグローバル指示ファイル）や Hermes の
`~/.hermes/SOUL.md` も Task 10 内では書き込んでいなかった。

**2026-07-03、controller がユーザー承認を取った上で 3 ファイルへの追記を実行済み**（各ファイルのバックアップは
`.bak-plk` サフィックスで同ディレクトリに保存: `~/.claude/CLAUDE.md.bak-plk` /
`~/.codex/AGENTS.md.bak-plk` / `~/.hermes/SOUL.md.bak-plk`）。

`reason="auto-guideline"` を利用ログに記録する仕組み自体は配布と独立に検証済み（下記）。

## 配布状況

| 配布先 | ファイル | 状態 | 備考 |
|---|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md`（グローバル） | **配布済み**（2026-07-03、controller 承認後） | バックアップ `~/.claude/CLAUDE.md.bak-plk` |
| Codex | `~/.codex/AGENTS.md`（グローバル） | **配布済み**（2026-07-03、controller 承認後） | バックアップ `~/.codex/AGENTS.md.bak-plk` |
| Hermes | `~/.hermes/SOUL.md` / システムプロンプト | **配布済み**（2026-07-03、controller 承認後） | バックアップ `~/.hermes/SOUL.md.bak-plk` |
| Agent SDK（自作） | `examples/sdk_client_check.py` の `system_prompt` | 配布済み（検証スクリプト内のみ・スコープ限定） | このスクリプト自体がグローバル設定ではなくリポジトリ内の検証コードなので対象外。恒久的なガイドライン注入ではなく `plk_search` 呼び出しの動作確認用 |

## `reason="auto-guideline"` ログ確認（配布とは独立に、記録メカニズム自体を検証）

Claude Code から `plk_search(reason="auto-guideline")` を手動で 1 回呼び出し、
`~/.plk/usage.jsonl` に `"reason": "auto-guideline"` が記録されることを確認済み
（`p2-task-10-report.md` にログ実物を記載）。3 ファイルへの実配布が完了した現在は、各クライアントで
「税務・社保・法務」文脈の依頼を投げ、エージェントが自発的に `reason="auto-guideline"` 付きで
`plk_search` を呼ぶことの実地確認が残作業。

## 残作業

1. 各クライアント（Claude Code / Codex / Hermes）で意図的に「税務・社保・法務」文脈の依頼を投げ、
   エージェントが自発的に `reason="auto-guideline"` 付きで `plk_search` を呼ぶことを 1 件ずつ確認する
