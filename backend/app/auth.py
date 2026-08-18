"""
JWT 认证模块

- 生成和验证 JWT token
- 密码哈希（bcrypt 风格，使用 hashlib）
- 用户注册/登录逻辑
"""

import hashlib
import hmac
import secrets
import time
import logging
from typing import Optional

import jwt
from app.config import settings

logger = logging.getLogger(__name__)

# ─── 配置 ──────────────────────────────────────────────────────────────

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE = 3600 * 24     # 24 小时
REFRESH_TOKEN_EXPIRE = 3600 * 24 * 30  # 30 天


# ─── 密码处理 ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """
    使用 HMAC-SHA256 哈希密码（生产环境应使用 bcrypt/argon2）。
    盐值随机生成并存储在哈希结果中。
    """
    salt = secrets.token_hex(16)
    key = settings.secret_key.encode("utf-8")
    h = hmac.new(key, f"{salt}:{password}".encode("utf-8"), hashlib.sha256)
    return f"{salt}${h.hexdigest()}"


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码"""
    try:
        salt, expected = password_hash.split("$", 1)
        key = settings.secret_key.encode("utf-8")
        h = hmac.new(key, f"{salt}:{password}".encode("utf-8"), hashlib.sha256)
        return hmac.compare_digest(h.hexdigest(), expected)
    except Exception:
        return False


# ─── JWT Token ─────────────────────────────────────────────────────────

def create_access_token(user_id: int, username: str) -> str:
    """创建访问 token"""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXPIRE,
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int, username: str) -> str:
    """创建刷新 token"""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + REFRESH_TOKEN_EXPIRE,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """解码并验证 token"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("[Auth] Token 已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"[Auth] Token 无效: {e}")
        return None


def get_user_id_from_token(token: str) -> Optional[int]:
    """从 token 中提取 user_id"""
    payload = decode_token(token)
    if payload:
        try:
            return int(payload.get("sub", 0))
        except (ValueError, TypeError):
            return None
    return None


# ─── 认证依赖（FastAPI Depends） ──────────────────────────────────────

from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer(auto_error=False)


async def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    """
    FastAPI 依赖：从请求中提取当前用户 ID。

    所有业务接口必须从 access token 获取当前用户，禁止使用默认用户。
    """
    if credentials:
        user_id = get_user_id_from_token(credentials.credentials)
        if user_id:
            return user_id
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    raise HTTPException(status_code=401, detail="请先登录")


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    """
    FastAPI 依赖：强制要求认证（生产环境用）。
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = get_user_id_from_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    return user_id
