"""进程启动时加载一次的应用配置。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent  # 项目根目录


class Settings(BaseSettings):
    """API 基础设施共享的环境配置。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    cors_origins: str = "http://localhost:5173"

    database_url: str
    checkpoint_database_url: str | None = None
    checkpoint_pool_min_size: int = Field(default=1, ge=1)
    checkpoint_pool_max_size: int = Field(default=10, ge=1)
    checkpoint_pool_timeout_seconds: int = Field(default=5, ge=1, le=60)

    app_host: str = "0.0.0.0"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"

    chroma_persist_directory: str = "./storage/chroma"

    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=1, le=1440)
    demo_auth_enabled: bool = True

    @model_validator(mode="after")
    def validate_runtime_safety(self) -> Settings:
        if self.checkpoint_pool_max_size < self.checkpoint_pool_min_size:
            raise ValueError("CHECKPOINT_POOL_MAX_SIZE 不能小于 CHECKPOINT_POOL_MIN_SIZE")
        if self.app_env == "production":
            if self.demo_auth_enabled:
                raise ValueError("生产环境必须关闭 DEMO_AUTH_ENABLED")
            secret = self.jwt_secret_key.get_secret_value()
            if len(secret) < 32 or secret == "change-this-for-local-development":
                raise ValueError("生产环境 JWT_SECRET_KEY 必须是至少 32 位的随机字符串")
        return self

    @property
    def checkpoint_dsn(self) -> str:
        url = self.checkpoint_database_url or self.database_url
        return url.replace("postgresql+psycopg://", "postgresql://", 1)

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings"]
