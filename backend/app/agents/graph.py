"""
JobGuard LangGraph 工作流

将多个 Agent 编排成有状态的工作流图：
- Orchestrator（意图识别）→ ProfileAgent / JobParser → BackgroundCheck → ResumeGenerator
- 支持条件分支、错误恢复、并行执行
"""

import json
import logging
from typing import Optional

from langgraph.graph import StateGraph, END
from app.agents.state import JobGuardState
from app.agents.orchestrator import detect_intent
from app.agents.profile_agent import profile_agent
from app.agents.job_parser import job_parser
from app.agents.background_check import background_check
from app.agents.resume_generator import resume_generator
from app.agents.job_matcher import job_matcher

logger = logging.getLogger(__name__)


# ─── 节点函数 ─────────────────────────────────────────────────

async def node_detect_intent(state: JobGuardState) -> JobGuardState:
    """节点：意图识别"""
    messages = state.get("messages", [])
    if not messages:
        return {**state, "intent": "build_profile", "current_stage": "profile_agent"}

    last_msg = messages[-1]
    content = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)

    intent = await detect_intent(content)
    stage_map = {
        "build_profile": "profile_agent",
        "analyze_job": "job_parser",
        "generate_resume": "resume_generator",
        "recommend_jobs": "job_matcher",
    }

    logger.info(f"[Graph] Intent: {intent} → Stage: {stage_map.get(intent, 'profile_agent')}")
    return {
        **state,
        "intent": intent,
        "current_stage": stage_map.get(intent, "profile_agent"),
        "error": None,
    }


async def node_profile_agent(state: JobGuardState) -> JobGuardState:
    """节点：用户画像构建"""
    logger.info("[Graph] Running ProfileAgent")
    try:
        # 获取用户消息
        messages = state.get("messages", [])
        if not messages:
            return {**state, "current_stage": "done"}

        last_msg = messages[-1]
        content = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)

        # 尝试从消息中提取画像更新
        recent_msgs = [{"role": "user", "content": content}]
        existing = state.get("user_profile") or {}

        updates = await profile_agent.extract_updates(recent_msgs, existing)
        if updates:
            merged = {**existing, **updates}
            logger.info(f"[Graph] Profile updated: {list(updates.keys())}")
            return {**state, "user_profile": merged, "current_stage": "done"}

        return {**state, "current_stage": "done"}

    except Exception as e:
        logger.error(f"[Graph] ProfileAgent error: {e}")
        return {**state, "error": str(e), "current_stage": "done"}


async def node_job_parser(state: JobGuardState) -> JobGuardState:
    """节点：岗位解析"""
    logger.info("[Graph] Running JobParser")
    try:
        messages = state.get("messages", [])
        if not messages:
            return {**state, "error": "No message to parse", "current_stage": "done"}

        last_msg = messages[-1]
        content = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)

        job_info = await job_parser.parse(content)
        if "error" in job_info:
            return {**state, "error": job_info["error"], "current_stage": "done"}

        logger.info(f"[Graph] Job parsed: {job_info.get('company_name')} - {job_info.get('job_title')}")
        return {
            **state,
            "job_info": job_info,
            "job_raw_input": content,
            "current_stage": "background_check",
        }

    except Exception as e:
        logger.error(f"[Graph] JobParser error: {e}")
        return {**state, "error": str(e), "current_stage": "done"}


async def node_background_check(state: JobGuardState) -> JobGuardState:
    """节点：企业背调（使用真实 WebSearch）"""
    logger.info("[Graph] Running BackgroundCheck")
    try:
        job_info = state.get("job_info", {})
        user_profile = state.get("user_profile")

        report = await background_check.investigate(
            job_info=job_info,
            user_profile=user_profile,
        )

        logger.info(f"[Graph] Background check done: risk={report.get('risk_level')}")
        return {
            **state,
            "company_report": report,
            "current_stage": "done",
        }

    except Exception as e:
        logger.error(f"[Graph] BackgroundCheck error: {e}")
        return {**state, "error": str(e), "current_stage": "done"}


async def node_resume_generator(state: JobGuardState) -> JobGuardState:
    """节点：简历生成"""
    logger.info("[Graph] Running ResumeGenerator")
    try:
        user_profile = state.get("user_profile", {})
        job_info = state.get("job_info", {})

        if not job_info:
            return {**state, "error": "No job info for resume generation", "current_stage": "done"}

        result = await resume_generator.generate(
            user_profile=user_profile,
            job_info=job_info,
            max_projects=3,
        )

        if "error" in result:
            return {**state, "error": result["error"], "current_stage": "done"}

        logger.info(f"[Graph] Resume generated, projects: {len(result.get('selected_projects', []))}")
        return {
            **state,
            "generated_resume": result.get("resume_markdown"),
            "generated_greeting": result.get("greeting"),
            "current_stage": "done",
        }

    except Exception as e:
        logger.error(f"[Graph] ResumeGenerator error: {e}")
        return {**state, "error": str(e), "current_stage": "done"}


async def node_job_matcher(state: JobGuardState) -> JobGuardState:
    """节点：岗位匹配推荐"""
    logger.info("[Graph] Running JobMatcher")
    try:
        user_profile = state.get("user_profile", {})
        # Job matcher needs external job list — handled by API layer
        return {**state, "current_stage": "done"}

    except Exception as e:
        logger.error(f"[Graph] JobMatcher error: {e}")
        return {**state, "error": str(e), "current_stage": "done"}


# ─── 路由函数 ─────────────────────────────────────────────────

def route_after_intent(state: JobGuardState) -> str:
    """根据意图路由到下一个节点"""
    intent = state.get("intent", "build_profile")
    route_map = {
        "build_profile": "profile_agent",
        "analyze_job": "job_parser",
        "generate_resume": "resume_generator",
        "recommend_jobs": "job_matcher",
    }
    return route_map.get(intent, "profile_agent")


def route_after_job_parser(state: JobGuardState) -> str:
    """岗位解析后：如果成功则进入背调，否则结束"""
    if state.get("error"):
        return END
    return "background_check"


# ─── 构建图 ───────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """构建 JobGuard LangGraph 工作流"""
    workflow = StateGraph(JobGuardState)

    # 添加节点
    workflow.add_node("detect_intent", node_detect_intent)
    workflow.add_node("profile_agent", node_profile_agent)
    workflow.add_node("job_parser", node_job_parser)
    workflow.add_node("background_check", node_background_check)
    workflow.add_node("resume_generator", node_resume_generator)
    workflow.add_node("job_matcher", node_job_matcher)

    # 设置入口
    workflow.set_entry_point("detect_intent")

    # 意图 → 路由到对应 Agent
    workflow.add_conditional_edges(
        "detect_intent",
        route_after_intent,
        {
            "profile_agent": "profile_agent",
            "job_parser": "job_parser",
            "resume_generator": "resume_generator",
            "job_matcher": "job_matcher",
        }
    )

    # 岗位解析 → 背调（条件）
    workflow.add_conditional_edges(
        "job_parser",
        route_after_job_parser,
        {
            "background_check": "background_check",
            END: END,
        }
    )

    # 叶子节点 → 结束
    workflow.add_edge("profile_agent", END)
    workflow.add_edge("background_check", END)
    workflow.add_edge("resume_generator", END)
    workflow.add_edge("job_matcher", END)

    return workflow


# ─── 全局编译图 ───────────────────────────────────────────────

_jobguard_graph = None


def get_graph():
    """获取编译后的工作流图（懒加载单例）"""
    global _jobguard_graph
    if _jobguard_graph is None:
        _jobguard_graph = build_graph().compile()
        logger.info("[Graph] JobGuard LangGraph compiled successfully")
    return _jobguard_graph


# ─── 便捷运行函数 ─────────────────────────────────────────────

async def run_graph(user_message: str, user_profile: Optional[dict] = None) -> dict:
    """
    运行 LangGraph 工作流

    Args:
        user_message: 用户消息
        user_profile: 可选的已有用户画像

    Returns:
        最终状态 dict
    """
    graph = get_graph()

    initial_state: JobGuardState = {
        "messages": [{"role": "user", "content": user_message}],
        "user_id": "default",
        "session_id": "default",
        "intent": "",
        "current_stage": "",
        "user_profile": user_profile,
        "user_projects": None,
        "job_raw_input": None,
        "job_info": None,
        "company_report": None,
        "match_score": None,
        "generated_resume": None,
        "generated_greeting": None,
        "recommended_jobs": None,
        "error": None,
        "retry_count": 0,
    }

    result = await graph.ainvoke(initial_state)
    logger.info(f"[Graph] Workflow completed. Stage: {result.get('current_stage')}, Error: {result.get('error')}")
    return result
