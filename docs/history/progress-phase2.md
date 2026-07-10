Phase 2 SDD start (Mac常駐版・10タスク, plan=plans/2026-07-03-plk-memory-phase2.md, plk-memory BASE=79506c9)
P2-T1: complete (commit 9f153d1, review clean; 64 passed)
P2-T2: complete (commit d44e2a6, review approved; 67 passed)
  最終レビューでトリアージ: /admin/reindex 連打時に2件目が silent drop で 200 'started' を返す（plan由来。route側で flag 先行セットの2行fixで解消可）
P2-T3: complete (commit 526d6d4 @agent-organization main, review clean; 41 passed・CI green・codex branch 不触を検証済み)
P2-T4: complete (commit 2ec77f2, review approved; 72 passed)
  裁定: proposed→applied 直接遷移は意図どおり（GitHub backend では merge=承認+適用。approved は Slack backend 用）。人間ゲートは backend+CI+ingest 検証が担保
  T6 への引き継ぎ: PromotionStore.get() の素 KeyError は呼び出し側でラップ（404 化）すること
P2-T5: complete (commit 99b1241, Opus review approved; worktree後始末・CI diff適合・ロック相互作用を実測検証)
  T6 に畳み込む修正: ①create_pr の URL パース失敗を例外化（number=0 の silent 化け防止）②_gh monkeypatch テストで create_pr/merged_state の引数・JSONパース・番号抽出を検証 ③PR already exists の扱い ④(任意) promote/* ブランチ ref の prune
P2-T6: complete (commits aa394b0+fca799a, fix 1回で approved; 87 passed。並行性・crash回復・冪等性は Opus 検証済み)
  Minor(最終レビュー行き): to_thread 化で同一 fact 並行 propose の重複レコードレース（同一PRに収束・低実害。rev-list を重複チェック前に移せば解消）
P2-T7: complete (commits 9fc97ff+a17d9bc, fix 1回で approved; 93 passed。fact_ids 記録で未参照判定が実用化)
P2-T8: complete (commit 3862616, Opus security review approved; 99 passed。inline script→external JS の逸脱は brief 矛盾の正しい解消と判定)
  Minor(最終レビュー行き): cookie/パスワード比較の非定数時間・静的cookieトークン・login レート制限なし（localhost 前提で許容）
P2-T9: complete (commit acbf187, review approved・実機再検証済み; launchd常駐・OrbStack環境)
P2-T10: complete (commits 72eaa33+73627d2+b5f88df; 全4クライアント実接続・検索疎通済み。動線3ファイル配布済み。昇格1往復実証: PR#1 → CI green → 人間merge → poller検知 → applied (11:08) → shared ingest済み)
  live中の実バグ修正2件(未タスクレビュー→最終レビューで検証): b5f88df=frontmatter往復正規化→外科的1行置換 / 73627d2=PR body regex
  残タスク: DISTRIBUTION.md の配布済み更新 / agent-organization ローカル clone が 8 commit 分岐中(codex作業・こちらでは触らない)
=== Phase 2 完了条件 達成 (2026-07-03 11:08) ===
=== Phase 2 final review: Ready to merge=Yes (2026-07-03)。live修正2件検証済み。持ち越し→P3: UI auth 強化(EC2前必須・README §7 注記)・reindex silent drop・dup propose・DISTRIBUTION.md 実態更新 ===
