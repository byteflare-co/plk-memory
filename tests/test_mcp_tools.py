from types import SimpleNamespace
from typing import Any, cast

from fastmcp import Client

from plk_memory.admission import AdmissionAssessment
from plk_memory.mcp_tools import build_mcp


class DummyServices:
    settings = SimpleNamespace(auth_mode="none")


class FakeAdmission:
    async def assess(self, *, candidate: str, context: str = "") -> AdmissionAssessment:
        assert candidate == "候補ファクト"
        assert context == "検証済み"
        return AdmissionAssessment(
            decision="ineligible",
            reason="既存SoTの複製",
            failed_gates=["sot_duplication"],
            recommended_destination="existing_sot",
            write_performed=False,
            requires_user_approval=True,
        )


class AssessServices(DummyServices):
    admission = FakeAdmission()

    async def tool_search(self, **_kwargs):
        raise AssertionError("ineligible candidate must not search")


async def test_plk_tools_have_agent_facing_descriptions():
    mcp = build_mcp(cast(Any, DummyServices()))

    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert set(tools) == {
        "plk_add",
        "plk_assess_candidate",
        "plk_decide_promotion",
        "plk_history",
        "plk_invalidate",
        "plk_propose_promotion",
        "plk_search",
        "plk_status",
    }
    assert all(tool.description for tool in tools.values())


async def test_plk_assess_description_preserves_read_only_approval_boundary():
    mcp = build_mcp(cast(Any, DummyServices()))

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    description = " ".join((tools["plk_assess_candidate"].description or "").split())

    assert "Read-only" in description
    assert "needs_evidence" in description
    assert "possible duplicates" in description
    assert "explicit user approval" in description
    assert len(description) < 300


async def test_plk_assess_tool_invokes_assessor_without_write_or_search():
    mcp = build_mcp(cast(Any, AssessServices()))

    async with Client(mcp) as client:
        result = await client.call_tool(
            "plk_assess_candidate",
            {"candidate": "候補ファクト", "context": "検証済み"},
        )

    assert result.structured_content is not None
    assert result.structured_content["decision"] == "ineligible"
    assert result.structured_content["write_performed"] is False
    assert result.structured_content["duplicate_check"] == {
        "status": "not_run",
        "hits": [],
    }


async def test_plk_add_description_explains_source_type_constraints():
    mcp = build_mcp(cast(Any, DummyServices()))

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    description = tools["plk_add"].description or ""

    assert "Philosophy requires a human PR" in description
    assert "external-untrusted requires plk.quarantine" in description
    assert "supersedes=[old_fact_id]" in description
    assert len(" ".join(description.split())) < 400


async def test_plk_add_description_requires_assessment_before_write():
    mcp = build_mcp(cast(Any, DummyServices()))

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    description = " ".join((tools["plk_add"].description or "").split())

    assert "after plk_assess_candidate returns eligible" in description
    assert "Never call for ineligible or needs_evidence" in description
    assert "duplicates are reviewed" in description
    assert "user explicitly approves" in description


async def test_plk_add_description_delegates_semantic_judgment_to_assessor():
    mcp = build_mcp(cast(Any, DummyServices()))

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    description = tools["plk_add"].description or ""
    normalized = " ".join(description.split())

    assert "plk_assess_candidate returns eligible" in normalized
    assert "explicitly approves" in normalized
    assert len(normalized) < 400
