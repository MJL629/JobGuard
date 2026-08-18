"""
对话接口（SSE 流式）

接入 ProfileAgent 和 JobParser/BackgroundCheck Agent
"""

import json
import asyncio
import logging
import re
import uuid
from contextvars import ContextVar
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.base import SessionLocal, get_db
from app.models.chat import ChatSession, ChatMessage
from app.agents.profile_agent import profile_agent
from app.agents.tools.career_tools import recommend_learning_resources
from app.graph.builder import classify_message
from app.llm.gateway import llm_gateway
from app.services.profile_service import profile_service
from app.services.job_service import job_service
from app.services.resume_service import resume_service
from app.services.agent_observability_service import agent_observability_service
from app.auth import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateSessionRequest(BaseModel):
    user_id: int | None = None  # 兼容旧客户端；服务端始终使用 token 中的用户
    session_type: str = "general"


class SendMessageRequest(BaseModel):
    content: str
    message_type: str = "text"


# ─── 会话管理 ─────────────────────────────────────────────

@router.post("/session")
async def create_session(
    req: CreateSessionRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    current_profile = profile_service.get_full_profile(db, current_user_id)
    profile_data = _flatten_profile(current_profile)
    completeness = profile_agent.check_completeness(profile_data)
    interview = profile_agent.next_deep_interview_question(
        profile_data, current_profile.get("interview_memory") or {}
    )
    interview_pending = completeness["ready"] and not interview["complete"]
    if interview_pending:
        profile_service.save_interview_memory(db, current_user_id, interview["state"])

    session = ChatSession(
        user_id=current_user_id,
        session_type="profile_building" if not completeness["ready"] or interview_pending else "general",
        status="active",
        context_json={"profile_interview": interview["state"]},
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    if interview_pending:
        first_message = (
            f"欢迎回来！核心求职画像完整度为 {completeness['completeness']}%，"
            f"深度访谈进度为 {interview['state']['depth_score']}%。\n\n"
            f"为了让后续岗位匹配、面试表达和定向简历更贴近真实经历，我继续问一个问题：\n\n"
            f"{interview['question']}"
        )
    elif completeness["ready"]:
        first_message = (
            f"欢迎回来！你的求职画像完整度为 {completeness['completeness']}%。"
            "你可以让我推荐岗位、分析岗位风险，或继续补充画像。"
        )
    else:
        first_message = await profile_agent.generate_question(profile_data, [])

    _save_assistant_message(db, session.id, first_message)
    return {
        "session_id": session.id,
        "session_type": session.session_type,
        "status": session.status,
        "first_message": first_message,
        "completeness": completeness["completeness"],
    }


# ─── 核心：发送消息 ────────────────────────────────────────

@router.post("/{session_id}/message")
async def send_message(
    session_id: int,
    req: SendMessageRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")

    user_id = session.user_id
    session_type = session.session_type or "general"

    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=req.content,
        message_type=req.message_type,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    history = _get_conversation_history(db, session_id)
    stream_id = f"{session_id}-{user_msg.id}-{uuid.uuid4().hex[:12]}"

    async def event_stream():
        encoder = SSEEventEncoder(
            stream_id=stream_id,
            request_message_id=user_msg.id,
            persist=lambda record: _persist_sse_event(session_id, record),
        )
        encoder_token = _active_sse_encoder.set(encoder)
        agent_run = None
        current_step = "received"
        try:
            try:
                agent_run = agent_observability_service.start_run(
                    db,
                    user_id=user_id,
                    session_id=session_id,
                    workflow="chat",
                    input_summary=req.content,
                    context_snapshot={
                        "session_type": session_type,
                        "history_messages": len(history),
                        "message_type": req.message_type,
                    },
                )
            except Exception:
                logger.exception("[Chat] Agent 运行记录初始化失败，业务流程继续")
            graph_result = await classify_message(
                req.content,
                user_id=str(user_id),
                session_id=str(session_id),
                session_type=session_type,
            )
            intent = graph_result["intent"]
            current_step = f"intent:{intent}"
            if agent_run:
                agent_observability_service.update_step(db, agent_run, current_step, intent=intent)
            logger.info(f"[Chat] Intent: {intent}, user_id={user_id}")

            yield _sse_event("intent", {
                "intent": intent,
                "session_type": session_type,
                "graph_trace": graph_result["graph_trace"],
                "execution_plan": graph_result.get("execution_plan", []),
                "evidence_policy": graph_result.get("evidence_policy", {}),
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
            elif intent == "career_advice":
                async for event in _handle_career_advice(
                    db, user_id, session_id, req.content
                ):
                    yield event
            else:
                yield _sse_event("message", {
                    "content": (
                        "你好，我是 JobGuard。你可以：\n"
                        "- 上传简历或继续补充求职偏好\n"
                        "- 粘贴完整岗位描述进行避雷分析\n"
                        "- 让我按当前画像推荐数据库岗位"
                    ),
                })

            if agent_run:
                try:
                    agent_observability_service.complete_run(db, agent_run, f"intent={intent}")
                except Exception:
                    logger.exception("[Chat] failed to persist Agent run completion")
            yield _sse_event("done", {"status": "completed", "run_id": agent_run.id if agent_run else None})

        except Exception as e:
            logger.error(f"[Chat] Error: {e}", exc_info=True)
            if agent_run:
                try:
                    agent_observability_service.fail_run(db, agent_run, current_step, e)
                except Exception:
                    logger.exception("[Chat] Agent 失败记录写入失败")
            yield _sse_event("error", {"message": "处理消息时发生错误，请稍后重试。"})
            yield _sse_event("done", {"status": "error", "run_id": agent_run.id if agent_run else None})
        finally:
            _active_sse_encoder.reset(encoder_token)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Stream-ID": stream_id,
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
        yield _sse_event("status", {"stage": "parsing_resume", "message": "正在解析简历..."})

        result = await profile_service.process_resume(db, user_id, user_message)

        if "error" in result:
            yield _sse_event("error", {"message": result["error"]})
            return

        yield _sse_event("resume_parsed", {
            "summary": (
                f"识别结果：{result.get('parsed', {}).get('degree', '学历未识别')} | "
                f"{result.get('parsed', {}).get('school', '学校未识别')} | "
                f"{len(result.get('parsed', {}).get('projects', []))} 个项目 | "
                f"{len(result.get('parsed', {}).get('skills', []))} 项技能"
            ),
            "completeness": result["completeness"],
            "missing_fields": result["missing_fields"],
        })

        _save_assistant_message(
            db, session_id,
            f"简历解析完成，画像完整度为 {result['completeness']}%。"
        )

    # 重要强度偏好需要用户确认后再写画像，避免把限定条件泛化。
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    session_context = dict(session.context_json or {}) if session else {}
    pending_confirmation = session_context.get("pending_profile_confirmation")
    confirmed_updates = None
    confirmed_interpretation = None

    if pending_confirmation:
        stripped = user_message.strip()
        affirmative = bool(re.fullmatch(r"(?:正确|对|是的|没错|确认|可以)", stripped))
        negative_only = bool(re.fullmatch(r"(?:不对|不是|否|不正确)", stripped))
        if affirmative:
            confirmed_updates = dict(pending_confirmation.get("updates") or {})
            confirmed_interpretation = pending_confirmation.get("interpretation")
            confirmed_updates.update(profile_agent._extract_rule_based_updates(user_message))
            evidence_history = list(session_context.get("profile_evidence_history") or [])
            evidence_history.append({
                **pending_confirmation,
                "status": "confirmed",
            })
            session_context["profile_evidence_history"] = evidence_history[-20:]
            session_context.pop("pending_profile_confirmation", None)
            session.context_json = session_context
            db.commit()
        elif negative_only:
            session_context.pop("pending_profile_confirmation", None)
            session.context_json = session_context
            db.commit()
            clarification = (
                "好的，我不会保存刚才的理解。请分别告诉我："
                "你能接受多频繁的加班，以及不能接受的强度或情形。"
            )
            yield _sse_event("message", {"content": clarification})
            _save_assistant_message(db, session_id, clarification)
            return
        else:
            # 用户直接给出修正内容时，放弃旧提案并按新原句重新抽取。
            session_context.pop("pending_profile_confirmation", None)
            session.context_json = session_context
            db.commit()

    # 使用最近多轮历史理解“改成上海”“薪资再高一点”等指代和纠正。
    recent_msgs = history[-10:]
    collected = profile_service.get_full_profile(db, user_id)

    flattened_profile = _flatten_profile(collected)
    updates = confirmed_updates or await profile_agent.extract_updates(
        recent_msgs, flattened_profile
    )
    # A single user turn may contain both a nuanced preference and a concrete
    # project/internship.  Preserve the experience before pausing for preference
    # confirmation so that one branch cannot silently discard the other.
    experience = await profile_agent.extract_experience_candidate(user_message)

    if updates and confirmed_updates is None:
        confirmation = profile_agent.build_constraint_confirmation(
            user_message, updates, flattened_profile
        )
        if confirmation and session:
            session_context = dict(session.context_json or {})
            session_context["pending_profile_confirmation"] = confirmation
            session.context_json = session_context
            db.commit()
            yield _sse_event("profile_confirmation", {
                "interpretation": confirmation["interpretation"],
                "raw_evidence": confirmation["raw_evidence"],
            })
            if experience:
                saved_experience = profile_service.add_experience(db, user_id, experience)
                yield _sse_event("experience_saved", saved_experience)
            yield _sse_event("message", {"content": confirmation["message"]})
            _save_assistant_message(db, session_id, confirmation["message"])
            return

    turn_acknowledgement = ""
    if updates:
        await profile_service.update_profile(db, user_id, updates)
        yield _sse_event("profile_updated", {
            "updated_fields": list(updates.keys()),
            "confirmed": confirmed_updates is not None,
        })
        if confirmed_interpretation:
            acknowledgement = f"已确认并保存：{confirmed_interpretation}。"
            yield _sse_event("message", {"content": acknowledgement})
            _save_assistant_message(db, session_id, acknowledgement)
        else:
            turn_acknowledgement = profile_agent.build_turn_acknowledgement(
                updates, experience
            )

    if experience:
        saved_experience = profile_service.add_experience(db, user_id, experience)
        yield _sse_event("experience_saved", saved_experience)

    current_profile = profile_service.get_full_profile(db, user_id)
    flattened_current = _flatten_profile(current_profile)
    completeness = profile_agent.check_completeness(flattened_current)

    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if completeness["ready"]:
        interview_memory = current_profile.get("interview_memory") or {}
        if confirmed_updates is None:
            interview_memory = profile_agent.record_deep_interview_answer(
                interview_memory, user_message
            )
        interview = profile_agent.next_deep_interview_question(
            flattened_current, interview_memory
        )
        saved_memory = profile_service.save_interview_memory(
            db, user_id, interview["state"]
        )
        if session:
            session_context = dict(session.context_json or {})
            session_context["profile_interview"] = saved_memory
            session.context_json = session_context
            session.session_type = "general" if interview["complete"] else "profile_building"
            db.commit()

        yield _sse_event("profile_interview", {
            "phase": saved_memory.get("phase"),
            "dimension": interview.get("dimension"),
            "depth_score": saved_memory.get("depth_score", 0),
            "explored_dimensions": saved_memory.get("explored_dimensions", []),
            "skipped_dimensions": saved_memory.get("skipped_dimensions", []),
        })
        if interview["complete"]:
            completion_msg = profile_agent._build_completion_message(flattened_current)
        else:
            completion_msg = (
                f"这条信息已纳入画像证据。深度访谈进度：{saved_memory.get('depth_score', 0)}%。\n\n"
                f"{interview['question']}"
            )
        if turn_acknowledgement:
            completion_msg = f"{turn_acknowledgement}\n\n{completion_msg}"
        yield _sse_event("message", {"content": completion_msg})
        _save_assistant_message(db, session_id, completion_msg)
    else:
        if session:
            session.session_type = "profile_building"
            db.commit()
        question = await profile_agent.generate_question(
            _flatten_profile(current_profile),
            history,
        )
        if turn_acknowledgement:
            question = f"{turn_acknowledgement}\n\n{question}"
        yield _sse_event("message", {"content": question})
        _save_assistant_message(db, session_id, question)


# ─── Job Analysis (Phase 3) ───────────────────────────────

async def _handle_job_analysis(db, user_id, session_id, user_message, history):
    """Job analysis flow: Parse -> Background Check -> Report"""
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id, ChatSession.user_id == user_id
    ).first()
    last_analysis = dict((session.context_json or {}).get("last_job_analysis") or {}) if session else {}
    generic_followup = bool(re.fullmatch(
        r"\s*(?:确定[，,。\s]*)?(?:帮我)?(?:继续)?(?:分析|看看|评估)(?:一下)?(?:值不值得投|是否值得投递)?[。！!？?\s]*",
        user_message,
    )) or bool(re.search(r"值不值得投|是否值得投递", user_message))

    if generic_followup and last_analysis.get("report"):
        job_info = last_analysis.get("job_info") or {}
        r = last_analysis.get("report") or {}
        yield _sse_event("job_parsed", {
            "company_name": job_info.get("company_name"),
            "job_title": job_info.get("job_title"),
            "salary": f"{job_info.get('salary_min', '?')}-{job_info.get('salary_max', '?')}",
            "location": job_info.get("location"),
            "category": job_info.get("sub_category"),
            "context_reused": True,
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
        report_text = _build_job_decision_message(job_info, r, reused=True)
        _save_assistant_message(db, session_id, report_text)
        yield _sse_event("message", {"content": report_text})
        return

    yield _sse_event("status", {"stage": "parsing", "message": "正在解析岗位信息..."})

    job_info = await job_service.parse_job(user_message)
    if "error" in job_info:
        yield _sse_event("error", {"message": job_info["error"]})
        _save_assistant_message(db, session_id, f"岗位解析失败：{job_info['error']}")
        return

    yield _sse_event("job_parsed", {
        "company_name": job_info.get("company_name"),
        "job_title": job_info.get("job_title"),
        "salary": f"{job_info.get('salary_min', '?')}-{job_info.get('salary_max', '?')}",
        "location": job_info.get("location"),
        "category": job_info.get("sub_category"),
    })

    yield _sse_event("status", {"stage": "background_check", "message": "正在分析 JD 原文风险..."})

    report = await job_service.analyze_job(
        db, user_id, user_message,
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

    report_text = _build_job_decision_message(report.get("job_info") or job_info, r)
    if session:
        context = dict(session.context_json or {})
        context["last_job_analysis"] = {
            "job_info": report.get("job_info") or job_info,
            "report": r,
            "job_id": report.get("job_id"),
            "source": "chat",
            "input_text": user_message[:12000],
        }
        session.context_json = context
        db.commit()
    _save_assistant_message(db, session_id, report_text)
    yield _sse_event("message", {"content": report_text})


def _build_job_decision_message(job_info: dict, report: dict, reused: bool = False) -> str:
    """Make the final apply/no-apply judgment explicit and evidence-aware."""
    index = report.get("recommendation_index")
    red_flags = report.get("red_flags") or []
    risk = report.get("risk_level") or "未知"
    if isinstance(index, (int, float)) and index >= 4 and not red_flags:
        decision = "值得投递"
    elif isinstance(index, (int, float)) and index <= 2:
        decision = "不建议作为优先投递"
    else:
        decision = "可以谨慎投递，但建议先核实关键信息"
    context_note = "（已接续你上一张岗位截图）" if reused else ""
    company = job_info.get("company_name") or "未完整识别企业"
    title = job_info.get("job_title") or "未完整识别岗位"
    source_count = len(report.get("sources") or report.get("verifiable_sources") or [])
    evidence_note = (
        f"本次报告附有 {source_count} 条可核验来源。"
        if source_count
        else "本次未取得可核验外部来源；企业社保、仲裁和口碑均不能当作已证实事实。"
    )
    details = report.get("report") or report.get("summary") or "暂无更多可核验结论。"
    advice = report.get("advice") or "面试前逐项确认薪资结构、工时、加班频率、试用期与社保缴纳主体。"
    return (
        f"## 是否值得投递{context_note}\n\n"
        f"**结论：{decision}**\n\n"
        f"- 企业：{company}\n- 岗位：{title}\n- 风险等级：{risk}\n"
        f"- 推荐指数：{index if index is not None else '证据不足，暂不评分'}\n\n"
        f"{details}\n\n### 证据说明\n{evidence_note}\n\n### 投递前核实\n{advice}"
    )


# ─── Resume Generation (Phase 4) ──────────────────────────

async def _handle_resume_generation(db, user_id, session_id, user_message, history):
    """Resume generation flow"""
    yield _sse_event("status", {"stage": "generating", "message": "正在生成定向简历并执行事实核查..."})

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
            "message": "没有找到岗位信息，请先分析岗位或粘贴完整岗位描述。"
        })
        _save_assistant_message(
            db, session_id,
            "请先粘贴完整岗位描述，或先在岗位分析页保存目标岗位。"
        )
        return

    yield _sse_event("status", {
        "stage": "retrieving",
        "message": f"正在为 {job_info.get('job_title', '目标岗位')} 检索真实项目经历..."
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
        _save_assistant_message(db, session_id, f"简历生成失败：{result['error']}")
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
            f"**招呼语：**\n{greeting}\n\n"
            f"简历已生成，可前往“定向简历”页面下载 PDF 或 DOCX（记录 #{result.get('resume_id')}）。"
        ),
    })


async def _handle_job_recommendation(db, user_id, session_id):
    """Job recommendation flow"""
    try:
        yield _sse_event("status", {"stage": "recommending", "message": "正在从数据库中筛选岗位..."})
        result = job_service.recommend_jobs(db, user_id, page=1, page_size=5)
        jobs = result.get("items", [])
        if not jobs:
            msg = "数据库中暂无岗位，请先粘贴岗位链接让我分析。"
            yield _sse_event("message", {"content": msg})
            _save_assistant_message(db, session_id, msg)
            return
        
        yield _sse_event("status", {"stage": "matching", "message": f"已按画像评估 {result.get('total', 0)} 个数据库岗位。"})

        lines = ["## 推荐岗位", ""]
        for i, job in enumerate(jobs, 1):
            salary_min = f"{job.get('salary_min') / 1000:g}K" if job.get("salary_min") else "?"
            salary_max = f"{job.get('salary_max') / 1000:g}K" if job.get("salary_max") else "?"
            score = job.get("match_score")
            score_text = f"匹配度 {score}%" if score is not None else "暂不评分"
            lines.append(f"{i}. {job.get('job_title')} @ {job.get('company_name')} - {score_text}")
            lines.append(f"   {job.get('location', '')} | {salary_min}-{salary_max}")
            lines.append(f"   评分证据覆盖率：{job.get('evidence_coverage', 0)}%")
            if job.get("match_reasons"):
                lines.append(f"   匹配原因：{'；'.join(job['match_reasons'])}")
            if job.get("match_concerns"):
                lines.append(f"   需确认：{'；'.join(job['match_concerns'][:2])}")
            lines.append("")
        msg = "\n".join(lines)
        yield _sse_event("message", {"content": msg})
        _save_assistant_message(db, session_id, msg)
    except Exception as e:
        logger.error(f"[Chat] Job recommendation failed: {e}", exc_info=True)
        msg = f"岗位推荐出错：{str(e)[:100]}"
        yield _sse_event("error", {"message": msg})
        _save_assistant_message(db, session_id, msg)


async def _handle_career_advice(db, user_id, session_id, user_message):
    """Answer career questions with profile context and auditable resources."""
    profile = profile_service.get_full_profile(db, user_id)
    flattened = _flatten_profile(profile)
    requested_topic = next(
        (topic for topic in ("LangGraph", "FastAPI", "RAG", "Docker") if topic.lower() in user_message.lower()),
        "",
    )
    wants_resources = bool(re.search(r"课程|教程|网课|B站|b站|怎么学|学习路线", user_message))
    resource_result = None
    if wants_resources:
        resource_result = await recommend_learning_resources(topic=requested_topic, limit=4)
        yield _sse_event("tool_result", {
            "tool_name": "recommend_learning_resources",
            "status": resource_result["status"],
            "source_count": len(resource_result["items"]),
            "items": resource_result["items"],
        })

    profile_context = {
        "job_direction": flattened.get("preferred_job_types") or flattened.get("job_direction"),
        "skills": [item.get("skill_name") for item in flattened.get("skills", [])[:20]],
        "experiences": [
            {
                "type": item.get("experience_type"),
                "title": item.get("title") or item.get("project_name"),
                "role": item.get("role"),
            }
            for item in (flattened.get("experiences", []) + flattened.get("projects", []))[:10]
        ],
        "profile_completeness": profile.get("completeness", 0),
    }
    prompt = (
        "你是务实的中文求职教练。请直接回答用户问题，并结合其真实画像给出：\n"
        "1. 明确判断；2. 3-5 个可执行步骤；3. 面试时如何表达；4. 尚缺少的证据或风险。\n"
        "不要虚构用户经历、课程链接或量化结果。资源列表为空时不要编造链接。\n\n"
        f"用户问题：{user_message[:3000]}\n"
        f"用户画像摘要：{json.dumps(profile_context, ensure_ascii=False)}\n"
        f"已核对资源：{json.dumps((resource_result or {}).get('items', []), ensure_ascii=False)}"
    )
    try:
        answer = await llm_gateway.chat(
            [
                {"role": "system", "content": "回答必须具体、中文、可执行，并明确事实边界。"},
                {"role": "user", "content": prompt},
            ],
            provider="zhipu",
            temperature=0.5,
        )
    except Exception:
        logger.exception("[Chat] 职业建议模型调用失败，使用本地兜底")
        answer = ""

    if not answer or answer.lstrip().startswith("[Mock]") or len(answer.strip()) < 160:
        direction = "、".join(profile_context["job_direction"] or []) or "目标岗位"
        answer = (
            f"## 建议结论\n\n你现在应围绕“{direction}”补齐可讲、可验证的项目证据，"
            "而不是只继续堆技术名词。\n\n"
            "## 下一步行动\n\n"
            "1. 选一个最接近目标岗位的项目，写清业务问题、你的职责、关键取舍和真实结果。\n"
            "2. 对照目标 JD 标出已有证据、可以短期补齐的技能和暂时无法证明的要求。\n"
            "3. 为项目准备一段 90 秒概述，并准备性能、异常处理、测试和协作四类追问。\n"
            "4. 新学到的内容必须落到一个可运行功能、测试用例或技术文档，才能进入简历。\n\n"
            "## 面试表达\n\n使用“背景—目标—行动—结果—复盘”的顺序；没有量化结果就说清交付物和验证方法，不能编数字。"
        )

    if resource_result and resource_result["items"]:
        resource_lines = ["", "## 可核验学习资源", ""]
        for item in resource_result["items"]:
            resource_lines.append(f"- [{item['title']}]({item['url']})（{item['topic']}）")
        resource_lines.append("")
        resource_lines.append(resource_result["notice"])
        answer = answer.rstrip() + "\n" + "\n".join(resource_lines)

    _save_assistant_message(db, session_id, answer)
    yield _sse_event("message", {"content": answer})


# ─── History ───────────────────────────────────────────────

@router.get("/{session_id}/history")
async def get_history(
    session_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")

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


@router.get("/{session_id}/events")
async def replay_events(
    session_id: int,
    stream_id: str = Query(..., min_length=1, max_length=100),
    after_sequence: int = Query(0, ge=0),
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """补发已持久化的 SSE 事件；不会重新执行有副作用的业务节点。"""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")

    events = _get_replay_events(session.context_json or {}, stream_id, after_sequence)
    streams = (session.context_json or {}).get("sse_streams", {})
    if stream_id not in streams:
        raise HTTPException(status_code=404, detail="流事件缓存不存在或已过期")
    return {
        "session_id": session_id,
        "stream_id": stream_id,
        "events": events,
        "last_sequence": streams[stream_id].get("last_sequence", 0),
        "completed": any(item.get("event") == "done" for item in streams[stream_id].get("events", [])),
    }


# ─── Utils ─────────────────────────────────────────────────

class SSEEventEncoder:
    """为单次消息流生成稳定 ID、连续序号并保存可补发事件。"""

    def __init__(self, stream_id: str, request_message_id: int | None = None, persist=None):
        self.stream_id = stream_id
        self.request_message_id = request_message_id
        self.sequence = 0
        self.persist = persist

    def encode(self, event: str, data: dict) -> str:
        self.sequence += 1
        event_id = f"{self.stream_id}:{self.sequence}"
        payload = {
            **data,
            "stream_id": self.stream_id,
            "sequence": self.sequence,
            "event_id": event_id,
        }
        if self.request_message_id is not None:
            payload["request_message_id"] = self.request_message_id
        record = {
            "id": event_id,
            "event": event,
            "sequence": self.sequence,
            "data": payload,
        }
        if self.persist:
            try:
                self.persist(record)
            except Exception:
                logger.exception("[Chat] SSE 事件持久化失败，当前事件仍继续发送")
        return (
            f"id: {event_id}\n"
            f"event: {event}\n"
            f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        )


_active_sse_encoder: ContextVar[Optional[SSEEventEncoder]] = ContextVar(
    "active_sse_encoder", default=None
)


def _sse_event(event: str, data: dict) -> str:
    encoder = _active_sse_encoder.get()
    if encoder is None:
        # 仅供独立单元测试/兼容调用；真实请求总会设置流级 encoder。
        encoder = SSEEventEncoder(f"standalone-{uuid.uuid4().hex[:12]}")
    return encoder.encode(event, data)


def _append_sse_record(context_json: dict | None, record: dict) -> dict:
    """纯函数方式合并事件，便于测试并避免 SQLAlchemy JSON 原地变更。"""
    context = dict(context_json or {})
    streams = dict(context.get("sse_streams") or {})
    stream_id = record["data"]["stream_id"]
    stream = dict(streams.get(stream_id) or {})
    events = list(stream.get("events") or [])
    events.append(record)
    stream.update({
        "request_message_id": record["data"].get("request_message_id"),
        "last_sequence": record["sequence"],
        "events": events[-100:],
    })
    streams[stream_id] = stream

    # 每个会话最多保留最近 3 次消息流，限制 JSON 字段增长。
    while len(streams) > 3:
        streams.pop(next(iter(streams)))
    context["sse_streams"] = streams
    return context


def _persist_sse_event(session_id: int, record: dict) -> None:
    # StreamingResponse 可能晚于请求依赖释放才开始迭代，因此不能复用请求级 DB Session。
    event_db = SessionLocal()
    try:
        session = (
            event_db.query(ChatSession)
            .filter(ChatSession.id == session_id)
            .with_for_update()
            .first()
        )
        if not session:
            raise RuntimeError(f"聊天会话不存在：{session_id}")
        session.context_json = _append_sse_record(session.context_json, record)
        event_db.commit()
    except Exception:
        event_db.rollback()
        raise
    finally:
        event_db.close()


def _get_replay_events(context: dict, stream_id: str, after_sequence: int) -> list[dict]:
    stream = (context.get("sse_streams") or {}).get(stream_id) or {}
    return [
        event for event in stream.get("events", [])
        if int(event.get("sequence", 0)) > after_sequence
    ]


def _flatten_profile(profile: dict) -> dict:
    """将服务层的分区画像转换为 Agent 使用的扁平结构。"""
    return {
        **profile.get("basic", {}),
        **profile.get("preferences", {}),
        "projects": profile.get("projects", []),
        "skills": profile.get("skills", []),
        "education": profile.get("education", []),
        "experiences": profile.get("experiences", []),
        "resumes": profile.get("resumes", []),
    }


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
