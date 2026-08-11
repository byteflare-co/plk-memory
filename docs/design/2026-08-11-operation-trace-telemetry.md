# Operation trace telemetry

## Goal

PLK検索回数ではなく、`intent -> search -> decision -> action attempted -> action completed`
を同一traceで監査し、検索漏れと実行への影響をclient別に測る。

## Contract

- `plk_record_intent`: 操作前に1回。`plk_requirement`をrequired/optional/not_requiredで宣言する。
- `plk_search(trace_id=...)`: intentと検索を結ぶ。traceなしは後方互換用。
- `plk_record_decision(trace_id=...)`: 同じtraceの検索だけを解決できる。
- `plk_record_action`: attemptedとcompletedを別eventで記録する。completedはattemptedなしでは拒否する。
- PLKが操作を変えた場合、actionからdecisionを参照する。

## Privacy and integrity

PostgreSQLはintent、target、queryの平文を保存せずSHA-256のみ保持する。Git backendは既存の
ローカル0600 JSONL境界内でintent/target previewを保持する。IDの再利用は同じpayloadのretryだけを
許し、client、trace、search、decisionの越境を拒否する。テレメトリ障害は本来の操作を止めない。

## Metrics

`/ui/api/metrics` の `operation_traces` で、PLK必須intent、事前検索率、検索漏れ、decision接続、
操作試行・完了、decision付き完了操作、effect別件数、client別検索率を返す。旧イベントは母数へ混ぜない。
