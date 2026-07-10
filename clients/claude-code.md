# Claude Code 接続

```bash
export PLK_TOKEN=<発行されたトークン>
claude mcp add --transport http plk http://127.0.0.1:8735/mcp --header "Authorization: Bearer ${PLK_TOKEN}"
```

- `.mcp.json` をプロジェクト共有する場合は `${PLK_TOKEN:-}` とデフォルト付きで書く（未定義だと設定パース自体が失敗する）
- ツール名は `mcp__plk__plk_search` 形式
- サーバー停止時は非ブロッキング（セッション継続・自動再接続）

## 常駐前提の注意（Mac launchd 常駐運用）

- plk-memory は launchd 常駐（`com.byteflare.plk-memory`）のため手動起動は不要。`http://127.0.0.1:8735/mcp` に常時接続できる想定で登録してよい。
- サーバー停止時は縮退動作（メモリなしでセッション続行。`plk_search` が呼べないだけでセッション自体はブロックされない）。
- `claude mcp add --header` はトークンを値としてローカル設定（`~/.claude.json` 等）に literal 保存する。実行前に `export PLK_TOKEN=<Claude Code 用トークン>` してから `--header "Authorization: Bearer ${PLK_TOKEN}"` の形でコマンドを打つこと。
