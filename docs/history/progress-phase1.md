Phase 1 SDD start (Tasks 1-12; 13/14 deferred by user)
P1-T1: complete (commit a68f0d4, review clean; deps: graphiti-core 0.29.2/mcp 1.28.1/fastmcp 3.4.2; GitHub repo cutsome/plk-memory 作成済み)
  Minor: 空 admin_token のデフォルト（Task 8 の実装は空なら常に 401 なので secure-by-default 予定）
P1-T2: complete (commit eadabb8, review clean; Minor: 16hex 切詰めの衝突面は plan 由来)
P1-T3: complete (commits deae438+776278a fix, review approved after F401 fix)
P1-T4: complete (commit ca4e592, review approved; 逸脱2件は正当と検証済み: merge-base except追加/テスト数18が正)
  最終レビューでトリアージ: merge-base の非rewrite失敗（corruption等）も HistoryRewritten に化ける narrow edge
P1-T5: complete (commits befec24+5b9ff4a, fix 1回で approved; supersedes 事前検証・push リトライ上限 reset・30 passed)
  Minor: raise from None のチェーン切断／reset 自体の失敗は生例外（リポジトリ破損級なので許容）
P1-T6: complete (commits 5dcd20f+be70edd, review approved; 適応3件をソース照合で妥当確認)
  重要知見（逆輸入レポート行き）: graphiti validate_group_id はドット不可 → group_id はハイフン区切りに変更（namespace はドットのまま）。_NullCrossEncoder で OpenAI reranker 回避。triplet 削除は Edge.delete_by_uuids
  Minor: triplet モードの EntityNode 残留可能性／SearchHit.score は常に None（コメント要）
P1-T7: complete (commit 073fda0, review approved; 整理3点は妥当・id無しmd無視は load-bearing)
  要確認@T9: status() 未テスト（T9 の test_status_tool_reports_freshness でカバーされること）／Minor: test_rename_promotion_delete_and_readd の名前不一致
P1-T8: complete (commit cb4c7f8, review approved; contextvar 伝播・secure-by-default を実行検証済み)
  T9 への引き継ぎ: /admin・/mcp の startswith は /adminfoo 等も match する — T9 で防御的 prefix 判定を検討
P1-T9: complete (commit 27ca8ab, review approved; 51 passed; admin_sync 同期化は brief 矛盾の正しい解決と判定)
  追跡: ①MCP フルラウンドトリップ（initialize→tools/call）未検証 — T10 起動スモーク/live で閉じる ②_bg_tasks の shutdown 未 cancel ③pyright: combine_lifespans フォールバック shim の型エラー — 最終レビューでトリアージ
P1-T10: complete (commits 751a84e+95338d3; 実スモークで degraded 起動・実データ clone・sync 動作確認。21vs23 は invalidated スキップ+誤記と判明)
P1-T11: complete (commit 403b781, review clean; 6ファイル・サーバー設定と整合確認済み)
P1-T12: complete (commit 1cd9a2b @agent-organization, review approved; 40 passed・実データOK・CI green)
  Minor: superseded_by 自己参照は素通り／CONVENTIONS の https 記述と URL_RE の http 許容の字面差
P1 final review: With fixes → 5件修正完了 commit 0302e73（live smoke group_id・WriteConflict変換・sync直列化・degraded分離・bg task cancel）、54 passed、push済み
P1 final review triage: Phase 2 送り = git identity 設定化/DOMAINS 設定化/recall post-filter/index キャッシュ/reindex 二重起動/query ログのハッシュ化検討/superseded_by 自己参照/CONVENTIONS http字面
Task 13 実施者への申し送りは p1-final-review にあり（モデルエイリアス実在確認・Ollama次元・初回ingest壁時計・NullCrossEncoder答え合わせ）
=== Phase 1 コード部分 COMPLETE (2026-07-02) — T1-12 + final fixes, plk-memory HEAD=0302e73 / agent-organization HEAD=1cd9a2b。Task 13/14（live実測・評価）は未実施・ユーザー承認待ち ===
P1-T12.5: complete (commit 385c1c8, 57 passed; ユーザー決定=完全ローカル方式A。OpenAIGenericClient採用・直接diff確認で妥当)
P1-T13: complete (commits 7aac634+a2b08cc; episode 302s/件・triplet 130s/件・両モード dead letter 0。重大バグ発見: FalkorDriver の単一group検索が default_db を見る→_route_group で修正。検索スモーク 2/3 が 1 位ヒット。副作用: plk-main グラフは現在空)
P1-T13 fix: complete (commit d823b13, re-review approved; op_lock 直列化・interleave 検出テスト・report 因果訂正)
  逆輸入必須事項: 組織展開 規模では graphiti driver= 引数スレッディングへの移行が required（search がingest 中ブロックされるため）
P1-T14: complete (plk-memory e951fad+79506c9 / agent-organization 451c0c8=main反映済み, Opus review approved・全数値独立再現)
  評価結果: embed素 20/20 MRR1.000 / graph(triplet) 20/20 MRR1.000 / graph(episode) 16/20 MRR0.612 / rg 0/20（23件・参考値）
  triplet 満点は実質 statement 埋め込み検索と同等（グラフ構造の付加価値でない）。発見バグ3件は全て修正済み
=== Phase 1 FULLY COMPLETE (2026-07-03) — チェックポイント材料出揃い ===
