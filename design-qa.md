# Design QA — PLK 利用状況

- source visual truth: `/Users/masahiro/.codex/generated_images/019fdc28-5852-7831-a036-0b3e8ac47be1/exec-742c828e-a748-4f17-b318-98526a005f52.png`
- implementation screenshot: `/Users/masahiro/.codex/visualizations/2026/08/07/019fdc28-5852-7831-a036-0b3e8ac47be1/plk-usage-implementation-final-pass.png`
- dark-mode screenshot: `/Users/masahiro/.codex/visualizations/2026/08/07/019fdc28-5852-7831-a036-0b3e8ac47be1/plk-usage-dark-mode.png`
- combined comparison: `/Users/masahiro/.codex/visualizations/2026/08/07/019fdc28-5852-7831-a036-0b3e8ac47be1/plk-usage-design-qa-final.png`
- viewport: 1440 x 1024 CSS px
- source pixels: 1487 x 1058, normalized with contain-fit to 1440 x 1024
- implementation pixels: 1440 x 1024
- device scale factor: 1
- state: 判断価値タブ、実データ読込済み、`insufficient_data`

## Full-view comparison evidence

選択案の情報階層（判定バナー → 3指標 → 週次チャート → 次のアクション）を維持した。既存PLKの上部ナビゲーションはプロダクト制約として残し、参照案の大規模な左ナビゲーションは導入していない。暖色キャンバス、オレンジの状態アクセント、連続した指標ストリップ、判定不能週のハッチ、運用キュー型CTAは参照案と同じ役割で実装されている。

## Focused comparison evidence

全体比較画像で主要コンポーネントの文字・罫線・状態色・棒グラフラベルまで判読できたため、追加のクロップ比較は不要だった。特にKPIの分母、`判定不能`、目標線、自己申告注記、CTA文言を確認した。

## Required fidelity surfaces

- Fonts and typography: 既存のGeist系フォールバックを維持し、見出し650、本文14px、補助12pxで参照案の密度へ調整した。日本語の折返しと数値のtabular表示に問題なし。
- Spacing and layout rhythm: 1440px幅で主要アクションの先頭がファーストビューに見えるよう、ヘッダー、判定バナー、KPI、チャートを圧縮した。カード内カードはない。
- Colors and visual tokens: 暖色キャンバス、白いデータ面、`#f54e00`の単一アクセント、薄いオレンジの注意面に限定した。状態は文字と形でも判別できる。
- Image quality and asset fidelity: 参照案に写真・イラスト・独自ロゴ資産はない。データ可視化はブラウザネイティブSVGで鮮明に描画されている。
- Copy and content: 実APIの値、`insufficient_data`、因果を示さない注記、未計測25件の次アクションを保持した。

## Comparison history

1. P2: 初回実装では判定バナーとチャートが縦に長く、主要アクションが1440 x 1024の下へ隠れた。
   - fix: バナー注記を本文へ統合し、KPI高、セクション間隔、チャート高を圧縮した。
   - post-fix evidence: `plk-usage-implementation-final-pass.png` で主要アクションの先頭がファーストビューに入り、情報順序も維持された。
2. P2: 値が0の判定不能週が空白になり、データ欠損とゼロ件を視覚的に区別しにくかった。
   - fix: 値の棒とは別のハッチ付き判定不能プレースホルダーとラベルを追加した。
   - post-fix evidence: 07/06、07/13、07/20が明示的な判定不能領域として表示された。

## Interaction and runtime checks

- tested: 判断価値 / 検索品質 / データ状態のタブ切替
- tested: データ表 disclosure
- checked: browser console errors = 0
- checked: launchd runtime restart後に実データを再読込
- checked: `prefers-color-scheme: dark` 環境で暗色トークンとSVGチャート色が適用されることを実画面で確認

## Findings

P0/P1/P2の未解決事項なし。左ナビを導入しない差分は、既存PLKの小規模な情報構造を守るための意図的な適応。

## Follow-up polish

- P3: 画面幅が十分ある場合、チャートの棒内に18件 / 31件の値ラベルを追加すると参照案へさらに近づく。

final result: passed
