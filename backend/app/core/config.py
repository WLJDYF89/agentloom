"""应用配置。

所有配置从环境变量读取，前缀 ``AGENTLOOM_``，并可被 ``.env`` 覆盖。
配置对象是**不可变**的：运行时不允许偷偷改配置，否则恢复路径会变得不可推理。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "prod"]


class Settings(BaseSettings):
    """全局配置。字段名即环境变量名去前缀后的大写形式。

    >>> import os; os.environ["AGENTLOOM_ENVIRONMENT"] = "test"
    >>> get_settings().environment
    'test'
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTLOOM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # ---- 基本信息 ----
    app_name: str = "agentloom"
    environment: Environment = "local"
    debug: bool = False

    # ---- HTTP 服务 ----
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    # ---- 数据库 ----
    # 写成 SQLAlchemy 的 driver 形式，因为 Alembic 走它；直接给 asyncpg 用时去掉 +asyncpg。
    database_url: str = "postgresql+asyncpg://agentloom:agentloom@localhost:5432/agentloom"
    db_pool_min_size: int = Field(default=1, ge=0, le=100)
    db_pool_size: int = Field(default=10, ge=1, le=200)
    db_pool_timeout_s: float = Field(default=5.0, gt=0)
    db_command_timeout_s: float = Field(default=10.0, gt=0)
    # 测试里关掉，避免每个 TestClient 都去连一次库
    db_pool_autostart: bool = True

    # ---- 日志 ----
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

    @property
    def asyncpg_dsn(self) -> str:
        """asyncpg 只认 ``postgresql://``，不认 SQLAlchemy 的 ``+asyncpg``。"""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程内单例配置。

    用 ``lru_cache`` 而不是模块级常量，是为了让测试能用
    ``get_settings.cache_clear()`` 干净地重置。
    """
    return Settings()
