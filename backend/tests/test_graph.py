"""生产 LangGraph 调用链测试。"""

import pytest

from app.graph import builder


def test_production_graph_has_real_planning_and_evidence_nodes():
    graph = builder.build_jobguard_graph().compile()
    nodes = graph.get_graph().nodes
    node_names = {name for name in nodes if name not in {"__start__", "__end__"}}

    assert node_names == {"classify_intent", "build_execution_plan", "apply_evidence_gate"}


@pytest.mark.asyncio
async def test_classify_message_runs_through_graph(monkeypatch):
    async def fake_detect_intent(content, session_type=None):
        assert content == "请推荐适合我的岗位"
        assert session_type == "profile_building"
        return "recommend_jobs"

    monkeypatch.setattr(builder, "detect_intent", fake_detect_intent)
    monkeypatch.setattr(builder, "_compiled_graph", None)

    result = await builder.classify_message(
        "请推荐适合我的岗位",
        user_id="8",
        session_id="16",
        session_type="profile_building",
    )

    assert result["intent"] == "recommend_jobs"
    assert result["current_stage"] == "evidence_gate_ready"
    assert result["graph_trace"] == [
        "classify_intent", "build_execution_plan", "apply_evidence_gate"
    ]
    assert result["execution_plan"][1]["executor"] == "search_job_database"
    assert result["evidence_policy"]["allow_unverified_numbers"] is False


def test_old_graph_import_path_reuses_production_builder():
    from app.agents.graph import build_graph

    graph = build_graph().compile()
    nodes = graph.get_graph().nodes
    assert "classify_intent" in nodes
    assert "profile_agent" not in nodes


@pytest.mark.asyncio
async def test_profile_building_context_keeps_resume_evidence_in_profile_flow():
    result = await builder.classify_message(
        "简历里没写的是，我做过一个 RAG 项目，主要负责检索流程",
        session_type="profile_building",
    )

    assert result["intent"] == "build_profile"


@pytest.mark.asyncio
async def test_profile_building_context_can_answer_user_question():
    result = await builder.classify_message(
        "Agent 应用研发这个方向未来前景怎么样？",
        session_type="profile_building",
    )

    assert result["intent"] == "career_advice"
