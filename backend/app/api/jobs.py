"""Jobs API."""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.models.base import get_db
from app.services.job_service import job_service
from app.services.resume_file_service import ResumeFileError, resume_file_service
from app.auth import get_current_user_id
from app.llm.gateway import llm_gateway
from app.models.chat import ChatSession
from app.services.agent_observability_service import agent_observability_service

router = APIRouter()
logger = logging.getLogger(__name__)


class AnalyzeRequest(BaseModel):
    user_id: int | None = None  # 兼容旧客户端；实际身份来自 access token
    url: str | None = None
    text: str | None = None
    message_type: str = "job_link"
    job_id: int | None = None


@router.get("")
async def list_jobs(
    category: str | None = Query(None),
    sub_category: str | None = Query(None),
    location: str | None = Query(None),
    salary_min: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = job_service.list_jobs(
        db, category=category, sub_category=sub_category,
        location=location, salary_min=salary_min,
        page=page, page_size=page_size,
    )
    return {"code": 0, "data": result}


@router.get("/recommend")
async def recommend_jobs(
    user_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = job_service.recommend_jobs(
        db, current_user_id, page=page, page_size=page_size,
    )
    return {"code": 0, "data": result}


@router.post("/analyze")
async def analyze_job(
    req: AnalyzeRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    text = req.text or req.url or ""
    if not text:
        return {"code": 1, "message": "请提供完整岗位信息"}

    run = agent_observability_service.start_run(
        db,
        user_id=current_user_id,
        session_id=None,
        workflow="job_analysis",
        intent="analyze_job",
        input_summary=f"input_type={req.message_type}; chars={len(text)}",
        context_snapshot={"input_type": req.message_type, "input_chars": len(text)},
    )
    try:
        agent_observability_service.update_step(db, run, "parse_and_verify")
        report = await job_service.analyze_job(
            db,
            current_user_id,
            text,
            input_type=req.message_type,
            existing_job_id=req.job_id,
        )
    except Exception as exc:
        try:
            agent_observability_service.fail_run(db, run, "parse_and_verify", exc)
        except Exception:
            logger.exception("[JobsAPI] failed to persist Agent run failure")
        logger.exception("[JobsAPI] analysis failed, error_type=%s", type(exc).__name__)
        return {
            "code": 1,
            "message": "岗位分析失败，请检查输入内容或稍后重试。",
            "run_id": run.id,
        }

    if "error" in report:
        analysis_error = RuntimeError(str(report["error"]))
        try:
            agent_observability_service.fail_run(db, run, "parse_and_verify", analysis_error)
        except Exception:
            logger.exception("[JobsAPI] failed to persist rejected analysis")
        return {"code": 1, "message": report["error"], "run_id": run.id}

    try:
        agent_observability_service.complete_run(
            db,
            run,
            f"job_id={report.get('job_id')}; evidence={len(report.get('sources') or [])}",
        )
    except Exception:
        logger.exception("[JobsAPI] failed to persist Agent run completion")
    return {"code": 0, "data": {**report, "run_id": run.id}}


@router.post("/analyze-image")
async def analyze_job_image(
    file: UploadFile = File(...),
    session_id: int | None = Form(None),
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """使用本地 OCR 识别岗位截图，再进入同一套真实分析链路。"""
    content = await file.read()
    try:
        prepared = await run_in_threadpool(
            resume_file_service.prepare, current_user_id, file.filename, content
        )
    except ResumeFileError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.message, "code": exc.code},
        ) from exc
    if not prepared.media_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="岗位截图仅支持 PNG、JPG、JPEG 或 WEBP")

    vision_text = ""
    vision_error = None
    try:
        vision_text = await llm_gateway.vision(
            content,
            prepared.media_type,
            "请完整识别这张招聘岗位截图。先逐项写出公司全称、岗位名称、地点、薪资、职责、要求、福利、工时和任何风险措辞，再给出完整可复制的岗位原文。不要猜测截图中看不清的内容。",
        )
    except Exception as exc:
        # Do not expose provider credentials or full upstream responses in logs/API.
        vision_error = f"{type(exc).__name__}: 多模态识别暂不可用，已自动改用本地 OCR"
        logger.warning("[Jobs] vision analysis fell back to local OCR (%s)", type(exc).__name__)

    analysis_text = vision_text.strip() or prepared.text
    report = await job_service.analyze_job(
        db,
        current_user_id,
        analysis_text,
        input_type="screenshot_text",
    )
    if "error" in report:
        return {"code": 1, "message": report["error"]}
    if session_id is not None:
        session = (
            db.query(ChatSession)
            .filter(ChatSession.id == session_id, ChatSession.user_id == current_user_id)
            .first()
        )
        if session is None:
            raise HTTPException(status_code=404, detail="当前对话会话不存在")
        context = dict(session.context_json or {})
        context["last_job_analysis"] = {
            "job_info": report.get("job_info") or {},
            "report": report.get("report") or {},
            "job_id": report.get("job_id"),
            "source": "image",
            "input_text": analysis_text[:12000],
        }
        session.context_json = context
        db.commit()

    return {
        "code": 0,
        "data": {
            **report,
            "image_ocr": {
                "original_name": prepared.original_name,
                "parser": prepared.parser,
                "extracted_chars": len(prepared.text),
                "vision_model": "glm-4v-flash" if vision_text else None,
                "analysis_mode": "multimodal" if vision_text else "local_ocr",
                "vision_fallback_reason": vision_error if not vision_text else None,
            },
        },
    }


@router.get("/{job_id}")
async def get_job(job_id: int, db: Session = Depends(get_db)):
    job = job_service.get_job_detail(db, job_id)
    if not job:
        return {"code": 1, "message": "岗位不存在"}
    return {"code": 0, "data": job}


@router.get("/{job_id}/analysis")
async def get_job_analysis(
    job_id: int,
    user_id: int | None = Query(None),
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    analysis = job_service.get_job_analysis(db, job_id, current_user_id)
    if not analysis:
        return {"code": 1, "message": "尚未生成该岗位的分析记录"}
    return {"code": 0, "data": analysis}
