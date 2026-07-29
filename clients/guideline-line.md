# 検索動線（1 行）

以下をエージェントの常駐指示（CLAUDE.md / AGENTS.md / システムプロンプト）に追加する:

> 税務・社会保険・法務・過去の意思決定・社内ノウハウに関わる判断の前に、plk の `plk_search` を `reason="auto-guideline"` 付きで呼ぶ。1回以上の検索でヒットした場合は、最終回答の直前に関連する全 `search_id`、実際に使った `used_fact_ids`、`effect` をまとめて `plk_record_decision` へ1回記録する。どのファクトも使わなければ `effect="none"` と `no_use_reason` を記録する。全検索が0ヒットなら追加の記録は不要。記録失敗が `non_blocking=true` なら本来の処理を続ける。

`reason` は自発検索と明示指示の区別、`plk_record_decision` は検索結果が最終判断へ与えた観測上の影響を計測するために使う（設計書 §9）。未記録は「未使用」ではなく「未計測」とする。
