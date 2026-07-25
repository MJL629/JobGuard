"""
用户画像接口
"""

import logging
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.services.profile_service import profile_service

logger = logging.getLogger(__name__)

router = APIRouter()


class AddProjectRequest(BaseModel):
    project_name: str
    role: str | None = None
    description: str | None = None
    tech_stack: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    highlights: str | None = None
    project_url: str | None = None


# ─── 画像查询 ─────────────────────────────────────────────────────────

@router.get("/{user_id}")
async def get_profile(user_id: int, db: Session = Depends(get_db)):
    """获取用户完整画像"""
    profile = profile_service.get_full_profile(db, user_id)
    return {
        "code": 0,
        "data": profile,
    }


# ─── 简历上传 ─────────────────────────────────────────────────────────

@router.post("/{user_id}/upload-resume")
async def upload_resume(
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传简历文件并解析"""
    # 读取文件内容
    content = await file.read()

    # 根据文件类型处理
    filename = file.filename or "resume"
    resume_text = ""

    if filename.endswith(".pdf"):
        # PDF 解析
        try:
            import io
            from pdf2image import convert_from_bytes
            # 对于纯文本 PDF，尝试直接提取
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(io.BytesIO(content))
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        resume_text += text + "\n"
            except ImportError:
                pass
        except Exception as e:
            logger.warning(f"PDF 解析失败: {e}")

    elif filename.endswith((".txt", ".md")):
        resume_text = content.decode("utf-8", errors="ignore")

    else:
        # 尝试作为文本读取
        try:
            resume_text = content.decode("utf-8", errors="ignore")
        except Exception:
            raise HTTPException(status_code=400, detail="不支持的文件格式，请上传 PDF/TXT/MD")

    if not resume_text or len(resume_text.strip()) < 50:
        raise HTTPException(status_code=400, detail="无法从文件中提取有效文本，请确认文件内容")

    # 处理简历
    result = await profile_service.process_resume(
        db, user_id, resume_text,
        file_path=f"uploads/{user_id}/{filename}",
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return {
        "code": 0,
        "data": {
            "summary": {
                "degree": result.get("parsed", {}).get("degree"),
                "school": result.get("parsed", {}).get("school"),
                "projects_count": len(result.get("parsed", {}).get("projects", [])),
                "skills_count": len(result.get("parsed", {}).get("skills", [])),
            },
            "completeness": result["completeness"],
            "missing_fields": result["missing_fields"],
        },
    }


# ─── 项目经历 ─────────────────────────────────────────────────────────

@router.post("/{user_id}/projects")
async def add_project(
    user_id: int,
    req: AddProjectRequest,
    db: Session = Depends(get_db),
):
    """添加项目经历"""
    result = profile_service.add_project(db, user_id, req.model_dump())
    return {
        "code": 0,
        "data": result,
    }


@router.delete("/{user_id}/projects/{project_id}")
async def delete_project(
    user_id: int,
    project_id: int,
    db: Session = Depends(get_db),
):
    """删除项目经历"""
    from app.models.user import UserProject
    project = (
        db.query(UserProject)
        .filter(UserProject.id == project_id, UserProject.user_id == user_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    db.delete(project)
    db.commit()

    return {"code": 0, "message": "删除成功"}
