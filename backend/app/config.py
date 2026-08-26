"""
JobGuard 全局配置管理
基于 pydantic-settings，自动从 .env 文件加载
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""

    # --- 应用 ---
    app_name: str = "JobGuard"
    app_version: str = "0.1.0"
    debug: bool = True
    secret_key: str = "change-me-to-a-random-secret-key"

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    # --- LLM API Keys ---
    zhipu_api_key: str = ""
    deepseek_api_key: str = ""
    siliconflow_api_key: str = ""

    # --- Local / self-hosted OpenAI-compatible model ---
    vllm_base_url: str = "http://127.0.0.1:6006/v1"
    vllm_api_key: str = "local-vllm"
    vllm_model: str = "qwen2.5-7b"
    llm_primary_provider: str = "zhipu"

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
