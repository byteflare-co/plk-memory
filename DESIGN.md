---
version: alpha
name: PLK Evidence Ledger
description: A restrained, evidence-first interface for reviewing personal knowledge and its observed contribution to decisions.
colors:
  primary: "#F54E00"
  primary-dark: "#FF6A2A"
  canvas: "#FAFAFA"
  canvas-dark: "#101010"
  surface: "#FFFFFF"
  surface-dark: "#181818"
  surface-warm: "#F7F6F2"
  surface-warm-dark: "#12110F"
  surface-attention: "#FFFAF2"
  surface-attention-dark: "#211A14"
  text-primary: "#171717"
  text-primary-dark: "#F2F2F2"
  text-body: "#4D4D4D"
  text-body-dark: "#C6C6C6"
  text-muted: "#8F8F8F"
  text-faint: "#A1A1A1"
  border: "#EBEBEB"
  border-dark: "#2A2A2A"
  border-strong: "#D4D4D4"
  border-strong-dark: "#414141"
  attention-border: "#F2C893"
  attention-border-dark: "#604226"
  link: "#0070F3"
  link-dark: "#52A8FF"
  error: "#EE0000"
  error-dark: "#FF6B6B"
  on-primary: "#FFFFFF"
  on-primary-dark: "#101010"
typography:
  page-title:
    fontFamily: Geist Sans, Geist, Inter, Hiragino Sans, sans-serif
    fontSize: 28px
    fontWeight: 650
    lineHeight: 36px
    letterSpacing: -0.04em
  section-title:
    fontFamily: Geist Sans, Geist, Inter, Hiragino Sans, sans-serif
    fontSize: 22px
    fontWeight: 650
    lineHeight: 28px
    letterSpacing: -0.025em
  card-title:
    fontFamily: Geist Sans, Geist, Inter, Hiragino Sans, sans-serif
    fontSize: 17px
    fontWeight: 650
    lineHeight: 24px
    letterSpacing: -0.02em
  body-md:
    fontFamily: Geist Sans, Geist, Inter, Hiragino Sans, sans-serif
    fontSize: 14px
    fontWeight: 400
    lineHeight: 20px
  body-lg:
    fontFamily: Geist Sans, Geist, Inter, Hiragino Sans, sans-serif
    fontSize: 16px
    fontWeight: 400
    lineHeight: 24px
  label-md:
    fontFamily: Geist Sans, Geist, Inter, Hiragino Sans, sans-serif
    fontSize: 14px
    fontWeight: 600
    lineHeight: 20px
  label-sm:
    fontFamily: Geist Mono, JetBrains Mono, IBM Plex Mono, monospace
    fontSize: 12px
    fontWeight: 500
    lineHeight: 16px
  data-display:
    fontFamily: Geist Sans, Geist, Inter, Hiragino Sans, sans-serif
    fontSize: 38px
    fontWeight: 650
    lineHeight: 40px
    letterSpacing: -0.045em
spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 40px
  3xl: 64px
  desktop-gutter: 24px
  mobile-gutter: 16px
rounded:
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  full: 9999px
components:
  app-shell:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.text-primary}"
  app-shell-dark:
    backgroundColor: "{colors.canvas-dark}"
    textColor: "{colors.text-primary-dark}"
  metrics-shell:
    backgroundColor: "{colors.surface-warm}"
    textColor: "{colors.text-body}"
  metrics-shell-dark:
    backgroundColor: "{colors.surface-warm-dark}"
    textColor: "{colors.text-body-dark}"
  metadata:
    textColor: "{colors.text-muted}"
    typography: "{typography.label-sm}"
  subdued-metadata:
    textColor: "{colors.text-faint}"
    typography: "{typography.label-sm}"
  divider:
    backgroundColor: "{colors.border}"
    height: 1px
  divider-dark:
    backgroundColor: "{colors.border-dark}"
    height: 1px
  divider-strong:
    backgroundColor: "{colors.border-strong}"
    height: 1px
  divider-strong-dark:
    backgroundColor: "{colors.border-strong-dark}"
    height: 1px
  attention-outline:
    backgroundColor: "{colors.attention-border}"
    height: 1px
  attention-outline-dark:
    backgroundColor: "{colors.attention-border-dark}"
    height: 1px
  focus-indicator:
    backgroundColor: "{colors.link}"
    size: 2px
  focus-indicator-dark:
    backgroundColor: "{colors.link-dark}"
    size: 2px
  error-copy:
    textColor: "{colors.error}"
    typography: "{typography.body-md}"
  error-copy-dark:
    textColor: "{colors.error-dark}"
    typography: "{typography.body-md}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: 8px 16px
    height: 36px
  button-primary-dark:
    backgroundColor: "{colors.primary-dark}"
    textColor: "{colors.on-primary-dark}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: 8px 16px
    height: 36px
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-primary}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: 8px 16px
    height: 36px
  button-secondary-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.text-primary-dark}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: 8px 16px
    height: 36px
  metric-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: 16px
  metric-card-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.text-primary-dark}"
    rounded: "{rounded.md}"
    padding: 16px
  attention-summary:
    backgroundColor: "{colors.surface-attention}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: 16px
  attention-summary-dark:
    backgroundColor: "{colors.surface-attention-dark}"
    textColor: "{colors.text-primary-dark}"
    rounded: "{rounded.md}"
    padding: 16px
  status-tag:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-body}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.sm}"
    padding: 4px 10px
  status-tag-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.text-body-dark}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.sm}"
    padding: 4px 10px
---

# PLK Evidence Ledger Design System

## Overview

PLK Memoryは、記憶の内容と、その記憶が意思決定へどう寄与したかを確認するための読み取り中心の業務画面である。見た目の目的は「賑やかさ」ではなく、観測事実、判定の確かさ、次の行動を短時間で区別できることにある。

デザインの人格は、落ち着いた分析ツール、精密な台帳、控えめな運用コンソール。PostHog系の親しみやすいデータツール感を参照しつつ、PLKの小規模な情報構造に不要なサイドバーや機能一覧は持ち込まない。

`src/plk_memory/static/index.html` のCSSカスタムプロパティと `src/plk_memory/static/app.js` の描画実装が現在のレンダリングSoTである。この文書は、新規UIを同じ方向で生成・レビューするための規範であり、実装変更時は同時に更新する。

### Core principles

1. 最初に判定、その次に根拠、最後に次の行動を置く。
2. `insufficient_data` を0件や成功に見せない。
3. 色だけで状態を伝えず、文言、形、ラベルを併用する。
4. 面を増やす前に、余白、整列、文字、区切り線で階層を作る。
5. オレンジは選択状態、主要アクション、重要なデータ系列に限定する。
6. ダークモードは単純反転ではなく、同じ意味階層を暗色トークンで再構成する。

## Colors

ライトモードは暖かいオフホワイトのキャンバスと白いデータ面、ダークモードは黒に近いキャンバスと炭色のデータ面を使う。OSの `prefers-color-scheme` に自動追従する。

- **Primary orange:** `primary` / `primary-dark`。選択中タブの下線、主要CTA、チャートの第2系列、進捗メーターに使う。装飾目的の面塗りやコンポーネント左端の色帯には使わない。
- **Canvas:** `canvas` / `canvas-dark`。アプリ全体の基底面。
- **Warm canvas:** `surface-warm` / `surface-warm-dark`。利用状況ビューのわずかに暖かい背景。
- **Surface:** `surface` / `surface-dark`。カード、入力、ナビゲーション、テーブルのデータ面。
- **Attention surface:** `surface-attention` / `surface-attention-dark`。判定保留など、注意は必要だがエラーではない状態。
- **Text:** `text-primary` は見出しと主要値、`text-body` は説明、`text-muted` と `text-faint` は補助情報に使う。
- **Borders:** `border` は通常の区切り、`border-strong` はホバーや選択可能性を補う場合だけ使う。
- **Semantic colors:** `link` はリンクとフォーカス、`error` は失敗・破壊的状態に限定する。

既存のライトモード主要ボタンは `#F54E00` 上に白文字を置いており、14px文字ではWCAG AAの4.5:1を満たさない（公式lint計算は3.52:1）。この文書は現状を正確に記録するため当該トークンを維持するが、新規コンポーネントへこの組み合わせを拡大しない。背景を暗くするか、前景を濃色へ変更する改善を別変更として行う。

チャートも同じテーマへ追従する。SVG属性にはCSS変数を渡し、ライト固定のhex値を埋め込まない。グリッド線は背景よりわずかに明るい／暗い程度に抑え、系列より目立たせない。

## Typography

サンセリフはGeist系を第一候補とし、日本語ではHiragino Sansへ自然にフォールバックする。数値、日時、短いメタデータ、表見出しにはGeist Mono系を使う。フォントは2系統を超えない。

- **Page title:** 28/36px、650。ページの主目的だけに使う。
- **Section title:** 22/28px、650。判定バナーなど強い区切り。
- **Card title:** 17/24px、650。チャート、表、アクションキュー。
- **Body:** 原則14/20px。長めの説明だけ16/24pxを許可する。
- **Labels:** 操作ラベルは14/20px、600。技術ラベルとメタデータはMono 12/16px、500。
- **Data display:** KPIは38/40px、650、tabular numbers。単位は値より小さく、弱い色にする。

英語ラベルを機械的に大文字化しない。日本語UIでは、短い自然な名詞句を優先する。

## Layout

デスクトップは最大幅1200px、左右24pxのガターを持つ固定最大幅レイアウト。モバイルは720px以下で1カラムへ切り替え、左右ガターを16pxにする。

基本単位は4px。実際のコンポーネント間隔は8、12、16、24、32pxを中心に構成し、40pxと64pxは大きなセクション境界だけに使う。

利用状況の情報順序は固定する。

1. ページタイトル、説明、更新時刻
2. `判断価値 / 検索品質 / データ状態` のサブタブ
3. 状態サマリー
4. 根拠となる3つのKPI
5. 週次チャートまたは詳細表
6. 最優先の次アクション
7. disclosure内の補助情報

デスクトップでは主要アクションの先頭が1440×1024の初期表示に入る密度を目安とする。モバイルではKPIを縦積みにし、タップ対象を最低44pxに拡張する。表は必要に応じて横スクロールさせ、重要列を無理に縮めない。

## Elevation & Depth

階層は影ではなく、面の明度差、1pxの罫線、余白、タイポグラフィで表現する。通常カードは影を持たない。

モーダルや詳細ドロワーのように、実際に前後関係がある要素だけ `shadow-float` 相当の影を許可する。ログインカードにはごく弱い `shadow-whisper` を使える。

カード内カードは禁止する。関連する複数指標は1つの連続面を区切り線で分割する。

## Shapes

形は小さく実務的な角丸へ統一する。

- 6px: ボタン、入力、タブ、タグ
- 8px: KPIストリップ、チャート、判定サマリー、アクションキュー
- 12px: 標準カード、テーブルラッパー
- 16px: ログインや大きな独立パネルだけ
- full: 名前空間フィルタなど、カテゴリとして明確なチップだけ

左端の色帯、角丸へ食い込むアクセント線、片側だけ太いボーダーは禁止する。選択状態は下線、面色、文字、状態タグで示す。

## Components

### App header

高さを抑えたstickyヘッダー。左にPLKの識別、中央寄りに `Facts / 利用状況`、右に読み取り状態を置く。主画面より強い背景や影は使わない。

### View tabs

トップレベルのタブは小さなcontained control。利用状況内のサブタブは下線式とし、選択中だけprimary orangeの2px下線を表示する。タブをpillの集合にしない。

### Attention summary

`insufficient_data` などの状態を、薄い暖色面と1pxの注意色ボーダーで示す。見出し、理由、判定タグ、自己申告値であることの注記を含む。左端の色帯や警告アイコンの巨大表示は使わない。

### KPI strip

3つの根拠指標を1枚の連続面に置き、縦の1px区切り線で分割する。各指標はラベル、主要値、任意のメーター、状態タグ、分子／分母または補足を持つ。独立した浮遊カードを3枚並べない。

### Charts

ブラウザネイティブSVGで描画し、外部チャートライブラリへ依存しない。軸とグリッドは弱く、データ系列を最優先する。判定不能週は0件の棒にせず、ハッチと `判定不能` ラベルで別状態として示す。目標線には必ず値ラベルを付ける。

### Tables

見出しはMono 12/16px、本文は14/20px。数値は右揃えとtabular numbers。通常行はカード化せず、1つの表面を軽い行区切りで整理する。動的文字列は `textContent` で挿入する。

### Status tags

高さを抑えた角丸四角形。小さなドット、明示的な文言、境界線を併用する。pillを主要レイアウト要素として乱用しない。`判定保留`、`判定不能`、`目標達成` を色だけで区別しない。

### Primary action queue

最優先アクションを1件だけ表示する。左に行動名と理由、右にprimary buttonを置く。複数候補を同じ強さでカード列にしない。コンテナ左端の色帯は禁止する。

### Disclosures and detail views

補助表や内訳は既定で閉じ、`+` / `−` と明示的なラベルで開閉する。詳細ドロワーは主画面を完全に置き換えず、戻れる文脈を保つ。

### Interaction states

ホバーは境界線または文字色を1段階強める。フォーカスは2pxのlink色アウトラインと2pxオフセット。disabledは不透明度を下げるが、文言を読めないほど薄くしない。loadingは既存レイアウトの高さを維持し、集計中であることを文章で示す。

## Do's and Don'ts

- Do keep the page evidence-first: verdict, evidence, then action.
- Do preserve numerator, denominator, period, and measurement scope around every important metric.
- Do render missing or unevaluable data as `判定不能` or `データ不足 — 判定保留`.
- Do use the same semantic hierarchy in light and dark modes.
- Do use orange sparingly for active navigation, one primary action, or a meaningful chart series.
- Do keep charts, tables, and actions interactive with realistic data.
- Do update this file when changing tokens, component patterns, or visual guardrails.
- Don't add colored rails or thick one-sided borders to cards and banners.
- Don't use cards inside cards or turn ordinary rows into isolated cards.
- Don't add gradients, decorative illustration, or heavy shadows to operational screens.
- Don't infer success or zero from missing telemetry.
- Don't use color as the only status signal.
- Don't place more than one primary CTA at the same hierarchy level.
- Don't introduce a large sidebar unless the product information architecture actually grows to require it.
- Don't hard-code light-mode colors inside SVG charts; use theme tokens.
- Don't reuse the current white-on-orange primary-button pair for new small-text controls until its contrast is remediated.
