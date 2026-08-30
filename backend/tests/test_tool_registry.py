import pytest

from app.agents.tool_registry import tool_registry


def test_every_exposed_tool_has_real_callable_and_safety_metadata():
    tools = tool_registry.list_available()

    assert len(tools) >= 13
    assert all(callable(item.func) for item in tools)
    assert all(item.execution_mode in {"read_only", "write"} for item in tools)
    assert tool_registry.get("generate_targeted_resume").requires_confirmation is True
    assert tool_registry.get("save_user_memory").requires_confirmation is True
    assert tool_registry.get("sync_job_kb_from_database").requires_confirmation is True
    assert tool_registry.get("inspect_profile_gaps").expose_via_mcp is False
    assert tool_registry.get("search_job_knowledge_base").expose_via_mcp is True


@pytest.mark.asyncio
async def test_learning_resource_tool_returns_real_links():
    result = await tool_registry.execute(
        "recommend_learning_resources", {"topic": "LangGraph", "limit": 2}
    )

    assert result["status"] == "success"
    assert result["items"]
    assert all(item["url"].startswith("https://www.bilibili.com/video/") for item in result["items"])


@pytest.mark.asyncio
async def test_write_tool_stops_at_human_confirmation_gate(monkeypatch):
    tool = tool_registry.get("generate_targeted_resume")
    called = False

    async def should_not_run(**kwargs):
        nonlocal called
        called = True
        return {"status": "success"}

    monkeypatch.setattr(tool, "func", should_not_run)
    result = await tool_registry.execute(
        "generate_targeted_resume", {"job_id": 1}, user_id=7, confirmed=False
    )

    assert result["status"] == "confirmation_required"
    assert called is False


@pytest.mark.asyncio
async def test_tool_schema_rejects_unknown_arguments():
    with pytest.raises(ValueError, match="不支持的参数"):
        await tool_registry.execute(
            "recommend_learning_resources", {"topic": "RAG", "cookie": "secret"}
        )


@pytest.mark.asyncio
async def test_memory_write_tool_requires_confirmation(monkeypatch):
    tool = tool_registry.get("save_user_memory")
    called = False

    async def should_not_run(**kwargs):
        nonlocal called
        called = True
        return {"status": "success"}

    monkeypatch.setattr(tool, "func", should_not_run)
    result = await tool_registry.execute(
        "save_user_memory",
        {"memory_type": "preference", "content": "不接受 996"},
        user_id=7,
        confirmed=False,
    )

    assert result["status"] == "confirmation_required"
    assert called is False
