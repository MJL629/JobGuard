"""Company search and source-bound evidence APIs."""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user_id
from app.models.base import get_db
from app.services.company_evidence_service import (
    CompanyEvidenceError,
    company_evidence_service,
)

router = APIRouter()


class CompanyEvidenceCreate(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    evidence_type: Literal[
        "registry",
        "operating_abnormality",
        "administrative_penalty",
        "social_insurance",
        "labor_dispute",
        "reputation",
        "official_job",
        "public_transaction",
        "other",
    ]
    source_kind: Literal["official", "job_board", "media", "user_provided"]
    source_name: str = Field(min_length=2, max_length=200)
    source_url: str = Field(min_length=8, max_length=1000)
    title: str = Field(min_length=2, max_length=300)
    content_excerpt: str | None = Field(default=None, max_length=5000)
    structured_data: dict[str, Any] = Field(default_factory=dict)
    published_at: datetime | None = None
    observed_at: datetime | None = None


@router.get("/search")
async def search_companies(
    q: str = Query(..., min_length=1, max_length=100, description="搜索关键词"),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Search companies already known to JobGuard and show evidence coverage."""
    return {
        "code": 0,
        "data": {
            "query": q,
            "items": company_evidence_service.search(db, q, limit=limit),
        },
    }


@router.post("/evidence")
async def create_company_evidence(
    request: CompanyEvidenceCreate,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Store a citation. Verification is computed from the source host, not client input."""
    try:
        evidence, created = company_evidence_service.add_evidence(
            db,
            request.model_dump(),
            created_by_user_id=current_user_id,
        )
        db.commit()
        db.refresh(evidence)
    except CompanyEvidenceError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "code": 0,
        "data": {
            "id": evidence.id,
            "company_id": evidence.company_id,
            "created": created,
            "is_verified": bool(evidence.is_verified),
            "verification_level": evidence.verification_level,
            "source_url": evidence.source_url,
        },
    }


@router.get("/{company_id}")
async def get_company(company_id: int, db: Session = Depends(get_db)):
    """Return company data together with source-level citations."""
    company = company_evidence_service.get_company(db, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="企业不存在")
    return {"code": 0, "data": company}
