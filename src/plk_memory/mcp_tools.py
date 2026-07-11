"""FastMCP ツール定義（組織展開 互換サーフェス）。

各ツールは薄いラッパで、実体は `AppServices` のメソッド（`tool_search` など）に
持たせてある（テスト容易性と MCP 結線の分離 — Task 9 brief）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from plk_memory.app import AppServices
    from plk_memory.postgres.application import PostgresAppServices

    ServiceFacade = AppServices | PostgresAppServices

PLK_SEARCH_DESCRIPTION = """Search PLK facts before making decisions about tax,
social insurance, legal, accounting, company know-how, or prior decisions. Use
reason="auto-guideline" when this call is required by repo/agent instructions.
By default this searches active facts and excludes plk.quarantine /
external-untrusted facts unless that namespace is explicitly requested. If the
result has degraded=true, treat it as an index failure and answer with caveats or
fallback evidence."""

PLK_ADD_DESCRIPTION = """Add a candidate only after it passes the PLK admission
rubric. The top-level gate is counterfactual usefulness: name the future situation
in which retrieving this fact changes a decision or action, and how it changes it.
If that cannot be stated concretely, do not propose or add it. A past organizational
decision is not exempt merely because it was important; architecture state, ADRs,
task history, and implementation choices belong in their existing source of truth
unless their rationale will change a likely future decision. The candidate must
have durable value across future sessions, be verified rather than speculative (except information
intentionally isolated as external-untrusted in plk.quarantine), does not copy a
volatile value, raw data, or whole-source summary from an existing source of truth,
is not limited to one customer/session, fits philosophy (unconditional norm), logic (conditional norm),
or knowhow (verifiable fact/procedure), and is one independently invalidatable
claim. Do not call this tool for transient dates/prices/status, conversation or work
summaries, single-customer reactions, current architecture/configuration that code
or design docs already describe, or decisions with no concrete future application.
Stable facts/procedures from official docs, code, or runbooks may be distilled as
minimal knowhow only when retrieving them changes a future decision or action and
they point to the source; do not copy the source itself. Before asking
the user for approval, normalize the candidate and use
plk_search to check duplicates and updates. Do not ask a generic "save to PLK?"
question: show the proposed statement, kind, namespace, whether it is new or an
update, the future retrieval situation, and the decision or action that changes
compared with not retrieving it. Choose an existing namespace from plk.domain.tax/legal/shaho/dev/backoffice/
biz/agent (or plk.quarantine for external-untrusted data); never invent one. When an
observed result motivates a future behavior, store the conditional behavior as
logic and put the observation in why/source; create a separate knowhow fact only if
the observation itself has durable retrieval value. For an update preview the old
fact id and statement that supersedes will invalidate. Philosophy candidates must
be proposed for human PR direct editing, not sent to plk_add by an ordinary agent.
The backend may expose protected administrative write roles, but they do not change
this agent proposal workflow. Normal agent callers should omit
source_type or set source_type="agent". Do not use source_type="conversation";
ordinary agent credentials may use "agent" and
"external-untrusted" for API callers. Use external-untrusted only with
namespace="plk.quarantine". source must be a URL, Notion ID, or Codex/session ID.
When replacing an old fact, pass supersedes=[old_fact_id] so the old fact is
invalidated atomically."""

PLK_INVALIDATE_DESCRIPTION = """Invalidate an active PLK fact by id when it is
obsolete, wrong, or no longer applicable. This records the reason and removes the
fact from active search/graph results; it does not physically delete history.
Provide a specific reason. If you are replacing a fact, prefer plk_add with
supersedes=[old_fact_id]."""

PLK_HISTORY_DESCRIPTION = """Read immutable revision history for a PLK fact id.
Use this to understand changes, supersession, and invalidation before relying on
or updating an old fact."""

PLK_STATUS_DESCRIPTION = """Check PLK service and index status: freshness,
degraded/maintenance state, unpushed commits, indexed counts, dead letters, and
pending promotion requests. Use after writes if search does not reflect the
change yet."""

PLK_PROPOSE_PROMOTION_DESCRIPTION = """Propose a stable plk.domain.* fact for
promotion into shared knowledge. This creates a reviewable PromotionRequest, not
a direct write to plk.shared. Depending on the configured backend, review occurs
through a GitHub PR or a revision-pinned database approval. Use only when the fact
is broadly useful and the user has approved any external write."""

PLK_DECIDE_PROMOTION_DESCRIPTION = """Approve or reject a revision-pinned
PostgreSQL promotion request. Requires reviewer/admin role. Approval creates a
new immutable fact revision in plk.shared; if the fact changed after proposal,
the request becomes stale instead of promoting unseen content."""


def build_mcp(services: "ServiceFacade") -> FastMCP:
    """Build the transport surface around either storage backend's service facade.

    The Git and PostgreSQL facades intentionally share a duck-typed tool surface;
    the concrete backend is selected at the composition root.
    """
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
    async def plk_propose_promotion(
        fact_id: str,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        return await services.tool_propose_promotion(
            fact_id, reason, idempotency_key=idempotency_key
        )

    @mcp.tool(description=PLK_DECIDE_PROMOTION_DESCRIPTION)
    async def plk_decide_promotion(
        request_id: str,
        decision: str,
        rationale: str,
        expected_revision: int,
        idempotency_key: str | None = None,
    ) -> dict:
        return await services.tool_decide_promotion(
            request_id,
            decision,
            rationale,
            expected_revision,
            idempotency_key=idempotency_key,
        )

    return mcp
