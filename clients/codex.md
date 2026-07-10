# Codex CLI 接続

```bash
codex mcp add plk --url http://127.0.0.1:8735/mcp --bearer-token-env-var PLK_TOKEN
```

- トークン直書きは Codex が拒否する仕様。必ず環境変数で
- **注意**: Codex はサーバー無応答時に初回ターンが startup_timeout（既定 10 秒）ブロックされる既知課題がある。plk-memory を停止する時は `[mcp_servers.plk] enabled = false` で一時無効化を推奨

## 常駐前提の注意（Mac launchd 常駐運用）

- plk-memory は launchd 常駐のため通常は手動起動不要。ただし上記の 10 秒ブロック既知課題があるため、長期停止（メンテナンス等）を予定する場合は事前に `~/.codex/config.toml` の `[mcp_servers.plk] enabled = false` にしておくこと。再開後は `enabled = true` に戻す。
- `PLK_TOKEN` はシェルの起動プロファイル（`~/.zshrc` 等）に `export PLK_TOKEN_CODEX=<Codex 用トークン>` を追記し、`--bearer-token-env-var PLK_TOKEN_CODEX` で参照する（Claude Code 用トークンと混在させない）。
