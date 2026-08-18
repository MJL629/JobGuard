"""Resume API."""

import logging
import os
from fastapi import APIRouter, Depends, File, Query, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.services.resume_service import resume_service
from app.auth import get_current_user_id
from app.services.resume_template_service import resume_template_service
from app.services.agent_observability_service import agent_observability_service

router = APIRouter()
logger = logging.getLogger(__name__)


class GenerateResumeRequest(BaseModel):
    user_id: int | None = None  # 兼容旧客户端；实际身份来自 access token
    job_id: int | None = None
    job_info: dict | None = None
    options: dict | None = None


@router.get("/templates")
async def list_resume_templates(
    current_user_id: int = Depends(get_current_user_id),
):
    """List the four verified built-in layouts available for generation."""
    return {"code": 0, "data": {"items": resume_template_service.list_for_user(current_user_id)}}


@router.post("/templates/custom")
async def upload_custom_resume_template(
    file: UploadFile = File(...),
    current_user_id: int = Depends(get_current_user_id),
):
    try:
        item = resume_template_service.save_custom(
            current_user_id, file.filename, await file.read()
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "data": item}


@router.post("/generate")
async def generate_resume(
    req: GenerateResumeRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    run = agent_observability_service.start_run(
        db,
        user_id=current_user_id,
        session_id=None,
        workflow="resume_generation",
        intent="generate_targeted_resume",
        input_summary=f"job_id={req.job_id or 'custom'}",
        context_snapshot={
            "job_id": req.job_id,
            "template_id": (req.options or {}).get("template_id"),
            "has_custom_job_info": bool(req.job_info),
        },
    )
    try:
        agent_observability_service.update_step(db, run, "grounding_and_generation")
        result = await resume_service.generate_resume(
            db,
            user_id=current_user_id,
            job_id=req.job_id,
            job_info=req.job_info,
            options=req.options,
        )
    except Exception as exc:
        logger.exception(
            "[ResumeAPI] generation failed, user=%s, error_type=%s",
            current_user_id,
            type(exc).__name__,
        )
        try:
            agent_observability_service.fail_run(db, run, "grounding_and_generation", exc)
        except Exception:
            logger.exception("[ResumeAPI] failed to persist Agent run failure")
        return {
            "code": 1,
            "message": "简历生成过程中出现内部错误，未保存失败结果。请稍后重试。",
            "run_id": run.id,
        }

    if "error" in result:
        generation_error = RuntimeError(str(result["error"]))
        try:
            agent_observability_service.fail_run(
                db, run, "grounding_and_generation", generation_error
            )
        except Exception:
            logger.exception("[ResumeAPI] failed to persist rejected generation")
        return {"code": 1, "message": result["error"], "run_id": run.id}

    try:
        agent_observability_service.complete_run(
            db,
            run,
            f"resume_id={result.get('resume_id')}; template={result.get('template_id')}",
        )
    except Exception:
        logger.exception("[ResumeAPI] failed to persist Agent run completion")
    return {"code": 0, "data": {**result, "run_id": run.id}}


@router.get("/history")
async def get_history(
    user_id: int | None = Query(None),
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    items = resume_service.get_history(db, current_user_id)
    return {"code": 0, "data": {"items": items}}


@router.get("/{resume_id}")
async def get_resume(
    resume_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    resume = resume_service.get_resume(db, resume_id)
    if not resume:
        return {"code": 1, "message": "简历记录不存在"}
    if resume.get("user_id") != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该简历")
    return {"code": 0, "data": resume}


@router.get("/{resume_id}/download")
async def download_resume(
    resume_id: int,
    format: str = Query("pdf", pattern="^(pdf|docx|markdown)$"),
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    resume = resume_service.get_resume(db, resume_id)
    if not resume:
        return {"code": 1, "message": "简历记录不存在"}
    if resume.get("user_id") != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该简历")

    selected_path = resume.get("docx_path") if format == "docx" else resume.get("pdf_path")
    if format != "markdown" and selected_path and os.path.exists(selected_path):
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if format == "docx"
            else "application/pdf" if selected_path.endswith(".pdf") else "text/markdown"
        )
        return FileResponse(
            selected_path,
            media_type=media_type,
            filename=os.path.basename(selected_path),
        )

    # Fallback: return markdown as text
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        resume.get("resume_markdown", ""),
        media_type="text/markdown",
    )
