"""账号注册、登录与身份校验。"""

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.models.base import get_db
from app.models.user import User, UserProfile, UserPreference

router = APIRouter()
bearer = HTTPBearer(auto_error=False)
ALGORITHM = "HS256"


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return f"pbkdf2_sha256$210000${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt_hex, digest_hex = stored.split("$", 3)
            candidate = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
            ).hex()
            return hmac.compare_digest(candidate, digest_hex)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)


def _user_payload(user: User) -> dict:
    return {"id": user.id, "username": user.username, "email": user.email}


def _issue_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user.id), "username": user.username, "iat": now, "exp": now + timedelta(days=7)},
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        payload = jwt.decode(credentials.credentials, settings.secret_key, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub", 0))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
    user = db.query(User).filter(User.id == user_id, User.is_active == 1).first()
    if not user:
        raise HTTPException(status_code=401, detail="账号不存在或已停用")
    return user


def require_own_user(user_id: int, current_user: User) -> None:
    if int(current_user.id) != int(user_id):
        raise HTTPException(status_code=403, detail="不能访问其他账号的数据")


@router.post("/register")
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册"""
    username = req.username.strip()
    if len(username) < 2 or len(username) > 50:
        raise HTTPException(status_code=400, detail="用户名长度需为 2 至 50 个字符")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少需要 6 个字符")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(username=username, email=req.email, password_hash=_hash_password(req.password))
    db.add(user)
    db.flush()
    db.add(UserProfile(user_id=user.id, profile_completeness=0))
    db.add(UserPreference(user_id=user.id))
    db.commit()
    db.refresh(user)
    return {"message": "注册成功", "token": _issue_token(user), "user": _user_payload(user)}


@router.post("/login")
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    user = db.query(User).filter(User.username == req.username.strip()).first()
    if not user or not _verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    return {"message": "登录成功", "token": _issue_token(user), "user": _user_payload(user)}


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return {"user": _user_payload(current_user)}
