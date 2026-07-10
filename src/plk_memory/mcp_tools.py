"""FastMCP ツール定義（組織展開 互換サーフェス）。

各ツールは薄いラッパで、実体は `AppServices` のメソッド（`tool_search` など）に
持たせてある（テスト容易性と MCP 結線の分離 — Task 9 brief）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from plk_memory.app import AppServices


PLK_SEARCH_DESCRIPTION = """Search PLK facts before making decisions about tax,
social insurance, legal, accounting, company know-how, or prior decisions. Use
reason="auto-guideline" when this call is required by repo/agent instructions.
By default this searches active facts and excludes plk.quarantine /
external-untrusted facts unless that namespace is explicitly requested. If the
result has degraded=true, treat it as an index failure and answer with caveats or
fallback evidence."""

PLK_ADD_DESCRIPTION = """Add a candidate only after it passes the PLK admission
rubric: it has durable value across future sessions (or records a reasoned
organizational decision), is verified rather than speculative (except information
intentionally isolated as external-untrusted in plk.quarantine), does not copy a
volatile value, raw data, or whole-source summary from an existing source of truth,
is not limited to one customer/session, fits philosophy (unconditional norm), logic (conditional norm),
or knowhow (verifiable fact/procedure), and is one independently invalidatable
claim. Do not call this tool for transient dates/prices/status, conversation or work
summaries or single-customer reactions. Stable facts/procedures from official docs,
code, or runbooks may be distilled as minimal knowhow when they have cross-session
retrieval value and point to the source; do not copy the source itself. Before asking
the user for approval, normalize the candidate and use
plk_search to check duplicates and updates. Do not ask a generic "save to PLK?"
question: show the proposed statement, kind, namespace, and whether it is new or an
update. Choose an existing namespace from plk.domain.tax/legal/shaho/dev/backoffice/
biz/agent (or plk.quarantine for external-untrusted data); never invent one. When an
observed result motivates a future behavior, store the conditional behavior as
logic and put the observation in why/source; create a separate knowhow fact only if
the observation itself has durable retrieval value. For an update preview the old
fact id and statement that supersedes will invalidate. Philosophy candidates must
use human PR direct editing; this API rejects kind="philosophy". Normal API callers should omit
source_type or set source_type="agent".
Do not set source_type="user" through the API; user is only for human PR direct
edits. Do not use source_type="conversation"; valid values are "agent" and
"external-untrusted" for API callers. Use external-untrusted only with
namespace="plk.quarantine". source must be a URL, Notion ID, or Codex/session ID.
When replacing an old fact, pass supersedes=[old_fact_id] so the old fact is
invalidated atomically."""

PLK_INVALIDATE_DESCRIPTION = """Invalidate an active PLK fact by id when it is
obsolete, wrong, or no longer applicable. This records the reason and removes the
fact from active search/graph results; it does not physically delete history.
Provide a specific reason. If you are replacing a fact, prefer plk_add with
supersedes=[old_fact_id]."""

PLK_HISTORY_DESCRIPTION = """Read git/frontmatter history for a PLK fact id.
Use this to understand changes, supersession, and invalidation before relying on
or updating an old fact."""

PLK_STATUS_DESCRIPTION = """Check PLK service and index status: freshness,
degraded/maintenance state, unpushed commits, indexed counts, dead letters, and
pending promotion requests. Use after writes if search does not reflect the
change yet."""

PLK_PROPOSE_PROMOTION_DESCRIPTION = """Propose a stable plk.domain.* fact for
promotion into shared knowledge. This creates a PromotionRequest / GitHub PR; it
is not a direct write to plk.shared. Use only when the fact is broadly useful and
the user has approved the external write. Requires the data repo to have no
unpushed commits."""


def build_mcp(services: "AppServices") -> FastMCP:
    auth = None
    if services.settings.auth_mode == "jwt":
        from plk_memory.auth import build_jwt_verifier
        auth = build_jwt_verifier(services.settings)
    mcp = FastMCP("plk-memory", auth=auth)

    @mcp.tool(description=PLK_SEARCH_DESCRIPTION)
    async def plk_search(
        query: str,
        namespaces: list[str] | None = None,
        kind: str | None = None,
        status: str = "active",
        limit: int = 10,
        reason: str | None = None,
    ) -> dict:
        return await services.tool_search(
            query=query, namespaces=namespaces, kind=kind, status=status,
            limit=limit, reason=reason,
        )

    @mcp.tool(description=PLK_ADD_DESCRIPTION)
    async def plk_add(
        namespace: str,
        kind: str,
        statement: str,
        why: str,
        how_to_apply: str,
        source: str,
        tags: list[str] | None = None,
        body: str = "",
        slug: str | None = None,
        source_type: str = "agent",
        supersedes: list[str] | None = None,
        idempotency_key: str | None = None,
        expected_revision: int | None = None,
        expected_superseded_revisions: dict[str, int] | None = None,
    ) -> dict:
        return await services.tool_add(
            namespace=namespace, kind=kind, statement=statement, why=why,
            how_to_apply=how_to_apply, source=source, tags=tags, body=body,
            slug=slug, source_type=source_type, supersedes=supersedes,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            expected_superseded_revisions=expected_superseded_revisions,
        )

    @mcp.tool(description=PLK_INVALIDATE_DESCRIPTION)
    async def plk_invalidate(
        fact_id: str,
        reason: str,
        idempotency_key: str | None = None,
        expected_revision: int | None = None,
    ) -> dict:
        return await services.tool_invalidate(
            fact_id,
            reason,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        )

    @mcp.tool(description=PLK_HISTORY_DESCRIPTION)
    async def plk_history(fact_id: str) -> dict:
        return await services.tool_history(fact_id)

    @mcp.tool(description=PLK_STATUS_DESCRIPTION)
    async def plk_status() -> dict:
        return await services.tool_status()

    @mcp.tool(description=PLK_PROPOSE_PROMOTION_DESCRIPTION)
    async def plk_propose_promotion(fact_id: str, reason: str | None = None) -> dict:
        return await services.tool_propose_promotion(fact_id, reason)

    return mcp
