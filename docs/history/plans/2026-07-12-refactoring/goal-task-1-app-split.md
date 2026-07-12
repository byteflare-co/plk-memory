# Task 1: app.py 分割（Git ファサード / コンポジション / ASGI 結線）

## ゴール

`src/plk_memory/app.py`（661 行・3 責務混在）を、責務ごとの 3 モジュールに分割する。
挙動・公開 API・import 互換は一切変えない。

## 触ってよいファイル（これ以外は変更禁止）

- Modify: `src/plk_memory/app.py`
- Create: `src/plk_memory/git_services.py`
- Create: `src/plk_memory/composition.py`
- Create: `src/plk_memory/facade.py`
- Modify: `src/plk_memory/mcp_tools.py`（ServiceFacade 定義の置き換えのみ）
- Modify: `src/plk_memory/webui.py`（ServiceFacade 定義の置き換えのみ）

tests/・scripts/ は変更禁止（互換は再エクスポートで守る）。

## 手順

### Step 1: `git_services.py` を作成

`app.py` の `AppServices` クラス（現 54〜394 行）を **クラス名を変えずに** そのまま移動する。
モジュール docstring は「Git backend の REST/MCP ファサード（旧 app.AppServices）」の趣旨で書く。
必要な import（asyncio, time, posixpath, auth, domain, facts, gitstore, graphindex, promotions,
settings, state, sync, usage_log, github_promotion など）を移動先で解決する。
`tool_propose_promotion` 内の `import posixpath`（関数内 import）はトップレベルに移してよい（挙動同一のため）。
それ以外のコード・コメント・docstring は一字一句保持する。

### Step 2: `composition.py` を作成

`app.py` の `_build_services`（現 397〜417 行）と `_build_postgres_services`（現 420〜480 行）を移動し、
**public 名** `build_services` / `build_postgres_services` に改名する。
関数内の遅延 import（`from plk_memory.postgres...`）は遅延のまま保持する（postgres 依存を
Git モードで読み込まない意図があるため）。
モジュール docstring は「storage_backend に応じたバックエンド合成（composition root）」の趣旨。
戻り値の型注釈 `"AppServices | PostgresAppServices"` は `git_services.AppServices` を参照するよう更新。

### Step 3: `facade.py` を作成

```python
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
```

注意: `ServiceFacade` は TYPE_CHECKING 内でのみ定義されるため、利用側も
`if TYPE_CHECKING: from plk_memory.facade import ServiceFacade` の形で import する。

### Step 4: `mcp_tools.py` / `webui.py` の重複定義を置き換え

両ファイルの TYPE_CHECKING ブロック内にある
`ServiceFacade = AppServices | PostgresAppServices` のローカル定義を削除し、
`from plk_memory.facade import ServiceFacade` に置き換える。
既存の `AppServices` / `PostgresAppServices` の import が他で未使用になる場合は削除する。

### Step 5: `app.py` を整理

- `AppServices` の定義・`_build_services`・`_build_postgres_services` を削除
- 後方互換の再エクスポートを追加（scripts/eval/measure_ingest.py が
  `from plk_memory.app import AppServices, _build_services` に依存）:

```python
from plk_memory.composition import build_services as _build_services
from plk_memory.git_services import AppServices as AppServices
```

- `create_app` 内の `_build_services(...)` 呼び出しは `build_services` 直接参照でも
  `_build_services` エイリアス経由でもよいが、composition からの import に統一する
- モジュール docstring を「FastAPI + FastMCP の ASGI 結線のみを担う」趣旨に更新
- `create_app` / `create_prod_app` / lifespan / middleware / route 定義（現 483〜661 行）は
  ロジックを一切変えずに残す
- 不要になった import を削除する（ruff が検出する）

### Step 6: 検証

```bash
uv run ruff check .
uv run pyright
uv run pytest -q
```

Expected: エラーゼロ / 160 passed, 16 deselected（ベースラインと同一）

### Step 7: コミット

```bash
git add -A src/plk_memory/
git commit -m "refactor: split app.py into git_services / composition / facade"
```

## 完了報告に含めること

- 各新規モジュールの行数と app.py の残り行数
- 再エクスポートの互換確認（`uv run python -c "from plk_memory.app import AppServices, _build_services, create_app"` の結果）
- 判断に迷って現状維持にした箇所（あれば）
