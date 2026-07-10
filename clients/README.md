# クライアント接続テンプレート

plk-memory（plk）への各エージェントクライアントからの接続手順テンプレート。

## 一覧

| ファイル | 対象 |
|---|---|
| [claude-code.md](./claude-code.md) | Claude Code |
| [codex.md](./codex.md) | Codex CLI |
| [hermes.md](./hermes.md) | Hermes Agent |
| [agent-sdk.md](./agent-sdk.md) | Claude Agent SDK（自作エージェント） |
| [guideline-line.md](./guideline-line.md) | 検索動線（1 行・全クライアント共通） |

## 共通事項

- **タイムアウト → メモリなしで続行**: plk サーバーが無応答・停止していても、各クライアントはセッションをブロックせず処理を継続する契約とする（クライアントごとの挙動は各ファイル参照）。plk-memory は思い出す・記録することが処理成功の必須条件ではない。
- **トークンは環境変数のみ**: 接続設定に平文トークンを直接書き込まない。`PLK_TOKEN` 等の環境変数経由で渡す（Codex は環境変数以外の指定を拒否する仕様）。
- **トークン発行**: サーバー側の `.env` の `PLK_TOKENS` にトークンを追記し、サーバーを再起動することで発行する。
