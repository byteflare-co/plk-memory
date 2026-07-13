# PLK activeファクト再評価・変更結果（v1.5基準）

- 日付: 2026-07-13
- 対象: active 56件
- 必須ゲート: 西川将弘／Byteflareの実務で同じ判断場面が現実的に再発し、取得が判断・行動を変えること
- 一般的に有用、他社なら使える、別法人を作れば使える、という仮想的再利用は不適格

## 結論

| 処置 | 旧fact数 | 置換後の新fact数 |
|---|---:|---:|
| 維持 | 30 | 30 |
| 置換 | 12 | 14 |
| 無効化のみ | 14 | 0 |
| 合計 | 56 | 44 active |

置換12件のうち、複合していたagent領域2件を各2件へ分割するため、新activeは14件。処理後のactive総数は44件となる。

## 実行結果

2026-07-13にユーザーの全文プレビュー承認後、置換は後継factの追加とsupersedesによる旧fact無効化、
削除候補はplk_invalidateで履歴を残した。philosophyの置換は規約どおり人間承認済みのGit直編集として
実行した。処理後のactiveは44件。

- 通常APIで追加した後継fact: 10件
- 人間承認済みGit直編集で追加したphilosophy: 4件
- 置換以外で無効化したfact: 14件
- 置換により無効化した旧fact: 12件


- 対象: `/Users/masahiro/dev/byteflare-co/agent-organization/knowledge/domains/agent/*.md` の `status: active` 30件
- 基準: 一般論としての再利用可能性ではなく、西川将弘 / Byteflare の実務で同じ判断場面が現実的に再発し、取得によって判断・行動が具体的に変わることを必須ゲートとした。
- 補助基準: 耐久性、確実性、SoT非重複、適用範囲、kind整合、原子性。
- `plk_search(query="Byteflare エージェント 判断原則 実務 再発", reason="auto-guideline")` 実施済み。検索は非degradedで、既存agent原則と関連SoTファクトを確認した。

## 全件判定

| # | file / id | 判定 | Byteflareで現実的に再発する取得場面と行動差 | 理由 / 措置 |
|---:|---|---|---|---|
| 1 | `ai-absorbs-labor-human-judges.md` / `2HCBYFYHF0F7NH0F3HRF0ZJR1K` | 維持 | 顧客業務のAIワークフローや社内エージェントを設計するたびに、人を実行工程へ残す案から、判断・承認・評価ゲートだけに置く案へ変える。 | AI業務診断・構築・自社運用で反復する組織規範。取得が役割分担を直接変える。 |
| 2 | `build-usage-path-before-feature.md` / `01KWX54J3ZET10A137KWCT0A6K` | 維持 | PLK、Hermes、顧客自動化などの新機能を作るたびに、単体機能だけで完了せず、実フローのトリガー・導線・利用ログまで成果物へ入れる。 | Byteflareでは機能追加が継続し、利用されない自動化を避ける判断が反復する。 |
| 3 | `check-browser-profile-before-automation.md` / `01KWY9PXR4MARNKF224W9ABH6X` | 置換 | Squeeze・Byteflare・個人などログイン状態の異なるChrome環境を使う代行操作のたびに、開始前に対象workspace/accountとprofileを照合する。 | 再発性は高いが、現文は製品名・具体APIという可変knowhowと、我々の行動規則を混在させ、kindも不整合。下記R1へ置換。 |
| 4 | `check-primary-before-implementation.md` / `01KWX54J3ZET10A137KWCT0A68` | 維持 | n8n、freee、Notion、Slack、Cloudflare等の未知API・設定を実装するたびに、推測実装から公式仕様または実レスポンス確認へ変える。 | ユーザーが明示的にOKとした例で、実際の外部連携開発が反復する。 |
| 5 | `compare-against-simple-baseline.md` / `01KWX54J3ZET10A137KWCT0A6H` | 維持 | classifier、検索、RAG、エージェント構成など複雑手法の採否ごとに、単純baselineを同一指標で測り、勝てなければ複雑案を捨てる。 | 複数の現行開発領域で繰り返す選定判断で、取得により実験設計と採否が変わる。 |
| 6 | `dependency-toward-stable.md` / `01KWX54J3ZET10A137KWCT0A6D` | 維持 | 評価器、移行ツール、索引、補助CLIを本番資産へ足すたびに、本番側から補助資産をimportする逆流を避ける。 | 複数repoの設計・refactorで現実に反復し、削除可能性と依存方向を変える。 |
| 7 | `derived-artifacts-disposable.md` / `01KX047XRT5033WYTKG9VA71C7` | 維持 | 診断レポート、定例資料、集計CSV、スライドを更新するたびに、派生物の直接育成ではなくSoT修正と再生成を選ぶ。 | Byteflareの顧客納品・月次運用で頻繁に再発し、更新先を具体的に変える。 |
| 8 | `end-or-cut-loss-as-first-class-option.md` / `01KWX54J3ZET10A137KWCT0A6S` | 維持 | 事業、セルフホスト基盤、自動化、機能の棚卸しで、継続・追加だけでなく終了を正式候補にし、将来期待値で判断する。 | 一人法人の限られた資源配分で継続的に再発する。仮想的な他社向け一般論ではない。 |
| 9 | `falsify-before-commit.md` / `01KWX54J3ZET10A137KWCT0A69` | 維持 | 障害恒久対応、設計結論、顧客向け提案を確定するたびに、最初の仮説を即採用せず、破綻条件をコード・実データで潰す。 | inboxやlabid-scraping等で繰り返す高影響判断に直接効く。 |
| 10 | `group-fixes-by-root-cause.md` / `01KWX54J3ZET10A137KWCT0A6G` | 維持 | review threadや回帰が複数出たとき、症状別patchではなく根本原因でcluster化して原因単位で修正する。 | 複数repoのreview-fixで反復し、修正単位を変える。 |
| 11 | `honest-reporting-no-fabrication.md` / `7CF4BQM639RMNQ1NAJTQQ2ZXP9` | 置換 | サイト、診断レポート、対外提案、完了報告を作るたびに、架空実績・推定値を事実として置かず、未検証を明示する。 | 再発性は極めて高いが、捏造禁止と検証状態の開示を並列した現statementは原子性が弱い。上位の単一規範R2へ置換。 |
| 12 | `include-reason-evidence-source.md` / `01KWX54J3ZET10A137KWCT0A6N` | 維持 | 設計review、顧客提案、調査回答を返すたびに、結論だけでなく理由・証拠・出典を付けて、人間が検証・却下できる形にする。 | ユーザーが求めるevidence-first運用で恒常的に再発し、成果物の構成を変える。 |
| 13 | `independent-review-before-critical-decision.md` / `01KWX54J3ZET10A137KWCT0A6A` | 維持 | Notion SoTの大改訂、アーキテクチャ、不可逆な運用変更を確定するたびに、独立reviewを通しmust-fixを解消する。 | 大きい設計レビューで実際に繰り返す明示運用。 |
| 14 | `internal-bold-external-approval.md` / `00BB2M9W0ZNF6XYBK4NBJGR21Q` | 置換 | ローカル編集・調査と、PR/Slack/メール/フォーム等の外部書き込みの境界判断で、自走か停止かを決める。 | 最重要かつ反復するが、内部可逆の自走と外部書き込みの承認は独立に変更可能な2規範。R3a/R3bへ分割置換。 |
| 15 | `investigate-before-asking.md` / `CGRK8HPB7WPX1TZ3PVQHSZ8GQT` | 維持 | repo・ログ・公式資料から答えられる不明点に毎回遭遇するため、即質問せず調査し、本人にしか決められない点だけ聞く。 | Codex/Claudeの全実務で現実に反復し、ユーザーへの質問数と調査行動を変える。 |
| 16 | `long-work-needs-north-star.md` / `01KWX54J3ZET10A137KWCT0A6Q` | 維持 | 期限のないclassifier改善、PLK、事業開発、運用自動化を始めるたびに、目的文と次の検証節目を先に置く。 | Byteflareに複数の長期改善テーマがあり、停滞・drift防止判断が反復する。 |
| 17 | `minimize-side-effects.md` / `01KWX54J3ZET10A137KWCT0A6P` | 維持 | API・GitHub・Notion・ブラウザの調査でreadとwriteの双方が可能なとき、同じ証拠が取れるならread-onlyを選ぶ。 | 外部システム調査で日常的に再発し、実行する操作を直接変える。 |
| 18 | `mvp-validates-hypotheses.md` / `01KWX54J3ZET10A137KWCT0A6C` | 維持 | 新規AIサービスや社内基盤のMVPを計画するたびに、機能縮小版から、最重要仮説を検証する最小構成へ変える。 | Byteflareの新規事業・顧客PoCで再発可能性が具体的に高い。 |
| 19 | `one-change-one-concern.md` / `01KWX54J3ZET10A137KWCT0A6B` | 維持 | PR修正中に別bug・rename・refactorを見つけるたびに、現在変更へ混ぜず別task/PRへ切り出す。 | 複数repoで頻発する場面で、diff境界を直接変える。 |
| 20 | `parallel-rollout-for-high-impact-rewrites.md` / `01KWX54J3ZET10A137KWCT0A6E` | 維持 | classifier、顧客自動化、基盤移行など既存稼働系の大幅rewriteで、一括置換からshadow/canary/段階拡大へ変える。 | 現行の複数システムで再発する高影響移行判断。 |
| 21 | `plausibility-not-evidence.md` / `GHE08REDSAMMC7KAWTPKFVQQXS` | 維持 | サブエージェント、reviewer、AI、ツールの完了断定を受けるたびに、自己申告を採用せず現物・別経路で検証する。 | 幻覚SHAやDB誤断定が実際に再発しており、完了判定を変える。 |
| 22 | `predefine-kill-criteria.md` / `01KWX54J3ZET10A137KWCT0A6J` | 置換 | PLK、セルフホストサービス、営業施策、PoCなど継続コストのある取り組み開始時に、撤退条件を先に置き実測で継続可否を判定する。 | 再発性は高いが「全施策で測定可能な数値」は適用不能な場面を含む。反復計測可能な投資へ限定し観測可能条件も許すR4へ置換。 |
| 23 | `prefer-latest-stable-technology.md` / `01KX63RR8RDJ13C8AKDZ9X2T62` | 維持 | ライブラリ、runtime、SaaS APIを選ぶたびに、ホスト既定を盲目的に使わず公式で最新安定版を確認し、旧版なら理由を残す。 | ユーザーの明示決定であり、全repoの依存選定で反復する。 |
| 24 | `raise-knowledge-to-principle.md` / `01KWX54J3ZET10A137KWCT0A6M` | 無効化 | PLK候補審査時に使う場面自体は反復するが、取得しなくても必ず読む`CONVENTIONS.md`のadmission rubricから同じ判断になる。 | PLKの保存規約をPLKへ複製しており、取得による行動差がない。具体理由: `CONVENTIONS.md`の適用範囲・原子性・反実仮想ゲートへの重複で、正本変更時にdriftする。 |
| 25 | `recommend-one-option.md` / `01KWX54J3ZET10A137KWCT0A6R` | 維持 | 技術選定、購入、事業判断、顧客提案で複数案を返すたびに、平坦列挙ではなく推奨1案・理由・却下理由を置く。 | ユーザーの意思決定負荷を下げる反復的な出力規則。 |
| 26 | `single-sot-pointer.md` / `01KX047XRT5033WYTKG9VA71C5` | 維持 | Notion、コード、runbook、顧客資料へ同一事実を書きそうな場面で、正本を1つ定め他はpointerにする。 | Byteflareの領域横断でdriftが反復するため、保存場所の判断を変える。 |
| 27 | `specificity-by-audience-scope.md` / `01KX047XRT5033WYTKG9VA71C6` | 維持 | AGENTS/CLAUDE、共有skill、顧客文書など広いscopeの器へ書くとき、固有名詞・可変値をSoTへ退避し規則だけ残す。 | agent設定とskill整備で繰り返す具体的な情報境界判断。 |
| 28 | `speed-as-learning-loop.md` / `JCD1V7DDBKQTAC5Y4CTHDJDC8N` | 置換 | 提案・施策・設計が完成待ちで停滞するとき、最小の比較・推奨・叩き台を先に出し、次の判断までの時間を短くする。 | Byteflareの一人法人運営で反復するが、現文は価値観と条件付き実務規則を結合。R5a/R5bへ分割置換。 |
| 29 | `spike-largest-uncertainty-first.md` / `01KWX54J3ZET10A137KWCT0A6F` | 維持 | 新サービス、AI手法、大規模構築へ投資する前に、需要または技術の最大不確実性一点を最小spikeで検証する。 | Byteflareの新規事業・技術PoCで具体的に再発し、投資順序と撤退判断を変える。 |
| 30 | `tiered-model-delegation.md` / `01KWX54J3ZET10A137KWCT0A67` | 維持 | コード調査・実装・reviewを含むまとまったタスクごとに、上位モデルは設計・統合へ集中し、独立作業を適切な実行者へ委譲する。 | 現行エージェント運用そのもので日常的に再発し、モデル配置と並列化を変える。 |

## 置換後のexact fields

### R1: browser profile確認

```yaml
statement: "複数のブラウザプロファイルやログイン先があり得る外部サービスを操作するときは、操作前に対象account・workspaceと使用中profileの一致を確認する。"
kind: logic
why: "Byteflare・Squeeze・個人のログイン状態が同じ端末に共存し、誤ったprofileでは未ログインと誤認するだけでなく別workspaceへ操作する危険が繰り返し生じるため。"
how_to_apply: "ブラウザ操作の開始時に利用可能なprofileと現在のaccount・workspaceを確認し、依頼対象と一致するprofileへ切り替えてから閲覧・入力を始める。製品別コマンドはrunbookで確認する。"
```

### R2: 裏付けのない内容を事実として提示しない

```yaml
statement: "裏付けのない実績・数値・権威・完了状態を事実として提示しない。"
kind: philosophy
why: "架空の実績や推定値は顧客と西川将弘の判断を誤らせ、未検証を完了として扱う報告は次の作業と承認を誤らせるため。"
how_to_apply: "対外成果物と完了報告では、一次情報または実行結果で裏付けられた内容だけを事実として記載し、確認できない箇所は未検証・推定・未完了と明示する。"
```

### R3a: 外部書き込みの承認境界

```yaml
statement: "外部書き込みや不可逆・高影響な操作は、対象と全文をプレビューし、その操作に対する西川将弘の明示承認を得るまで実行しない。"
kind: philosophy
why: "PR・Slack・メール・フォーム・金銭操作は他者や外部システムへ直接影響し、誤実行後に完全には取り消せないため。"
how_to_apply: "送信・公開・申請・購入・削除の直前に対象と最終内容を提示し、その操作への承認を確認する。別操作への承認を流用せず、拒否や不確実性があれば停止する。"
```

### R3b: 内部で可逆な作業の自走

```yaml
statement: "目的達成に必要な内部かつ可逆な調査・編集・検証は、追加承認を待たず完了まで自走する。"
kind: philosophy
why: "ローカル調査や編集の都度確認すると西川将弘へ判断不要な待ち時間を転嫁し、エージェントへ実行労働を吸収させる運用目的を損なうため。"
how_to_apply: "ローカルファイルの調査・編集・build・test・失敗原因の修正とretryは自律して進める。不可逆、高影響、外部書き込みの境界に達した時点だけ停止して承認を求める。"
```

### R4: kill criteriaの適用範囲

```yaml
statement: "継続コストがあり反復計測できる施策・システムを始めるときは、着手前に観測可能な撤退・凍結条件を定める。"
kind: logic
why: "運用開始後は埋没コストと愛着で終了判断が遅れるため、PLKやセルフホスト基盤、継続施策では事前条件がないと低価値な運用を抱え続ける。"
how_to_apply: "利用回数・成果・保守時間・費用など継続判断に使える指標と判定期間を開始前に定め、閾値または観測条件を満たさなければ凍結・撤退の審査へ回す。"
```

### R5a: 速さの価値

```yaml
statement: "速さは作業量ではなく、次の意思決定と検証結果を得るまでの時間を短くするために追求する。"
kind: philosophy
why: "一人法人では西川将弘の判断が希少資源であり、完成度だけを高めても判断材料が届かなければ学習と軌道修正が止まるため。"
how_to_apply: "進行速度を評価するときは着手量や生成量ではなく、比較可能な結果が出て次の採否・修正判断を行えるまでの時間で評価する。"
```

### R5b: 完成待ちで判断を止めない

```yaml
statement: "完成を待つと意思決定が止まるときは、判断に必要な最小の比較・推奨・叩き台を先に提示してフィードバックを得る。"
kind: logic
why: "Byteflareの提案・設計・施策では、網羅的な完成物を待つより判断可能な最小材料を早く出す方が、誤方向を早期に修正できるため。"
how_to_apply: "残作業が多くても採否や方向修正に必要な論点が揃った時点で、前提・比較・推奨を明示した暫定成果物を提示し、得た判断を次の実装へ反映する。"
```

## 件数照合

- filesystem上のagentファクト: 32件
- `status: active`: 30件
- `status: invalidated`: 2件（今回の対象外）
- 判定行: 30件（#1〜#30、漏れなし）
- 維持: 24件
- 置換: 5件（後継案は計7ファクト。R3とR5を各2件へ分割）
- 無効化: 1件
- 合計: 24 + 5 + 1 = 30件


## 判定基準

`active` 14件に対し、次を必須ゲートとして適用した。

> 西川将弘／Byteflareの実務で同じ判断場面が現実的に再発し、その場でこのファクトを取得すると、取得しなかった場合とは異なる判断・行動になること。

一般論として他者へ再利用できるだけの知識、仮想的な再利用、現在のコード・設定・設計書・Notionから復元できる構成の複製、廃止技術・version/issueの一時状態、単発の移行・申請は不適格とした。一方、既存SoTの可変値を複製せず、複数の将来セッションで参照される安定した運用ルールは `logic` として残せる。

## 全件判定

| # | namespace / fact_id | 現statement（要約） | 判定 | 再発場面と反実仮想差／specific reason |
|---:|---|---|---|---|
| 1 | backoffice / `01KWKZCPCBS1FM8GVTX5RTH2B3` | backoffice-automationはaccounting一本化、互換ファサード残置 | **無効化** | 同repoの機能追加時という場面は再発するが、実装先・package構成・互換ファサードはREADME、package tree、entry pointsがcurrent SoTである。PLK取得がなくてもrepoを読めば同じ判断になり、変更時にはPLKだけが陳腐化する。過去決定の記録はREADME/ADR/git historyへ置く。 |
| 2 | backoffice / `01KWX01KWBQAXC68N39NEBRWQE` | 手続き系ブラウザ操作はByteflare profileのChrome Plugin | **維持** | 行政・税務・社保・経理・共済などの手続き操作は今後も現実的に繰り返す。取得しない場合はin-app browserや別profileを選び、login state・証明書・拡張・本人認証がずれる。取得すればByteflare profileの既存Chrome tabを最初に選ぶ。人間の明示した条件付き運用規範で、可変な認証情報は複製していない。 |
| 3 | backoffice / `01KWGM7ZH366AZSB442K5YSTAV` | freee事業所の切替日とcompany_id | **無効化** | これは2026年の一度きりの個人事業→法人移行と現在のroute設定値。将来の日付別事業所選択は `config/rules.yml` を読むべきで、ID・境界をPLKへ複製すると二重管理になる。新たな法人切替を仮定しなければ同じ判断場面も再発しない。 |
| 4 | backoffice / `01KWGM7ZM0PMX4HQRJPFGA7EXQ` | 持続化補助金は法人の方が有利という助言で法人申請 | **無効化** | Byteflareは既に法人であり、個人事業と法人のどちらを申請主体にするかという同じ選択は現実的に再発しない。単一担当者の助言を制度上の持続的事実へ一般化もできず、次回公募では最新要領と支援機関へ確認すべき。一件の申請case記録に置く。 |
| 5 | backoffice / `01KWGM7ZFKKHYX7CD2CZX4SFC9` | Gmail領収書を発行元blacklistで除外し、除外を明示 | **維持** | Gmailからの領収書収集・freee登録は月次で再発し、不要な発行元が候補へ混ざる。取得しない場合は不要候補を毎回手作業で判断するか誤登録しうる。取得すれば、可変な除外先そのものは `receipt_blacklist.yml` から読み、filter後も除外結果をユーザーへ明示する。PLKは値でなく安定した運用ルールを保持している。 |
| 6 | backoffice / `01KWGM7ZNHJR5XY04FMFPYMKCM` | 領収書はGmailとlocal directoryを横断収集 | **置換** | 領収書収集は月次で再発し、実際にGmail外へ保存された書類がある。取得しない場合はGmailだけで完了扱いして漏らす。取得すればGmailとローカル保存先の双方を対象にする。ただし現ファクトは観測を `knowhow` として書き、領収書でない行政・契約書まで広げているため、条件付き運用規範へ原子化する。置換案は下記。 |
| 7 | biz / `01KWGM7ZQ0VV8R01YP2VXAAJ2P` | 会社の確定数値・IDはNotion法人ファクトDBをSoTにする | **維持** | 会社情報はフォーム、請求、契約、税務・社保等で繰り返し必要になる。取得しない場合は古い散文・local memo・PLKのコピーを使いうる。取得すれば毎回Notion法人ファクトDBをqueryし、値を別知識ベースへ複製しない。PLKは値ではなくSoT routing ruleのみを保持する。 |
| 8 | biz / `01KWGM7ZRG22SPSVMNZPPFH3CZ` | Notion新規pageはteam spaceのcategory配下へ置く | **維持** | ByteflareのNotion page作成は継続して再発する。取得しない場合はHOME/Wiki hub直下へ迷子pageを作りうる。取得すればHOMEから該当team/categoryを確認して配下へ作る。category名などの全mappingはNotion/設計書をSoTとし、PLKはplacement ruleだけを保持する。 |
| 9 | biz / `01KX047XRT5033WYTKG9VA71C8` | AI業務診断で人間に残す3種の役割境界 | **維持** | AI業務診断の案件運用・skill・SaaS・自動化設計で、人間とAIの責務分界は繰り返し判断される。取得しない場合は制作工程を人間へ戻す、または対人・品質保証・承認まで自動化する局所判断が起こりうる。取得すれば3境界を守り、KPIや詳細工程はNotion SoTで最新確認する。安定した商品運用logicの最小蒸留として妥当。 |
| 10 | dev / `01KWKZCW2VBRE0NF0MPS4THZH3` | uv repo移動後のstale shebangはvenv再作成で復旧 | **維持** | Byteflareでは複数のuv/Python repoを扱い、directory移動・renameや同症状のdiagnosisは現実的に再発する。取得しない場合はpytest/CLIの `No such file or directory` をsource/import障害として追う。取得すればまずvenv shebangを確認し、移動が原因なら再構築する。単発repoの構成ではなく再現可能なtool挙動。 |
| 11 | dev / `01KWGM7Z8FSN0WWG69TZKKNM0F` | graphiti 0.29.2/FalkorDBのgroup分離とclear_data | **無効化** | 適用先はplk-memoryのgraph index実装・reindexだけで、現在のversion pin、`graphindex.py`、migration/design docsから復元できるbackend固有の実装詳細。version/backend変更時には前提が変わるためPLK取得よりinstalled source/current codeを確認すべき。repo SoT複製。 |
| 12 | dev / `01KWGM7Z9V4FZKT04YQE6QAM9E` | graphiti日本語MinHash dedupeは未merge PRにより不全 | **無効化** | 未merge PRの状態は短命で、現在の正否はupstreamとinstalled versionを都度確認すべき。PLK側の重複防止は現行CONVENTIONS/tool policy/codeで管理され、Graphiti依存方式もrepo設計事項。同じ設計判断が起きても古いPR状態の取得はむしろ誤判断を招く。 |
| 13 | dev / `01KWGM7ZB9J7QPP97CSRSSAZR5` | graphiti add_episode promptは英語のみ、issue未解決 | **無効化** | upstream issue status・prompt実装はversionで変わる一時状態で、適用先もplk-memoryのepisode ingestに限定される。現在はrepoのrendering、GraphIndex、評価設計、installed sourceを確認すべきで、過去issueをPLKから取得して英訳/人間reviewを固定するのは危険。repo SoTとupstream current docsへ戻す。 |
| 14 | dev / `01KWGM7ZE5DFW8HH0DF71H0E9T` | validatorのrglobにSKIP_NAMESが必要 | **無効化** | `repo_checks.py` の現在実装をそのまま説明したrepo固有の保守知識。validatorを変更する場面はあり得るが、取得しなくてもcurrent code/testを読むことで同じ判断になり、scanner設計変更時にはPLKが陳腐化する。コメント・test・developer docsがSoT。 |

## 置換案（exact fields）

### `01KWGM7ZNHJR5XY04FMFPYMKCM` の後継

- `statement`: `Byteflareの領収書収集では、Gmailだけで完了扱いせず、対象期間のローカル保存先も併せて検索する。`
- `kind`: `logic`
- `namespace`: `plk.domain.backoffice`
- `why`: `Byteflareでは領収書がGmail添付だけでなくダウンロード・スキャン等でローカルにも保存され、Gmail検索だけでは月次処理の候補漏れが実際に起こるため。`
- `how_to_apply`: `月次経理やfreee登録のため領収書を収集するときは、対象期間を揃えてByteflare用Gmailと領収書のローカル保存先を双方検索する。具体的なアカウント・ディレクトリ・コマンドはreceipt-to-freeeスキルの現行runbookを参照する。行政・契約書など領収書でない文書はこのルールの対象に含めない。`
- `supersedes`: [`01KWGM7ZNHJR5XY04FMFPYMKCM`]
- 将来の取得状況: 月次経理、freee登録、領収書候補収集を開始するとき。
- 取得しない場合との差: Gmail検索だけで完了してローカル保存分を漏らす可能性があるところ、双方を検索してから候補確定する。

## 件数照合

- 入力active: **14件**
- 維持: **6件**（#2, #5, #7, #8, #9, #10）
- 置換: **1件**（#6）
- 無効化: **7件**（#1, #3, #4, #11, #12, #13, #14）
- 合計: **6 + 1 + 7 = 14件**

対象IDは `plk_search(namespaces=[backoffice,biz,dev], status=active)` の14件と、agent-organizationのfrontmatterを照合した。書き込み・無効化操作は実施していない。

## 規制領域・shared active 12件の再評価

| file / id | 判定 | 西川将弘／Byteflareでの現実的再発性と措置 |
|---|---|---|
| tax/aoiro-shonin-3kagetsu.md / 01KWGM7YT2S5CAS37F9DQ44Z2R | 無効化 | Byteflareの設立時申請は完了済みで、別法人設立を仮定しない限り再発しない。法人設立記録へ置く。 |
| tax/gensen-tokurei-nenidokai.md / 01KWGM7YVH2NHMGQKJRSK65GBR | 置換 | 源泉税納付は毎年再発する。常時10人未満・対象所得・適用開始条件を含むknowhowへ置換する。 |
| tax/hojin-todokede-2kagetsu.md / 01KWGM7YRK3DZAQ22T1YDS8BK8 | 無効化 | Byteflareの法人設立届は完了済み。理論上の別法人向け知識はPLK対象外。 |
| tax/jizokuka-menzei-zeikomi.md / 01KWGM7YWYDF37N8W0YPD72V9N | 無効化 | 今回の公募・申請に閉じ、公募回ごとに変わる。案件記録と当該回の公募要領がSoT。 |
| legal/kabunushisoukai-gijiroku-hokan.md / 01KWGM7YZT4B6BCXEA1D0F5KRJ | 置換 | 株主総会と議事録保管は今後も再発する。10年備置義務だけへ原子化し、Notion/iCloud構成を除く。 |
| legal/onestop-sumaho-qr-shomei.md / 01KWGM7YYB2VMET2HH8KPN7XW4 | 無効化 | 法人設立は再発せず、e-Tax WEB版の現行スマホ対応とも矛盾する。 |
| legal/yakuinhoshu-soukai-ketsugi.md / 01KWGM7Z196FSMZ94CRZW927XH | 置換 | 役員報酬の見直しは将来再発し得る。会社法361条と既存決議の枠を確認する正確なknowhowへ置換する。 |
| shaho/daihyousha-kyousei-kanyu.md / 01KWGM7Z47WQD8WAPFE6X2870J | 無効化 | 法人新規適用はByteflareで完了済み。別法人設立を仮定しない限り同じ場面は再発しない。 |
| shaho/fuyousha-shikaku-teisei-daikou-risk.md / 01KWGM7Z5NFNNMV0WN24APSXP6 | 置換 | 家族の扶養資格変更は現実的に再発し得る。特定業者の単発事故を除き、健保と第3号双方を確認するlogicへ置換する。 |
| shaho/kokuho-nige-tsutatsu-2026.md / 01KWGM7Z2TW1B2Z0EJXGXQNGPY | 置換 | 社保加入スキームの適法性評価は継続判断になり得る。民間サービス構成を除き、実態確認のlogicへ置換する。 |
| shaho/kokunen-tainou-hochi-risk.md / 01KWGM7Z726ZSM8WFDYQVX6JJR | 置換 | 資格訂正中の納付案内への対応は再発し得る。個人事例を除き、未納放置を避けるknowhowへ置換する。 |
| shared/mcp-sdk-pin-lifespan.md / 01KWGM7ZCQX90Q7PP7D8QYV3B3 | 無効化 | version・issue状態は短命で、各repoの依存定義・公式README・CIがSoT。issue #1367も既にclosed。 |

### 規制領域の置換案（exact fields）

1. 源泉所得税の納期特例
   - statement: 常時使用する給与支給人員が10人未満で納期の特例の承認を受けた場合、給与・退職手当および一定の士業報酬から源泉徴収した所得税を年2回にまとめて納付できる。
   - kind: knowhow
   - how_to_apply: 源泉税の納付予定を作るたびに、対象所得と適用開始月を国税庁の現行案内で確認し、承認前の源泉税を特例扱いしない。
2. 株主総会議事録
   - statement: 株式会社は株主総会の日から10年間、株主総会議事録を本店に備え置く。
   - kind: knowhow
   - how_to_apply: 株主総会後に、10年間閲覧・提示できる形で本店備置の記録へ保存する。具体的な保管先は法務運用SoTで確認する。
3. 役員報酬決議
   - statement: 取締役報酬を定款で定めていない場合は、額・算定方法等を株主総会決議で定める。変更時は定款と既存決議の総額枠・算定方法の範囲を確認し、範囲外なら株主総会へ付議する。
   - kind: knowhow
   - how_to_apply: 役員報酬を見直す前に定款と直近決議を確認し、会社法上の決議要否を判定する。税務上の定期同額給与は別途確認する。
4. 被扶養者資格変更
   - statement: 被扶養配偶者の資格得喪日を変更・訂正したときは、健康保険の被扶養者記録と国民年金第3号被保険者記録の双方への反映を確認する。
   - kind: logic
   - how_to_apply: 変更・訂正の完了連絡後に、健保と年金の両方の記録を確認し、片方だけなら年金事務所または提出先へ是正を依頼する。
5. 法人役員を介した社保加入
   - statement: 法人役員としての社会保険加入スキームを検討・継続するときは、肩書だけで判断せず、経常的な経営参画・労務と業務対価としての経常的報酬の実態を現行の公式基準で確認する。
   - kind: logic
   - how_to_apply: 契約開始・更新・制度変更時に厚生労働省と日本年金機構の現行基準を確認し、実態を証拠化できなければ加入前提で進めない。
6. 国民年金の未納案内
   - statement: 国民年金保険料は督促状の指定期限後に納付すると延滞金が発生し、未納継続時は差押えへ進む可能性がある。
   - kind: knowhow
   - how_to_apply: 資格訂正中でも納付案内や督促が届いたら放置せず、指定期限前に年金事務所へ連絡し、納付・訂正・免除・猶予の扱いを確定する。

- 規制領域集計: 維持0、置換6、無効化6、計12。
