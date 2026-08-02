"""
JobGuard 中间件

- MonitoringMiddleware: 请求监控（延迟、状态码、错误）
- AuthMiddleware: JWT 认证（开发阶段放行）
"""

import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.monitoring import metrics


class MonitoringMiddleware(BaseHTTPMiddleware):
    """请求监控中间件 — 自动记录所有 API 请求的延迟和状态"""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        try:
            response = await call_next(request)
            duration_ms = (time.time() - start) * 1000
            metrics.record_request(
                path=request.url.path,
                method=request.method,
                status=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            metrics.record_error(type(e).__name__, request.url.path)
            metrics.record_request(
                path=request.url.path,
                method=request.method,
                status=500,
                duration_ms=duration_ms,
            )
            raise


class AuthMiddleware(BaseHTTPMiddleware):
    """JWT 认证中间件（开发阶段放行所有请求）"""

    PUBLIC_PATHS = [
        "/api/auth/", "/health", "/docs", "/openapi.json",
        "/metrics", "/", "/api/",
    ]

    async def dispatch(self, request: Request, call_next):
        # 公开路径跳过认证
        if any(request.url.path.startswith(p) for p in self.PUBLIC_PATHS):
            return await call_next(request)

        # 开发阶段：放行所有请求
        # 生产环境：验证 JWT token
        # token = request.headers.get("Authorization", "").replace("Bearer ", "")
        # if not token or not verify_token(token):
        #     return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        return await call_next(request)
