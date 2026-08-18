"""MCP server contract tests."""

import pytest

from app.mcp_server import get_jobguard_tool_status, jobguard_mcp


@pytest.mark.asyncio
async def test_mcp_server_exposes_real_company_tool():
    tools = await jobguard_mcp.list_tools()
    names = {tool.name for tool in tools}
    assert "search_company_info" in names
    assert "get_jobguard_tool_status" in names
    assert {
        "search_job_database",
        "analyze_job_requirements",
        "recommend_learning_resources",
        "build_company_verification_plan",
    }.issubset(names)


@pytest.mark.asyncio
async def test_mcp_status_is_transparent_about_manual_gsxt():
    status = await get_jobguard_tool_status()
    assert status["status"] == "ready"
    assert status["adapters"]["gsxt"] == "manual_handoff"
    assert "unknown" in status["policy"]
