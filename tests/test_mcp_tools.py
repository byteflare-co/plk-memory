from types import SimpleNamespace

from plk_memory.mcp_tools import build_mcp


class DummyServices:
    settings = SimpleNamespace(auth_mode="none")


async def test_plk_tools_have_agent_facing_descriptions():
    mcp = build_mcp(DummyServices())

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
    mcp = build_mcp(DummyServices())

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    description = tools["plk_add"].description or ""

    assert 'source_type="agent"' in description
    assert 'source_type="user"' in description
    assert 'source_type="conversation"' in description
    assert 'namespace="plk.quarantine"' in description
    assert "supersedes=[old_fact_id]" in description


async def test_plk_add_description_explains_semantic_admission_rubric():
    mcp = build_mcp(DummyServices())

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    description = tools["plk_add"].description or ""
    normalized = " ".join(description.split())

    assert "future sessions" in normalized
    assert "source of truth" in normalized
    assert "Stable facts/procedures" in normalized
    assert "plk.quarantine" in normalized
    assert "one independently invalidatable claim" in normalized
    assert "single-customer reactions" in normalized
    assert 'generic "save to PLK?"' in normalized
    assert "statement, kind, namespace" in normalized
    assert "never invent one" in normalized
    assert "conditional behavior as" in normalized
    assert "old fact id and statement" in normalized
    assert 'rejects kind="philosophy"' in normalized
