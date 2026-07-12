"""REST/MCP ファサードの型定義。

AppServices（Git backend）と PostgresAppServices は duck typing で同一のツール面
（tool_* / ui_*）を提供する。この Union が現状の契約表現であり、mcp_tools / webui /
app が共有する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plk_memory.git_services import AppServices
    from plk_memory.postgres.application import PostgresAppServices

    ServiceFacade = AppServices | PostgresAppServices

__all__ = ["ServiceFacade"]
