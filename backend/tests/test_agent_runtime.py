import pytest

from app.agents.runtime import agent_runtime
from app.graph.builder import classify_message


def test_agent_runtime_analyze_job_blueprint_contains_engineering_contract():
    context = {
        "user_id": 1,
        "job_text": "广州 AI Agent 工程师，要求 Python、RAG、LangGraph。",
        "company_name": "广州文基智能科技有限公司",
        "raw_resume_text": "这段原始简历不应该进入 Prompt",
    }

    blueprint = agent_runtime.describe("analyze_job", context)

    node_names = [item["name"] for item in blueprint["workflow"]]
    assert node_names[:3] == ["supervisor", "planner", "context_builder"]
    assert "evidence_agent" in node_names
    assert "evidence_gate" in node_names
    assert "raw_resume_text" in blueprint["context_engineering"]["omitted_keys"]
    assert blueprint["context_engineering"]["isolate"]["cross_user_access_allowed"] is False
    assert blueprint["prompt_assembly"]["evidence_policy"]["on_missing_evidence"] == "unknown/no_evidence"
    assert "query_real_company_registry" in blueprint["prompt_assembly"]["allowed_tools"]
    assert any(item["name"] == "ToolScopeMiddleware" for item in blueprint["middleware_chain"])


def test_agent_runtime_resume_prompt_guards_against_fabrication():
    prompt = agent_runtime.build_prompt(
        "generate_resume",
        {
            "user_id": 1,
            "target_job": {"title": "AI Agent 实习生"},
            "project_summaries": ["JobGuard 求职决策智能体"],
            "unrelated_history": "不应选择",
        },
    )

    assert "简历生成只能重组和改写已有经历" in "\n".join(prompt.system_rules)
    assert "unrelated_history" not in prompt.context_keys
    assert "generate_targeted_resume" in prompt.allowed_tools
    assert prompt.output_schema["required"] == [
        "resume_markdown",
        "selected_projects",
        "unsupported_claims",
    ]


@pytest.mark.asyncio
async def test_production_graph_returns_runtime_blueprint():
    result = await classify_message("请帮我分析这个岗位是否适合我", user_id="1")

    assert result["graph_trace"] == [
        "classify_intent",
        "build_execution_plan",
        "apply_evidence_gate",
    ]
    assert result["runtime_blueprint"]["runtime"] == "LangGraph + deterministic Agent Runtime"
    assert result["prompt_assembly"]["evidence_policy"]["allow_unverified_numbers"] is False
