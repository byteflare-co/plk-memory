# Manual testing

PLK workflow evaluation の手動検証は、リポジトリ内 fixture と pytest の
`tmp_path` だけを使う。ブラウザ、外部送信、`~/.plk`、既存 DB には接続しない。

## C0: CI / validator contract

| Test ID | 種別 | 確認内容 | コマンド | 期待結果 |
| --- | --- | --- | --- | --- |
| `C0-NORMAL-001` | 正常 | repository workflow case が active corpus と整合する | `uv run python scripts/eval/validate_workflow_cases.py` | exit 0 と case / variant 件数を表示 |
| `C0-ERROR-001` | 異常 | expected fact が欠落した corpus を fail-closed にする | `uv run pytest -q tests/test_workflow_eval_cases.py::test_workflow_cases_fail_closed_for_missing_fact` | 1 passed |
| `C0-ERROR-002` | 異常 | invalidated fact を fail-closed にする | `uv run pytest -q tests/test_workflow_eval_cases.py::test_workflow_cases_fail_closed_for_invalidated_fact` | 1 passed |
| `C0-BOUNDARY-001` | 境界 | fact の content hash 変更を fail-closed にする | `uv run pytest -q tests/test_workflow_eval_cases.py::test_workflow_cases_fail_closed_for_changed_fact` | 1 passed |
| `C0-BOUNDARY-002` | 境界 | action pass に Tier A evidence を必須化する | `uv run pytest -q tests/test_workflow_eval_cases.py::test_action_pass_requires_tier_a_evidence` | 1 passed |

実施結果と新しい学びは
[`manual-testing-learnings.md`](manual-testing-learnings.md) に追記する。
