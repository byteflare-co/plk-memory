"""live マーカー付きテストの前提条件チェック。

このリポジトリのローカル実行は Anthropic API を使わず、FalkorDB と
ローカル Ollama（OpenAI 互換エンドポイント）に対して実接続する。
前提が満たされない場合は「静かに skip」ではなく明示的に fail させ、
何が到達不能なのかをメッセージに含める（brief の指示）。
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.request

import pytest

from plk_memory.settings import Settings


def _check_falkordb(host: str, port: int) -> str | None:
    try:
        with socket.create_connection((host, port), timeout=3):
            return None
    except OSError as e:
        return f"FalkorDB に接続できない（{host}:{port}）: {e}"


def _check_ollama(base_url: str) -> str | None:
    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 - localhost 固定
            if resp.status != 200:
                return f"Ollama /models が HTTP {resp.status} を返した（{url}）"
            return None
    except (urllib.error.URLError, OSError) as e:
        return f"Ollama に接続できない（{url}）: {e}"


def _live_prerequisites() -> list[str]:
    s = Settings(
        tokens={"t": "c"},
        admin_token="a",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    checks = [
        _check_falkordb(s.falkordb_host, s.falkordb_port),
        _check_ollama(s.llm_base_url),
    ]
    if s.embedder_base_url != s.llm_base_url:
        checks.append(_check_ollama(s.embedder_base_url))
    return [c for c in checks if c]


@pytest.fixture(scope="session", autouse=True)
def _require_live_prerequisites(request):
    """live テストが 1 つでも収集された場合のみ前提を検証する。

    skip ではなく fail させる（brief の指示）。前提未達なら何が到達不能かを
    メッセージに明示する。
    """
    live_selected = any(
        item.get_closest_marker("live") for item in request.session.items
    )
    if not live_selected:
        return
    problems = _live_prerequisites()
    if problems:
        pytest.fail(
            "live テストの前提が未達:\n  - " + "\n  - ".join(problems),
            pytrace=False,
        )
