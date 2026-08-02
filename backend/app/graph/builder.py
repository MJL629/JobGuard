"""
LangGraph Graph Builder

Assembles all Agents into a coordinated workflow with state management,
intent routing, and conditional branching.
"""

import logging
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.agents.state import JobGuardState
from app.agents.orchestrator import detect_intent

logger = logging.getLogger(__name__)


# ─── Node Functions ────────────────────────────────────────────────────

async def router_node(state: JobGuardState) -> dict:
    """Entry point: detect intent and route"""
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "build_profile", "current_stage": "init"}

    last_msg = messages[-1]
    user_message = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    intent = await detect_intent(user_message)
    logger.info(f"[Graph] Router: intent={intent}")

    return {
        "intent": intent,
        "current_stage": intent,
    }


async def profile_node(state: JobGuardState) -> dict:
    """Profile building node"""
    logger.info("[Graph] Profile node executing")
    return {
        "current_stage": "profile_complete",
    }


async def job_parse_node(state: JobGuardState) -> dict:
    """Job parsing node"""
    logger.info("[Graph] Job parse node executing")
    return {
        "current_stage": "job_parsed",
    }


async def background_check_node(state: JobGuardState) -> dict:
    """Background check node"""
    logger.info("[Graph] Background check node executing")
    return {
        "current_stage": "background_checked",
    }


async def job_match_node(state: JobGuardState) -> dict:
    """Job matching node"""
    logger.info("[Graph] Job match node executing")
    return {
        "current_stage": "matched",
    }


async def resume_generate_node(state: JobGuardState) -> dict:
    """Resume generation node"""
    logger.info("[Graph] Resume generation node executing")
    return {
        "current_stage": "resume_generated",
    }


async def recommend_node(state: JobGuardState) -> dict:
    """Job recommendation node"""
    logger.info("[Graph] Recommendation node executing")
    return {
        "current_stage": "recommended",
    }


# ─── Routing Functions ─────────────────────────────────────────────────

def route_by_intent(state: JobGuardState) -> Literal[
    "profile", "job_parse", "resume_generate", "recommend", "fallback"
]:
    """Route to the appropriate node based on intent"""
    intent = state.get("intent", "build_profile")

    routing = {
        "build_profile": "profile",
        "analyze_job": "job_parse",
        "generate_resume": "resume_generate",
        "recommend_jobs": "recommend",
    }

    target = routing.get(intent, "fallback")
    logger.info(f"[Graph] Routing: {intent} -> {target}")
    return target


def route_after_job_parse(state: JobGuardState) -> Literal["background_check", "job_match", END]:
    """After parsing a job, decide next step"""
    intent = state.get("intent", "")
    if intent == "analyze_job":
        return "background_check"
    elif intent == "generate_resume":
        return "job_match"
    return END


def route_after_background_check(state: JobGuardState) -> Literal["job_match", END]:
    """After background check, optionally match"""
    return "job_match"


# ─── Fallback ──────────────────────────────────────────────────────────

async def fallback_node(state: JobGuardState) -> dict:
    """Fallback for unrecognized intents"""
    logger.warning(f"[Graph] Fallback: unknown intent={state.get('intent')}")
    return {
        "current_stage": "fallback",
        "error": f"Unknown intent: {state.get('intent')}",
    }


# ─── Graph Builder ─────────────────────────────────────────────────────

def build_jobguard_graph() -> StateGraph:
    """
    Build the JobGuard LangGraph workflow.

    Graph structure:

        [router] ──intent──> [profile] ────────────────> END
                   │
                   ├────────> [job_parse] ──> [background_check] ──> [job_match] ──> END
                   │
                   ├────────> [resume_generate] ─────────────────────> END
                   │
                   ├────────> [recommend] ───────────────────────────> END
                   │
                   └────────> [fallback] ────────────────────────────> END
    """
    # Create graph
    workflow = StateGraph(JobGuardState)

    # Add nodes
    workflow.add_node("router", router_node)
    workflow.add_node("profile", profile_node)
    workflow.add_node("job_parse", job_parse_node)
    workflow.add_node("background_check", background_check_node)
    workflow.add_node("job_match", job_match_node)
    workflow.add_node("resume_generate", resume_generate_node)
    workflow.add_node("recommend", recommend_node)
    workflow.add_node("fallback", fallback_node)

    # Set entry point
    workflow.set_entry_point("router")

    # Router -> conditional edges
    workflow.add_conditional_edges(
        "router",
        route_by_intent,
        {
            "profile": "profile",
            "job_parse": "job_parse",
            "resume_generate": "resume_generate",
            "recommend": "recommend",
            "fallback": "fallback",
        },
    )

    # Profile -> END
    workflow.add_edge("profile", END)

    # Job parse -> conditional (background_check or match)
    workflow.add_conditional_edges(
        "job_parse",
        route_after_job_parse,
        {
            "background_check": "background_check",
            "job_match": "job_match",
            END: END,
        },
    )

    # Background check -> job_match
    workflow.add_conditional_edges(
        "background_check",
        route_after_background_check,
        {
            "job_match": "job_match",
            END: END,
        },
    )

    # Job match -> END
    workflow.add_edge("job_match", END)

    # Resume generate -> END
    workflow.add_edge("resume_generate", END)

    # Recommend -> END
    workflow.add_edge("recommend", END)

    # Fallback -> END
    workflow.add_edge("fallback", END)

    return workflow


def compile_graph():
    """Compile the graph with memory checkpoint"""
    workflow = build_jobguard_graph()
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


# Global compiled graph
jobguard_graph = compile_graph()
