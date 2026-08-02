"""
企业接口
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.base import get_db

router = APIRouter()


@router.get("/{company_id}")
async def get_company(company_id: int, db: Session = Depends(get_db)):
    """企业详情"""
    return {"message": "企业详情接口已就绪（待实现）", "company_id": company_id}


@router.get("/search")
async def search_companies(
    q: str = Query(..., description="搜索关键词"),
    db: Session = Depends(get_db),
):
    """搜索企业"""
    return {"message": "搜索企业接口已就绪（待实现）", "query": q, "results": []}
