"""
Jobs API
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.services.job_service import job_service

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
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return {
        "code": 0,
        "message": "Recommendation engine under development",
        "data": {"items": [], "total": 0},
    }


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
