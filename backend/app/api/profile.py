"""
用户画像接口
"""

import logging
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.models.base import SessionLocal, get_db
from app.services.profile_service import profile_service
from app.services.resume_file_service import ResumeFileError, resume_file_service
from app.models.resume import UserResume
from app.auth import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter()


def _resume_status_payload(db: Session, user_id: int, resume: UserResume) -> dict:
    parsed = resume.structured_data or {}
    profile = profile_service.get_full_profile(db, user_id)
    return {
        "resume": profile_service._resume_to_dict(resume),
        "parse_status": resume.parse_status,
        "profile_updated": resume.parse_status == "parsed",
        "completeness": profile.get("completeness", 0),
        "summary": {
            "degree": parsed.get("degree"),
            "school": parsed.get("school"),
            "projects_count": len(parsed.get("projects", [])),
            "skills_count": len(parsed.get("skills", [])),
        },
        "follow_up_questions": profile_service.build_resume_follow_up_questions(
            profile, parsed
        ),
    }


async def _process_resume_background(resume_id: int, user_id: int) -> None:
    """Parse a stored resume outside the upload request lifecycle."""
    db = SessionLocal()
    try:
        resume = (
            db.query(UserResume)
            .filter(UserResume.id == resume_id, UserResume.user_id == user_id)
            .first()
        )
        if resume is None or resume.parse_status == "parsed":
            return

        resume.parse_status = "processing"
        resume.parse_error = None
        resume.updated_at = datetime.utcnow()
        db.commit()

        result = await profile_service.process_resume(
            db,
            user_id,
            resume.extracted_text or "",
            file_path=resume.stored_path,
            source_resume_id=resume.id,
        )
        resume = db.query(UserResume).filter(UserResume.id == resume_id).first()
        if resume is None:
            return
        resume.structured_data = (result or {}).get("parsed") or None
        resume.parse_status = (
            "parsed" if result and "error" not in result else "needs_review"
        )
        resume.parse_error = (result or {}).get("error")
        resume.updated_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("简历后台结构化解析失败，user=%s resume=%s", user_id, resume_id)
        try:
            resume = db.query(UserResume).filter(UserResume.id == resume_id).first()
            if resume is not None:
                resume.parse_status = "needs_review"
                resume.parse_error = (
                    "结构化解析暂时失败，原文件和已识别文字已经保存，可重新解析或手动补充画像"
                )
                resume.updated_at = datetime.utcnow()
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("简历后台失败状态保存失败，resume=%s", resume_id)
    finally:
        db.close()


class AddProjectRequest(BaseModel):
    project_name: str
    role: str | None = None
    description: str | None = None
    tech_stack: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    highlights: str | None = None
    project_url: str | None = None


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = None
    gender: str | None = None
    birth_year: int | None = None
    degree: str | None = None
    major: str | None = None
    school: str | None = None
    graduation_year: int | None = None
    current_city: str | None = None
    years_of_experience: int | None = None
    expected_salary_min: int | None = None
    expected_salary_max: int | None = None
    preferred_job_types: list[str] | None = None
    preferred_sub_categories: list[str] | None = None
    preferred_locations: list[str] | None = None
    preferred_industries: list[str] | None = None
    overtime_tolerance: str | None = None
    weekend_preference: str | None = None
    holiday_preference: str | None = None
    labor_intensity: str | None = None
    remote_work: str | None = None
    company_scale_pref: str | None = None


class AddExperienceRequest(BaseModel):
    experience_type: str = "project"
    title: str
    organization: str | None = None
    role: str | None = None
    description: str | None = None
    actions: str | None = None
    achievements: str | None = None
    tech_stack: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None


def _ensure_owner(requested_user_id: int, current_user_id: int):
    if requested_user_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问其他用户的画像")


# ─── 画像查询 ─────────────────────────────────────────────────────────

@router.get("/me")
async def get_my_profile(
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return {"code": 0, "data": profile_service.get_full_profile(db, current_user_id)}


@router.patch("/me")
async def update_my_profile(
    req: ProfileUpdateRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    updates = req.model_dump(exclude_none=True)
    profile = await profile_service.update_profile(db, current_user_id, updates)
    return {"code": 0, "data": profile_service.get_full_profile(db, current_user_id)}


@router.post("/me/upload-resume")
async def upload_my_resume(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return await upload_resume(
        current_user_id, background_tasks, file, db, current_user_id
    )

@router.get("/{user_id}")
async def get_profile(
    user_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """获取用户完整画像"""
    _ensure_owner(user_id, current_user_id)
    profile = profile_service.get_full_profile(db, user_id)
    return {
        "code": 0,
        "data": profile,
    }


# ─── 简历上传 ─────────────────────────────────────────────────────────

@router.post("/{user_id}/upload-resume")
async def upload_resume(
    user_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    """校验并保存简历原文件，再提取文字建立画像。"""
    _ensure_owner(user_id, current_user_id)
    content = await file.read()
    try:
        prepared = await run_in_threadpool(
            resume_file_service.prepare, user_id, file.filename, content
        )
        existing = (
            db.query(UserResume)
            .filter(UserResume.user_id == user_id, UserResume.sha256 == prepared.sha256)
            .first()
        )
        if existing:
            if existing.parse_status in {"pending", "needs_review"}:
                existing.parse_status = "pending"
                existing.parse_error = None
                existing.updated_at = datetime.utcnow()
                db.commit()
                background_tasks.add_task(
                    _process_resume_background, existing.id, user_id
                )
            return {
                "code": 0,
                "message": "这份简历已经保存，无需重复上传",
                "data": {
                    **_resume_status_payload(db, user_id, existing),
                    "file": prepared.public_metadata(),
                    "missing_fields": [],
                },
            }
        await run_in_threadpool(resume_file_service.save, prepared)
    except ResumeFileError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.message, "code": exc.code},
        ) from exc
    except Exception as exc:
        logger.exception("简历原文件保存失败，user=%s", user_id)
        raise HTTPException(status_code=500, detail="简历文件保存失败，请稍后重试") from exc

    is_first_resume = db.query(UserResume).filter(UserResume.user_id == user_id).count() == 0
    saved_resume = UserResume(
        user_id=user_id,
        original_name=prepared.original_name,
        stored_path=prepared.relative_path,
        sha256=prepared.sha256,
        media_type=prepared.media_type,
        parser=prepared.parser,
        ocr_used=prepared.ocr_used,
        extracted_text=prepared.text,
        extracted_chars=len(prepared.text),
        parse_status="pending",
        is_primary=is_first_resume,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(saved_resume)
    try:
        db.commit()
        db.refresh(saved_resume)
    except Exception as exc:
        db.rollback()
        await run_in_threadpool(resume_file_service.discard, prepared)
        logger.exception("简历记录保存失败，user=%s", user_id)
        raise HTTPException(status_code=500, detail="简历记录保存失败，请稍后重试") from exc

    background_tasks.add_task(_process_resume_background, saved_resume.id, user_id)

    return {
        "code": 0,
        "message": "简历已保存，正在后台解析",
        "data": {
            **_resume_status_payload(db, user_id, saved_resume),
            "missing_fields": [],
            "file": prepared.public_metadata(),
        },
    }


@router.get("/me/resumes")
async def list_my_resumes(
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return {"code": 0, "data": {"items": profile_service.list_resumes(db, current_user_id)}}


@router.get("/me/resumes/{resume_id}")
async def get_my_resume_status(
    resume_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    resume = (
        db.query(UserResume)
        .filter(UserResume.id == resume_id, UserResume.user_id == current_user_id)
        .first()
    )
    if resume is None:
        raise HTTPException(status_code=404, detail="简历不存在")
    return {
        "code": 0,
        "data": _resume_status_payload(db, current_user_id, resume),
    }


@router.patch("/me/resumes/{resume_id}/primary")
async def set_my_primary_resume(
    resume_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    item = profile_service.set_primary_resume(db, current_user_id, resume_id)
    if item is None:
        raise HTTPException(status_code=404, detail="简历不存在")
    return {"code": 0, "data": item}


@router.post("/me/experiences")
async def add_my_experience(
    req: AddExperienceRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        item = profile_service.add_experience(db, current_user_id, req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"code": 0, "data": item}


# ─── 项目经历 ─────────────────────────────────────────────────────────

@router.post("/{user_id}/projects")
async def add_project(
    user_id: int,
    req: AddProjectRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """添加项目经历"""
    _ensure_owner(user_id, current_user_id)
    result = profile_service.add_project(db, user_id, req.model_dump())
    return {
        "code": 0,
        "data": result,
    }


@router.delete("/{user_id}/projects/{project_id}")
async def delete_project(
    user_id: int,
    project_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """删除项目经历"""
    _ensure_owner(user_id, current_user_id)
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
