"""Claude Agent SDK からの plk-memory 接続検証スクリプト（Phase 2 Task 10）。

`clients/agent-sdk.md` のサンプルを実行可能にしたもの。自作エージェント（Agent SDK）
から plk-memory MCP サーバーに接続し、`plk_search` を 1 回呼んでヒットを確認する。

前提:
- plk-memory が launchd 常駐で `http://127.0.0.1:8735/mcp` に立っている（`curl -s localhost:8735/healthz`）
- 環境変数 `PLK_TOKEN_AGENT` に「custom-agent」identity のトークンがセットされていること
  （`.env` の `PLK_TOKENS` に登録済みのトークンを `export PLK_TOKEN_AGENT=...` する）
- `uv sync --group examples`（`claude-agent-sdk` を dev 依存として追加済み）

実行:
    uv run --group examples python examples/sdk_client_check.py [query]

サーバーが縮退・停止していても例外で落とさず、結果を分かりやすく表示して終了する
（`clients/README.md` の「タイムアウト→メモリなしで続行」契約に合わせた失敗時の振る舞い）。
"""

from __future__ import annotations

import asyncio
import os
import sys

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, TextBlock, ToolUseBlock

PLK_URL = "http://127.0.0.1:8735/mcp"
DEFAULT_QUERY = "持続化補助金の経費は税込か"


async def main() -> int:
    token = os.environ.get("PLK_TOKEN_AGENT")
    if not token:
        print("NG: 環境変数 PLK_TOKEN_AGENT が未設定（.env の PLK_TOKENS で custom-agent 用トークンを確認して export すること）")
        return 1

    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY

    options = ClaudeAgentOptions(
        mcp_servers={
            "plk": {
                "type": "http",
                "url": PLK_URL,
                "headers": {"Authorization": f"Bearer {token}"},
            }
        },
        allowed_tools=["mcp__plk__plk_search"],
        system_prompt=(
            "You must call the mcp__plk__plk_search tool exactly once with the given query "
            "and reason='sdk-client-check', then report whether it returned any hits."
        ),
        max_turns=3,
    )

    saw_tool_use = False
    final_text_parts: list[str] = []

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(f"plk_search を reason='sdk-client-check' で呼び、'{query}' を検索して。結果を1行で。")
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock) and "plk_search" in block.name:
                            saw_tool_use = True
                        if isinstance(block, TextBlock):
                            final_text_parts.append(block.text)
    except Exception as e:  # noqa: BLE001 - 接続検証スクリプトなので縮退して報告する
        print(f"NG: plk-memory への接続に失敗（縮退動作の確認: サーバー停止時はここに来る想定）: {e}")
        return 1

    print(f"tool_use 確認: {'OK' if saw_tool_use else 'NG（ツールが呼ばれなかった）'}")
    if final_text_parts:
        print("応答:", " ".join(final_text_parts))
    return 0 if saw_tool_use else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
