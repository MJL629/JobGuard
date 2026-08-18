from fastapi import APIRouter
from . import agent, auth, profile, chat, jobs, resume, companies

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(profile.router, prefix="/profile", tags=["用户画像"])
api_router.include_router(chat.router, prefix="/chat", tags=["对话"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["岗位"])
api_router.include_router(resume.router, prefix="/resume", tags=["简历"])
api_router.include_router(companies.router, prefix="/companies", tags=["企业"])
api_router.include_router(agent.router, prefix="/agent", tags=["Agent与工具"])
