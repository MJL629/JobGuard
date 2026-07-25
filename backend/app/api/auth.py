"""
认证接口
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.base import get_db

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册"""
    # TODO: 实现注册逻辑
    return {"message": "注册接口已就绪（待实现）", "username": req.username}


@router.post("/login")
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    # TODO: 实现登录逻辑
    return {"message": "登录接口已就绪（待实现）", "token": "mock_token_xxx"}
