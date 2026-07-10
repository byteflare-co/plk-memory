# Hermes Agent 接続

`~/.hermes/config.yaml`:

```yaml
mcp_servers:
  plk:
    url: http://127.0.0.1:8735/mcp
    headers:
      Authorization: "Bearer ${PLK_TOKEN}"
```

- ツール名は `mcp_plk_plk_search` 形式（アンダースコア 1 つ）
- Hermes は接続時に content-type を検査する。plk-memory はエラー時も JSON を返す設計なので相性問題なし

## 常駐前提の注意（Mac launchd 常駐運用）

- plk-memory は launchd 常駐のため手動起動不要。停止中は plk_search 系ツールがエラーを返すのみで Hermes 自体はブロックされず縮退動作（メモリなしで続行）。
- `${PLK_TOKEN}` は Hermes 起動シェルの環境変数（`export PLK_TOKEN_HERMES=<Hermes 用トークン>`、必要なら `config.yaml` 側の参照名も揃える）で渡す。設定ファイルへの平文直書きはしない。
- `~/.hermes/config.yaml` を編集する際は必ず事前にバックアップを取ること（既存設定を壊さない）。
