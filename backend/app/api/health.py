"""健康检查。

``/health`` 是 A01 的验收点之一（curl 返回 200）。它是**存活**探针：
只要进程还能处理请求就返回 200，不验证数据库等下游——下游挂了是
``/health/ready`` 的事，混在一起会让探针把好好的进程重启掉。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import __version__
from app.core.config import get_settings

router = APIRouter(tags=["ops"])


class HealthResponse(BaseModel):
    """健康检查响应体。"""

    status: Literal["ok"] = "ok"
    service: str = Field(description="服务名")
    version: str = Field(description="服务版本")
    environment: str = Field(description="运行环境")


@router.get("/health", response_model=HealthResponse, summary="存活探针")
async def health() -> HealthResponse:
    """返回 200 表示进程可服务。"""
    settings = get_settings()
    return HealthResponse(
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
    )
