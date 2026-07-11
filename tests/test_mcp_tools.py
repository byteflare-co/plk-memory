from types import SimpleNamespace
from typing import Any, cast

from plk_memory.mcp_tools import build_mcp


class DummyServices:
    settings = SimpleNamespace(auth_mode="none")


async def test_plk_tools_have_agent_facing_descriptions():
    mcp = build_mcp(cast(Any, DummyServices()))

    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert set(tools) == {
        "plk_add",
        "plk_decide_promotion",
        "plk_history",
        "plk_invalidate",
        "plk_propose_promotion",
        "plk_search",
        "plk_status",
    }
    assert all(tool.description for tool in tools.values())


async def test_plk_add_description_explains_source_type_constraints():
    mcp = build_mcp(cast(Any, DummyServices()))

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    description = tools["plk_add"].description or ""

    assert 'source_type="agent"' in description
    assert "human PR direct editing" in description
    assert "protected administrative write roles" in description
    assert 'source_type="conversation"' in description
    assert 'namespace="plk.quarantine"' in description
    assert "supersedes=[old_fact_id]" in description


async def test_plk_add_description_explains_semantic_admission_rubric():
    mcp = build_mcp(cast(Any, DummyServices()))

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    description = tools["plk_add"].description or ""
    normalized = " ".join(description.split())

    assert "future sessions" in normalized
    assert "counterfactual usefulness" in normalized
    assert "changes a decision or action" in normalized
    assert "organizational decision is not exempt" in normalized
    assert "current architecture/configuration" in normalized
    assert "decisions with no concrete future application" in normalized
    assert "source of truth" in normalized
    assert "Stable facts/procedures" in normalized
    assert "plk.quarantine" in normalized
    assert "one independently invalidatable claim" in normalized
    assert "single-customer reactions" in normalized
    assert 'generic "save to PLK?"' in normalized
    assert "statement, kind, namespace" in normalized
    assert "future retrieval situation" in normalized
    assert "decision or action that changes compared with not retrieving it" in normalized
    assert "never invent one" in normalized
    assert "conditional behavior as" in normalized
    assert "old fact id and statement" in normalized
    assert "Philosophy candidates must be proposed for human PR direct editing" in normalized
    assert "not sent to plk_add by an ordinary agent" in normalized
