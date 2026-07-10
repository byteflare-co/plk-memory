# Claude Agent SDK（自作エージェント）接続

```python
import os
from claude_agent_sdk import ClaudeAgentOptions

options = ClaudeAgentOptions(
    mcp_servers={
        "plk": {
            "type": "http",
            "url": "http://127.0.0.1:8735/mcp",
            "headers": {"Authorization": f"Bearer {os.environ['PLK_TOKEN']}"},
        }
    },
    allowed_tools=["mcp__plk__*"],
)
```

- `allowed_tools` の明示が必須（無いとツールが見えても呼べない）

## 常駐前提の注意（Mac launchd 常駐運用）

- plk-memory は launchd 常駐のため手動起動不要。停止中に接続すると `mcp_servers` 呼び出しがエラーを返すが、SDK 側での try/except で縮退（メモリなしで続行）できるようにハンドリングすること。
- `PLK_TOKEN`（自作エージェント用トークン）は環境変数で渡す。動作確認用スクリプトは `examples/sdk_client_check.py` を参照。
