"""
Jobs API
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.services.job_service import job_service
from app.models.user import User
from app.api.auth import get_current_user, require_own_user

router = APIRouter()


class AnalyzeRequest(BaseModel):
    user_id: int
    url: str | None = None
    text: str | None = None
    message_type: str = "job_link"


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
    user_id: int = Query(...),
    category: str | None = Query(None),
    sub_category: str | None = Query(None),
    location: str | None = Query(None),
    salary_min: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_own_user(user_id, current_user)
    result = job_service.recommend_jobs(
        db, user_id, page=page, page_size=page_size,
        category=category, sub_category=sub_category,
        location=location, salary_min_filter=salary_min,
    )
    return {"code": 0, "data": result}


@router.post("/analyze")
async def analyze_job(req: AnalyzeRequest, db: Session = Depends(get_db)):
    text = req.text or req.url or ""
    if not text:
        return {"code": 1, "message": "No job info provided"}

    report = await job_service.analyze_job(
        db, req.user_id, text, input_type=req.message_type,
    )

    if "error" in report:
        return {"code": 1, "message": report["error"]}

    return {"code": 0, "data": report}


@router.get("/analysis/history")
async def get_analysis_history(
    user_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_own_user(user_id, current_user)
    return {"code": 0, "data": {"items": job_service.get_analysis_history(db, user_id)}}


@router.get("/analysis/record/{analysis_id}")
async def get_analysis_record(
    analysis_id: int,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_own_user(user_id, current_user)
    analysis = job_service.get_analysis_by_id(db, analysis_id, user_id)
    if not analysis:
        return {"code": 1, "message": "Analysis not found"}
    return {"code": 0, "data": analysis}


@router.post("/{job_id}/analyze-fast")
async def analyze_existing_job_fast(
    job_id: int,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_own_user(user_id, current_user)
    report = job_service.analyze_existing_job_fast(db, user_id, job_id)
    if "error" in report:
        return {"code": 1, "message": report["error"]}
    return {"code": 0, "data": report}


@router.get("/{job_id}")
async def get_job(job_id: int, db: Session = Depends(get_db)):
    job = job_service.get_job_detail(db, job_id)
    if not job:
        return {"code": 1, "message": "Job not found"}
    return {"code": 0, "data": job}


@router.get("/{job_id}/analysis")
async def get_job_analysis(job_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    analysis = job_service.get_job_analysis(db, job_id, user_id)
    if not analysis:
        return {"code": 1, "message": "Analysis not found"}
    return {"code": 0, "data": analysis}
