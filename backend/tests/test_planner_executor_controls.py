import asyncio

import pytest

from app.agents.planner import Executor, PlanStep
from app.agents.tool_registry import Tool, ToolRegistry


def _registry_with_tool(func):
    registry = ToolRegistry()
    registry._tools = {}
    registry.register(Tool(
        name="demo_tool",
        description="demo",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        func=func,
    ))
    return registry


@pytest.mark.asyncio
async def test_executor_truncates_plan_by_max_steps():
    async def demo_tool(value: str):
        return {"status": "success", "value": value}

    plan = [
        PlanStep(step_id=1, tool_name="demo_tool", tool_args={"value": "a"}, description="a"),
        PlanStep(step_id=2, tool_name="demo_tool", tool_args={"value": "b"}, description="b"),
    ]

    result = await Executor(registry=_registry_with_tool(demo_tool), max_steps=1).execute(plan)

    assert len(result) == 1
    assert result[0].status == "completed"
    assert result[0].result["value"] == "a"


@pytest.mark.asyncio
async def test_executor_marks_tool_timeout_as_failed():
    async def slow_tool(value: str):
        await asyncio.sleep(0.05)
        return {"status": "success", "value": value}

    plan = [PlanStep(step_id=1, tool_name="demo_tool", tool_args={"value": "a"}, description="a")]

    result = await Executor(
        registry=_registry_with_tool(slow_tool),
        tool_timeout_seconds=0.001,
    ).execute(plan)

    assert result[0].status == "failed"
    assert "TimeoutError" in result[0].error or result[0].error == ""
