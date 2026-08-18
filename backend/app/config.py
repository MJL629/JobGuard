"""
JobGuard 全局配置管理
基于 pydantic-settings，自动从 .env 文件加载
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""

    # --- 应用 ---
    app_name: str = "JobGuard"
    app_version: str = "0.1.0"
    debug: bool = True
    secret_key: str = "change-me-to-a-random-secret-key"

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug_mode(cls, value):
        """Accept common tool-provided mode names without breaking startup."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod"}:
                return False
            if normalized in {"debug", "development", "dev"}:
                return True
        return value

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    # --- LLM API Keys ---
    zhipu_api_key: str = ""
    deepseek_api_key: str = ""
    siliconflow_api_key: str = ""

    # --- 可选外部可观测性（默认关闭，避免求职隐私离开本机）---
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "jobguard-local-evaluation"

    # --- 数据库 ---
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "jobguard"
    mysql_password: str = "jobguard123"
    mysql_database: str = "jobguard"

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset=utf8mb4"
        )

    # --- Chroma ---
    chroma_persist_dir: str = "./data/chroma"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


# 全局单例
settings = Settings()
