"""
对话接口（SSE 流式）

接入 ProfileAgent 和 JobParser/BackgroundCheck Agent
"""

import json
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.models.chat import ChatSession, ChatMessage
from app.models.user import User
from app.api.auth import get_current_user, require_own_user
from app.agents.profile_agent import profile_agent
from app.agents.orchestrator import detect_intent, route_by_intent
from app.services.profile_service import profile_service
from app.services.job_service import job_service
from app.services.resume_service import resume_service
from app.agents.job_matcher import job_matcher
from app.observability.tracing import trace_recorder

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateSessionRequest(BaseModel):
    user_id: int
    session_type: str = "general"


class SendMessageRequest(BaseModel):
    content: str
    message_type: str = "text"


# ─── 会话管理 ─────────────────────────────────────────────

@router.post("/session")
async def create_session(
    req: CreateSessionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_own_user(req.user_id, current_user)
    session = ChatSession(
        user_id=req.user_id,
        session_type=req.session_type,
        status="active",
        context_json={},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "session_id": session.id,
        "session_type": session.session_type,
        "status": session.status,
    }


@router.get("/sessions")
async def list_sessions(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前账号的历史会话，供重新登录后恢复。"""
    require_own_user(user_id, current_user)
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .all()
    )
    result = []
    for item in sessions:
        first_message = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == item.id, ChatMessage.role == "user")
            .order_by(ChatMessage.created_at.asc())
            .first()
        )
        result.append({
            "session_id": item.id,
            "session_type": item.session_type,
            "title": (first_message.content[:24] if first_message else "新对话"),
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        })
    return {"sessions": result}


# ─── 核心：发送消息 ────────────────────────────────────────

@router.post("/{session_id}/message")
async def send_message(
    session_id: int,
    req: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    require_own_user(session.user_id, current_user)

    user_id = session.user_id
    session_type = session.session_type

    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=req.content,
        message_type=req.message_type,
    )
    db.add(user_msg)
    db.commit()

    history = _get_conversation_history(db, session_id)

    async def _event_stream_impl():
        try:
            intent = await detect_intent(req.content)
            logger.info(f"[Chat] Intent: {intent}, user_id={user_id}")

            yield _sse_event("intent", {
                "intent": intent,
                "session_type": session_type,
            })

            if intent == "build_profile":
                async for event in _handle_profile_building(
                    db, user_id, session_id, req.content, history
                ):
                    yield event
            elif intent == "analyze_job":
                async for event in _handle_job_analysis(
                    db, user_id, session_id, req.content, history
                ):
                    yield event
            elif intent == "generate_resume":
                async for event in _handle_resume_generation(
                    db, user_id, session_id, req.content, history
                ):
                    yield event
            elif intent == "recommend_jobs":
                async for event in _handle_job_recommendation(
                    db, user_id, session_id
                ):
                    yield event
            else:
                from app.llm.gateway import llm_gateway
                generic_message = await llm_gateway.chat_primary(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是 JobGuard 中文求职助手。结合上下文直接回答用户，语言自然、简洁、专业。"
                                "只讨论求职、岗位、简历、职业规划；信息不足时提出一个明确的补充问题。"
                                "不要声称已经检索或核实没有实际调用的数据。"
                            ),
                        },
                        *history[-12:],
                    ],
                    temperature=0.4,
                    max_tokens=800,
                    prompt_version="chat-general-v1",
                )
                yield _sse_event("message", {
                    "content": generic_message,
                })
                _save_assistant_message(db, session_id, generic_message)

            yield _sse_event("done", {"status": "completed"})

        except Exception as e:
            logger.error(f"[Chat] Error: {e}", exc_info=True)
            yield _sse_event("error", {"message": str(e)})
            yield _sse_event("done", {"status": "error"})

    async def event_stream():
        async with trace_recorder.trace(
            request_id=f"chat-{session_id}", name="chat.message"
        ):
            async for event in _event_stream_impl():
                yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Profile Building ─────────────────────────────────────

async def _handle_profile_building(
    db: Session,
    user_id: int,
    session_id: int,
    user_message: str,
    history: list[dict],
):
    is_resume = _detect_resume_content(user_message)

    if is_resume:
        yield _sse_event("status", {"stage": "parsing_resume", "message": "Parsing your resume..."})

        result = await profile_service.process_resume(db, user_id, user_message)

        if "error" in result:
            yield _sse_event("error", {"message": result["error"]})
            return

        yield _sse_event("resume_parsed", {
            "summary": (
                f"Detected: {result.get('parsed', {}).get('degree', 'Unknown degree')} | "
                f"{result.get('parsed', {}).get('school', 'Unknown school')} | "
                f"{len(result.get('parsed', {}).get('projects', []))} projects | "
                f"{len(result.get('parsed', {}).get('skills', []))} skills"
            ),
            "completeness": result["completeness"],
            "missing_fields": result["missing_fields"],
        })

        _save_assistant_message(
            db, session_id,
            f"Resume parsed! Profile completeness: {result['completeness']}%"
        )

    # Extract updates from conversation
    recent_msgs = [{"role": "user", "content": user_message}]
    collected = profile_service.get_full_profile(db, user_id)

    updates = await profile_agent.extract_updates(recent_msgs, collected)

    if updates:
        await profile_service.update_profile(db, user_id, updates)
        yield _sse_event("profile_updated", {
            "updated_fields": list(updates.keys()),
        })

    current_profile = profile_service.get_full_profile(db, user_id)
    completeness = profile_agent.check_completeness({
        **current_profile.get("basic", {}),
        **current_profile.get("preferences", {}),
    })

    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session:
        session.session_type = "profile_building"
        db.commit()

    if completeness["ready"]:
        completion_msg = profile_agent._build_completion_message({
            **current_profile.get("basic", {}),
            **current_profile.get("preferences", {}),
        })
        yield _sse_event("message", {"content": completion_msg})
        _save_assistant_message(db, session_id, completion_msg)
    else:
        question = await profile_agent.generate_question(
            {**current_profile.get("basic", {}), **current_profile.get("preferences", {})},
            history,
        )
        yield _sse_event("message", {"content": question})
        _save_assistant_message(db, session_id, question)


# ─── Job Analysis (Phase 3) ───────────────────────────────

async def _handle_job_analysis(db, user_id, session_id, user_message, history):
    """Job analysis flow: Parse -> Background Check -> Report"""
    yield _sse_event("status", {"stage": "parsing", "message": "Parsing job info..."})

    job_info = await job_service.parse_job(user_message)
    if "error" in job_info:
        yield _sse_event("error", {"message": job_info["error"]})
        _save_assistant_message(db, session_id, f"Error: {job_info['error']}")
        return

    yield _sse_event("job_parsed", {
        "company_name": job_info.get("company_name"),
        "job_title": job_info.get("job_title"),
        "salary": f"{job_info.get('salary_min', '?')}-{job_info.get('salary_max', '?')}",
        "location": job_info.get("location"),
        "category": job_info.get("sub_category"),
    })

    yield _sse_event("status", {"stage": "background_check", "message": "Running background check..."})

    async def web_search_wrapper(query: str) -> str:
        try:
            from app.llm.gateway import llm_gateway
            messages = [
                {"role": "system", "content": "You are a search assistant. Return search result summary."},
                {"role": "user", "content": f"Search for: {query}"},
            ]
            result = await llm_gateway.chat_primary(messages, temperature=0.3)
            return result
        except Exception:
            return "[WebSearch unavailable]"

    report = await job_service.analyze_job(
        db, user_id, user_message,
        web_search_func=web_search_wrapper,
    )

    if "error" in report:
        yield _sse_event("error", {"message": report["error"]})
        return

    r = report["report"]
    dimensions = r.get("dimensions", {})

    for dim_name, dim_label in [
        ("social_insurance", "Social Insurance"),
        ("labor_disputes", "Labor Disputes"),
        ("online_reputation", "Online Reputation"),
        ("jd_analysis", "JD Analysis"),
    ]:
        dim = dimensions.get(dim_name)
        if dim:
            yield _sse_event("background_result", {
                "dimension": dim_label,
                "assessment": dim.get("assessment", ""),
                "score": dim.get("score", 3),
            })

    yield _sse_event("analysis_complete", {
        "risk_level": r.get("risk_level"),
        "recommendation_index": r.get("recommendation_index"),
        "recommendation_text": r.get("recommendation_text"),
        "summary": r.get("summary"),
        "red_flags": r.get("red_flags", []),
        "positive_points": r.get("positive_points", []),
        "advice": r.get("advice"),
    })

    report_text = r.get("report", "") or r.get("summary", "")
    _save_assistant_message(db, session_id, report_text)
    yield _sse_event("message", {"content": report_text})


# ─── Resume Generation (Phase 4) ──────────────────────────

async def _handle_resume_generation(db, user_id, session_id, user_message, history):
    """Resume generation flow"""
    yield _sse_event("status", {"stage": "generating", "message": "Generating tailored resume..."})

    # Try to extract job info from user message or use last analyzed job
    job_info = None
    job_id = None

    # Check if user provided a job link/description in the message
    try:
        job_info = await job_service.parse_job(user_message)
        if "error" in job_info:
            job_info = None
    except Exception:
        pass

    if not job_info:
        # Fallback: try to find last analyzed job for this user
        from app.models.analysis import JobAnalysis
        last_analysis = (
            db.query(JobAnalysis)
            .filter(JobAnalysis.user_id == user_id)
            .order_by(JobAnalysis.created_at.desc())
            .first()
        )
        if last_analysis and last_analysis.job_id:
            job_id = last_analysis.job_id
            job_info = job_service.get_job_detail(db, job_id)

    if not job_info:
        yield _sse_event("error", {
            "message": "No job info found. Please analyze a job first or paste a job link."
        })
        _save_assistant_message(
            db, session_id,
            "Please paste a job link or describe the position you want to apply for first."
        )
        return

    yield _sse_event("status", {
        "stage": "retrieving",
        "message": f"Retrieving your projects for {job_info.get('job_title', 'this position')}..."
    })

    result = await resume_service.generate_resume(
        db,
        user_id=user_id,
        job_id=job_id,
        job_info=job_info,
        options={"max_projects": 3},
    )

    if "error" in result:
        yield _sse_event("error", {"message": result["error"]})
        _save_assistant_message(db, session_id, f"Error: {result['error']}")
        return

    yield _sse_event("resume_generated", {
        "resume_id": result.get("resume_id"),
        "company_name": job_info.get("company_name"),
        "job_title": job_info.get("job_title"),
        "projects_selected": len(result.get("selected_projects", [])),
    })

    # Send greeting first
    greeting = result.get("greeting", "")
    if greeting:
        yield _sse_event("greeting", {"text": greeting})

    # Send resume preview
    resume_md = result.get("resume_markdown", "")
    yield _sse_event("message", {"content": resume_md})

    _save_assistant_message(db, session_id, resume_md)

    # Download hint
    yield _sse_event("message", {
        "content": (
            f"\n---\n"
            f"**Greeting message:**\n{greeting}\n\n"
            f"Download resume: `/api/resume/{result.get('resume_id')}/download`"
        ),
    })


async def _handle_job_recommendation(db, user_id, session_id):
    """Job recommendation flow"""
    yield _sse_event("status", {"stage": "recommending", "message": "Finding matching jobs..."})
    user_profile = profile_service.get_full_profile(db, user_id)
    jobs_result = job_service.list_jobs(db, page=1, page_size=50)
    jobs = jobs_result.get("items", [])
    if not jobs:
        yield _sse_event("message", {"content": "No jobs in database yet. Paste a job link for me to analyze."})
        return
    matches = await job_matcher.match_batch(user_profile, jobs, top_k=10)
    if not matches:
        yield _sse_event("message", {"content": "No strong matches found."})
        return
    lines = ["## Top Job Matches", ""]
    for i, m in enumerate(matches[:5]):
        j = m["job"]
        s = m["match"].get("overall_score", 0)
        lines.append(f"{i+1}. {j.get('job_title')} @ {j.get('company_name')} - {s}%")
        lines.append(f"   {j.get('location', '')} | {j.get('salary_min', '?')}-{j.get('salary_max', '?')}K")
        lines.append("")
    msg = "\n".join(lines)
    yield _sse_event("message", {"content": msg})
    _save_assistant_message(db, session_id, msg)


# ─── History ───────────────────────────────────────────────

@router.get("/{session_id}/history")
async def get_history(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    require_own_user(session.user_id, current_user)
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return {
        "session_id": session_id,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "message_type": msg.message_type,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages
        ],
    }


# ─── Utils ─────────────────────────────────────────────────

def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_conversation_history(db: Session, session_id: int, limit: int = 30) -> list[dict]:
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    messages.reverse()
    return [{"role": msg.role, "content": msg.content} for msg in messages]


def _save_assistant_message(db: Session, session_id: int, content: str):
    msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=content,
        message_type="text",
    )
    db.add(msg)
    db.commit()


def _detect_resume_content(text: str) -> bool:
    if len(text) < 200:
        return False
    resume_keywords = [
        "education", "experience", "project", "skill",
        "university", "bachelor", "master", "PhD", "degree",
        "intern", "work", "job",
    ]
    match_count = sum(1 for kw in resume_keywords if kw.lower() in text.lower())
    return match_count >= 2
