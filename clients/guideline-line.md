# 検索動線（1 行）

以下をエージェントの常駐指示（CLAUDE.md / AGENTS.md / システムプロンプト）に追加する:

> ツール・コマンド・外部操作を始める前に `plk_record_intent` で trace を開始し、操作分類・対象・副作用・PLK要否を記録する。税務・社会保険・法務・過去の意思決定・社内ノウハウに関わる判断では、同じ `trace_id` を付けて `plk_search(reason="auto-guideline")` を呼ぶ。ヒットがあれば同じ trace で `plk_record_decision` を1回記録する。実操作は `plk_record_action` の attempted / completed で挟み、PLKが影響した場合は `decision_id` を結ぶ。PLK不要なら `plk_requirement="not_required"` と理由を記録する。テレメトリ失敗が `non_blocking=true` なら本来の処理を続ける。

traceなしの旧呼び出しも互換目的で有効だが、操作適用率の集計対象外とする。未記録は「未使用」ではなく「未計測」とする。
