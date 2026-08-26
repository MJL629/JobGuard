"""
JobGuard - 求职卫士
FastAPI 应用入口
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import create_api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print(f"🚀 {settings.app_name} v{settings.app_version} 启动中...")
    print(f"   LLM Gateway: {'Mock 模式 (未配置 API Key)' if _is_mock_mode() else '已就绪'}")
    yield
    # 关闭时
    print(f"👋 {settings.app_name} 已关闭")


def _is_mock_mode() -> bool:
    """检查是否在 Mock 模式"""
    keys = [settings.zhipu_api_key, settings.deepseek_api_key]
    return any(not k or k.startswith("your_") for k in keys)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="面向求职者的多智能体岗位筛选与简历优化系统",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(create_api_router(), prefix="/api")


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
