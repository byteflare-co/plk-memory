# Loop Review Project Config

## Revision

- contract_version: `loop-review/v1`
- 宣言ラベル: `2026-08-21.1`

`review_config_revision` の正は、このファイルの raw bytes の SHA-256 先頭12桁とする。宣言ラベルは scope tuple や stale 判定には使わない。

## Normative sources

- intent / acceptance criteria / out-of-scope: 対象 Plane 課題の description と、承認済み `[epic-plan]` または `[loop-ledger]`
- project architecture and operations: `DESIGN.md`、`README.md`、`docs/BLUEPRINT.md`、`docs/OPERATING_MODEL.md`、`docs/OPERATIONS.md`
- evaluation contract: `docs/EVALUATION_MODEL.md`、`scripts/eval/workflow_cases.yaml`
- code invariants: `src/plk_memory/`、`alembic/versions/`、`clients/`
- declared impact scope: 対象課題の影響範囲。repo 内候補は `src/`、`tests/`、`scripts/`、`alembic/`、`clients/`、`docs/`、`deploy/`、`.github/`、`pyproject.toml`、`uv.lock`、`README.md`、`DESIGN.md`
- project review rules: このファイル、`docs/loop/flow-config.md`、repo に存在する `AGENTS.md`
- CI status source: GitHub Actions for the exact review SHA。CI workflow が未整備の間は `docs/loop/flow-config.md` の C0 gate に従い、実 CI は未充足と記録する
- tester raw evidence: 許可されたローカルコマンドの出力と、正確な SHA に紐づく GitHub Actions logs。結論だけを spec reviewer へ渡さない

## Static review boundary

- readable root: repository root only
- readable local artifacts: `docs/loop/reports/`、repo 内 fixtures、各 test / reviewer が作成した task 固有 tmp のみ
- allowed static / local verification commands:
  - `git diff`、`git diff --check`、`git show`、`git status`、`rg`、`sed`、`jq`、`find`
  - `node --check src/plk_memory/static/app.js`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pyright`
  - `uv run pytest`
- forbidden commands and actions:
  - `git commit`、`git push`、`gh pr merge`、main への merge、force-push、dependency installation
  - production / customer / external service への read・write、通知・投稿・送信
  - `~/.plk` の live data、既存 PostgreSQL / FalkorDB、運用中 daemon / worker への接続
  - migration / index rebuild / outbox delivery / promotion / external integration の live 実行
- external-write destinations: none。reviewer は findings とローカル証拠だけを orchestrator へ返す

## Security triage candidates

Path・keyword の一致は full security review の候補シグナルであり、それ自体を finding としない。

- candidate paths:
  - `src/plk_memory/auth.py`
  - `src/plk_memory/mcp_tools.py`
  - `src/plk_memory/postgres/**`
  - `src/plk_memory/git_services.py`
  - `src/plk_memory/github_promotion.py`
  - `src/plk_memory/slack_promotion.py`
  - `src/plk_memory/telemetry.py`
  - `src/plk_memory/workflow_evaluation.py`
  - `alembic/**`
  - `scripts/**`
  - `deploy/**`
  - `.github/**`
  - `pyproject.toml`
- candidate keywords:
  - `credential`, `secret`, `token`, `authorization`, `jwt`, `tenant`
  - `path`, `payload`, `query`, `embedding`, `prompt`, `fact`, `trace`
  - `POST`, `PUT`, `PATCH`, `DELETE`, `subprocess`, `shell`, `webhook`

## Security full context

- product boundary: 西川将弘が複数エージェントから利用する private memory service。customer-facing service ではない
- authentication boundary: MCP / HTTP / dashboard の認証・認可を迂回せず、token・credential・session をログ、telemetry、review artifact、UIへ出さない
- trust boundary: agent / client input → admission and policy → Git / Markdown primary store → rendered MCP / API / dashboard output。PostgreSQL は target / alternate backend、graph / embedding は primary から再構築可能な derived index として扱う
- knowledge integrity: fact の追加・更新・無効化、`supersedes`、namespace、provenance、revision を守る。derived index を SoT とせず、stale index や dead letter を成功扱いしない
- evaluation integrity: `plk_record_intent`、search、decision、action、workflow review の trace 関係を偽装せず、自己申告 effect を E2E 成功の独立証拠として扱わない
- filesystem boundary: repository fixture / task 固有 tmp だけを許可し、`~/.plk` live data と任意パスへの読み書きを禁止する。path traversal、symlink、権限設定、atomic append を確認する
- database boundary: reviewer は disposable DB / fake のみを使う。production/customer/existing service DB は禁止
- external integration boundary: GitHub、Slack、Anthropic、embedding / graph backend 等は fake / stub のみ。外部 read・write と secret 取得は禁止
- data classification: private internal knowledge。secret、credential、customer data、生の外部 payload を fixture・log・telemetry・reportへ入れない
- browser/dashboard boundary: HTML rendering、Markdown sanitization、JSON serialization、URL / DOM insertionでstored/reflected XSSを防ぎ、private fact や query text を不要に露出しない

## Runtime adapter

```yaml
# loop-model-allocation/v1
models:
  claude-code:
    fast: claude-haiku-4-5-20251001
    standard-reasoning: claude-sonnet-5
    high-reasoning: claude-opus-4-8
  codex:
    fast: luna_explorer
    standard-reasoning: terra_worker
    high-reasoning: terra_reviewer
role_overrides: {}
```

## Learnings

- short-term learnings file: `docs/loop/review-learnings.md`
- project-specific findings remain in Plane or project docs; no automatic PLK promotion

## Sandbox and confidentiality

- allowed local sandbox roots: this repository and task-specific temporary directories only
- prohibited resources: production systems, customer data, credentials, external service APIs, existing service databases, `~/.plk` live data
- human escalation route: private Plane issue comment text generated for the orchestrator; Phase 1では投稿せず文面提示のみ
- prohibited output: secret values, customer data, raw private facts / queries, raw service payloads, exploit instructions unnecessary for remediation
