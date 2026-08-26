"""
Resume API
"""

import os
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.services.resume_service import resume_service
from app.models.user import User
from app.api.auth import get_current_user, require_own_user

router = APIRouter()


class GenerateResumeRequest(BaseModel):
    user_id: int
    job_id: int | None = None
    job_info: dict | None = None
    options: dict | None = None


@router.post("/generate")
async def generate_resume(
    req: GenerateResumeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_own_user(req.user_id, current_user)
    result = await resume_service.generate_resume(
        db,
        user_id=req.user_id,
        job_id=req.job_id,
        job_info=req.job_info,
        options=req.options,
    )

    if "error" in result:
        return {"code": 1, "message": result["error"]}

    return {"code": 0, "data": result}


@router.get("/user/history")
async def get_user_history(
    user_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_own_user(user_id, current_user)
    items = resume_service.get_history(db, user_id)
    return {"code": 0, "data": {"items": items}}


@router.get("/{resume_id}")
async def get_resume(resume_id: int, db: Session = Depends(get_db)):
    resume = resume_service.get_resume(db, resume_id)
    if not resume:
        return {"code": 1, "message": "Resume not found"}
    return {"code": 0, "data": resume}


@router.get("/{resume_id}/download")
async def download_resume(resume_id: int, db: Session = Depends(get_db)):
    resume = resume_service.get_resume(db, resume_id)
    if not resume:
        return {"code": 1, "message": "Resume not found"}

    pdf_path = resume.get("pdf_path")
    if pdf_path and os.path.exists(pdf_path):
        return FileResponse(
            pdf_path,
            media_type="application/pdf" if pdf_path.endswith(".pdf") else "text/markdown",
            filename=os.path.basename(pdf_path),
        )

    # Fallback: return markdown as text
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        resume.get("resume_markdown", ""),
        media_type="text/markdown",
    )
