"""Transparent Agent, LangGraph, tool execution and trace endpoints."""

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.tool_registry import tool_registry
from app.auth import get_current_user_id
from app.graph.builder import get_jobguard_graph
from app.models.agent_run import AgentRun
from app.models.base import get_db
from app.services.agent_observability_service import agent_observability_service


router = APIRouter()


class ExecuteToolRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)
    confirmed: bool = False


@router.get("/graph")
async def get_agent_graph(_current_user_id: int = Depends(get_current_user_id)):
    graph = get_jobguard_graph().get_graph()
    nodes = [name for name in graph.nodes if name not in {"__start__", "__end__"}]
    edges = [
        {"source": edge.source, "target": edge.target}
        for edge in graph.edges
        if edge.source != "__start__" and edge.target != "__end__"
    ]
    return {
        "code": 0,
        "data": {
            "runtime": "langgraph",
            "nodes": nodes,
            "edges": edges,
            "compiled_once": True,
            "business_dispatch": "app.api.chat",
            "note": "生产 LangGraph 执行意图分类、确定性任务规划和证据门禁；具体业务步骤由 API 层按计划显式执行并管理数据库事务。",
        },
    }


@router.get("/tools")
async def get_agent_tools(_current_user_id: int = Depends(get_current_user_id)):
    tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "category": tool.category,
            "available": tool.is_available,
            "execution_mode": tool.execution_mode,
            "risk_level": tool.risk_level,
            "requires_confirmation": tool.requires_confirmation,
            "expose_via_mcp": tool.expose_via_mcp,
        }
        for tool in tool_registry.list_available()
    ]
    return {
        "code": 0,
        "data": {
            "items": tools,
            "mcp": {
                "transport": "stdio",
                "command": "python -m app.mcp_server",
                "status": "ready",
            },
        },
    }


@router.post("/tools/{tool_name}/execute")
async def execute_agent_tool(
    tool_name: str,
    req: ExecuteToolRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    tool = tool_registry.get(tool_name)
    if not tool or not tool.is_available:
        raise HTTPException(status_code=404, detail="工具不存在或尚未接通")

    run = agent_observability_service.start_run(
        db,
        user_id=current_user_id,
        session_id=None,
        workflow="tool_execution",
        intent=tool_name,
        input_summary=f"执行工具 {tool_name}",
        context_snapshot={"execution_mode": tool.execution_mode, "risk_level": tool.risk_level},
    )
    started_at = time.perf_counter()
    try:
        result = await tool_registry.execute(
            tool_name,
            req.arguments,
            user_id=current_user_id,
            confirmed=req.confirmed,
        )
        agent_observability_service.record_tool_call(
            db,
            run=run,
            tool_name=tool_name,
            arguments=req.arguments,
            result=result,
            started_at=started_at,
            requires_confirmation=tool.requires_confirmation,
            confirmed=req.confirmed,
        )
        agent_observability_service.complete_run(db, run, f"{tool_name}: {result.get('status', 'success') if isinstance(result, dict) else 'success'}")
        return {"code": 0, "data": result, "run_id": run.id}
    except (ValueError, KeyError, PermissionError) as exc:
        agent_observability_service.record_tool_call(
            db,
            run=run,
            tool_name=tool_name,
            arguments=req.arguments,
            result={},
            started_at=started_at,
            requires_confirmation=tool.requires_confirmation,
            confirmed=req.confirmed,
            error=exc,
        )
        agent_observability_service.fail_run(db, run, "tool_execution", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        agent_observability_service.record_tool_call(
            db,
            run=run,
            tool_name=tool_name,
            arguments=req.arguments,
            result={},
            started_at=started_at,
            requires_confirmation=tool.requires_confirmation,
            confirmed=req.confirmed,
            error=exc,
        )
        agent_observability_service.fail_run(db, run, "tool_execution", exc)
        raise HTTPException(status_code=500, detail="工具执行失败，请查看 Agent 运行记录") from exc


@router.get("/runs")
async def list_agent_runs(
    limit: int = 50,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return {
        "code": 0,
        "data": {"items": agent_observability_service.list_runs(db, current_user_id, limit)},
    }


@router.get("/runs/{run_id}")
async def get_agent_run(
    run_id: str,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.user_id == current_user_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Agent 运行记录不存在")
    return {"code": 0, "data": agent_observability_service.run_to_dict(db, run)}


@router.get("/metrics")
async def get_agent_metrics(
    days: int = 30,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return {"code": 0, "data": agent_observability_service.metrics(db, current_user_id, days)}
