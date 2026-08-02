"""
认证接口 — 完整实现

POST /api/auth/register — 用户注册
POST /api/auth/login    — 用户登录（返回 JWT）
POST /api/auth/refresh  — 刷新 token
GET  /api/auth/me       — 获取当前用户信息
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.models.user import User
from app.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_token, get_current_user_id,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: int
    username: str


# ─── 注册 ─────────────────────────────────────────────────────────

@router.post("/register")
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册"""
    # 检查用户名是否已存在
    existing = db.query(User).filter(User.username == req.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")

    # 创建用户
    user = User(
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        is_active=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"[Auth] 新用户注册: {req.username} (id={user.id})")

    # 直接返回 token（注册即登录）
    return TokenResponse(
        access_token=create_access_token(user.id, user.username),
        refresh_token=create_refresh_token(user.id, user.username),
        user_id=user.id,
        username=user.username,
    )


# ─── 登录 ─────────────────────────────────────────────────────────

@router.post("/login")
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    user = db.query(User).filter(User.username == req.username).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    logger.info(f"[Auth] 用户登录: {req.username} (id={user.id})")

    return TokenResponse(
        access_token=create_access_token(user.id, user.username),
        refresh_token=create_refresh_token(user.id, user.username),
        user_id=user.id,
        username=user.username,
    )


# ─── 刷新 Token ───────────────────────────────────────────────────

@router.post("/refresh")
async def refresh_token(req: RefreshRequest):
    """刷新 access token"""
    payload = decode_token(req.refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="无效的 refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="token 类型错误")

    user_id = int(payload.get("sub", 0))
    username = payload.get("username", "")

    return TokenResponse(
        access_token=create_access_token(user_id, username),
        refresh_token=create_refresh_token(user_id, username),
        user_id=user_id,
        username=username,
    )


# ─── 当前用户信息 ────────────────────────────────────────────────

@router.get("/me")
async def get_me(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """获取当前登录用户信息"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": bool(user.is_active),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
