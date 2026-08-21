# Workflow evaluation validation runbook

## 目的

C0 の workflow case / corpus 契約が、正常系を受理し、欠落・無効化・内容変更を
fail-closed で拒否することをローカルで確認する。

## 安全境界

- リポジトリ内 fixture と pytest の一時ディレクトリだけを使う。
- ブラウザ、外部 API、外部送信、`~/.plk`、既存 DB へ接続しない。
- private review data や secret を入力・出力しない。
- 失敗時に本番データや既存ローカルデータを修正しない。

## 前提

- repository root で実行する。
- Python コマンドは `uv run` 経由で実行する。
- approved plan と C0 の評価契約を照合済みである。

## 実行

まず正常系validatorを実行する。

```bash
uv run python scripts/eval/validate_workflow_cases.py
```

CI と同じ隔離検証では、repository fixture を明示して実行する。

```bash
uv run python scripts/eval/validate_workflow_cases.py \
  tests/fixtures/workflow_evaluation/workflow_cases.yaml \
  --corpus-root tests/fixtures/workflow_evaluation/corpus
```

次に正常・異常・境界をまとめて確認する。

```bash
uv run pytest -q tests/test_workflow_eval_cases.py
```

baseline の静的検証も行う。

```bash
uv run ruff check .
uv run pyright
node --check src/plk_memory/static/app.js
git diff --check
```

個別のTest IDと期待結果は
[`manual-testing.md`](manual-testing.md) を参照する。

## 判定

- validator が exit 0 で case / variant 件数を表示する。
- CI の disposable fixture 実行は `~/.plk` や既存 corpus を参照しない。
- `tests/test_workflow_eval_cases.py` がすべてpassする。
- lint、型検査、JavaScript構文、diff検査がすべてpassする。
- 欠落・invalidated・content hash変更が受理された場合はfailとする。

## cleanup

pytestの一時ディレクトリはpytestが管理する。手動で作成したfixtureやreview storeは
ないため、追加cleanupは不要である。
