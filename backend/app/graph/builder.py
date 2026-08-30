"""唯一的生产 LangGraph：负责聊天请求的真实意图分类。

具体画像、岗位、简历服务由 API 层显式调用并承担数据库事务。这里不再
声明没有实现体的“Agent 节点”，避免图结构与真实执行链不一致。
"""

import logging
from typing import Optional

from langgraph.graph import END, StateGraph

from app.agents.orchestrator import detect_intent
from app.agents.state import JobGuardState

logger = logging.getLogger(__name__)


async def classify_intent_node(state: JobGuardState) -> dict:
    """调用真实意图识别器，并在结果中留下可测试的图执行轨迹。"""
    messages = state.get("messages", [])
    if not messages:
        content = ""
    else:
        last_message = messages[-1]
        content = last_message.content if hasattr(last_message, "content") else str(last_message.get("content", ""))

    intent = await detect_intent(content, state.get("session_type"))
    logger.info("[ProductionGraph] classify_intent -> %s", intent)
    return {
        "intent": intent,
        "current_stage": "intent_classified",
        "graph_trace": ["classify_intent"],
    }


async def build_execution_plan_node(state: JobGuardState) -> dict:
    """为当前意图生成确定性的业务步骤，避免模型自行越权或跳步。"""
    state_owners = {
        "intent": "router",
        "execution_plan": "router",
        "evidence_policy": "evidence_gate",
        "user_profile": "profile_service",
        "user_projects": "profile_service",
        "job_info": "job_service",
        "retrieval_results": "job_retrieval",
        "recommended_jobs": "job_recommendation",
        "recommendation_breakdown": "job_recommendation",
        "company_report": "background_check",
        "match_score": "job_service",
        "generated_resume": "resume_service",
        "generated_greeting": "resume_service",
    }
    plans = {
        "build_profile": [
            {"step": "extract_profile_evidence", "executor": "profile_service"},
            {"step": "confirm_high_impact_constraints", "executor": "human"},
            {"step": "persist_profile", "executor": "profile_service"},
            {"step": "ask_next_deep_question", "executor": "profile_agent"},
        ],
        "analyze_job": [
            {"step": "parse_job_input", "executor": "job_service"},
            {"step": "search_company_evidence", "executor": "search_company_info"},
            {"step": "evaluate_match_and_risk", "executor": "job_service"},
        ],
        "recommend_jobs": [
            {"step": "load_profile", "executor": "profile_service"},
            {"step": "rule_recall", "executor": "job_service", "writes": ["retrieval_results.rule"]},
            {"step": "keyword_recall", "executor": "job_service", "writes": ["retrieval_results.keyword"]},
            {"step": "semantic_recall", "executor": "job_service", "writes": ["retrieval_results.semantic"]},
            {"step": "fuse_and_rank", "executor": "job_service", "writes": ["recommended_jobs", "recommendation_breakdown"]},
        ],
        "generate_resume": [
            {"step": "load_grounded_profile", "executor": "profile_service"},
            {"step": "load_target_job", "executor": "job_service"},
            {"step": "confirm_write_action", "executor": "human"},
            {"step": "generate_and_fact_check", "executor": "resume_service"},
        ],
        "career_advice": [
            {"step": "load_profile_gaps", "executor": "inspect_profile_gaps"},
            {"step": "select_verified_resources", "executor": "recommend_learning_resources"},
            {"step": "compose_action_plan", "executor": "career_advisor"},
        ],
    }
    intent = state.get("intent", "build_profile")
    return {
        "execution_plan": plans.get(intent, plans["build_profile"]),
        "state_owners": state_owners,
        "current_stage": "execution_planned",
        "graph_trace": [*state.get("graph_trace", []), "build_execution_plan"],
    }


async def apply_evidence_gate_node(state: JobGuardState) -> dict:
    """声明流程可使用的证据和人工确认边界，供 API 执行层强制遵循。"""
    intent = state.get("intent", "build_profile")
    policy = {
        "require_source_links": intent == "analyze_job",
        "allow_unverified_numbers": False,
        "require_human_confirmation": intent == "generate_resume",
        "persist_only_confirmed_constraints": intent == "build_profile",
        "on_missing_evidence": "mark_unknown_and_return_verification_steps",
    }
    return {
        "evidence_policy": policy,
        "current_stage": "evidence_gate_ready",
        "graph_trace": [*state.get("graph_trace", []), "apply_evidence_gate"],
    }


def build_jobguard_graph() -> StateGraph:
    """构建意图、计划和证据门禁均会真实执行的确定性主链。"""
    workflow = StateGraph(JobGuardState)
    workflow.add_node("classify_intent", classify_intent_node)
    workflow.add_node("build_execution_plan", build_execution_plan_node)
    workflow.add_node("apply_evidence_gate", apply_evidence_gate_node)
    workflow.set_entry_point("classify_intent")
    workflow.add_edge("classify_intent", "build_execution_plan")
    workflow.add_edge("build_execution_plan", "apply_evidence_gate")
    workflow.add_edge("apply_evidence_gate", END)
    return workflow


_compiled_graph = None


def get_jobguard_graph():
    """懒加载编译，避免模块导入时重复构图。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_jobguard_graph().compile()
        logger.info("[ProductionGraph] compiled")
    return _compiled_graph


async def classify_message(
    content: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    session_type: Optional[str] = None,
) -> dict:
    """让聊天请求经过生产图并返回意图与执行轨迹。"""
    result = await get_jobguard_graph().ainvoke({
        "messages": [{"role": "user", "content": content}],
        "user_id": user_id or "",
        "session_id": session_id or "",
        "session_type": session_type or "general",
        "intent": "",
        "current_stage": "received",
        "graph_trace": [],
        "execution_plan": [],
        "evidence_policy": {},
    })
    return {
        "intent": result.get("intent", "build_profile"),
        "current_stage": result.get("current_stage"),
        "graph_trace": result.get("graph_trace", []),
        "execution_plan": result.get("execution_plan", []),
        "evidence_policy": result.get("evidence_policy", {}),
        "state_owners": result.get("state_owners", {}),
    }


# 兼容原有导入名，但不在模块加载时立即编译。
def compile_graph():
    return get_jobguard_graph()
