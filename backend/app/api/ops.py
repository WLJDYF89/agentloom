from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import __version__
from app.api.deps import ERROR_RESPONSES, SettingsDep

router = APIRouter(tags=["ops"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = Field(description="服务名")
    version: str = Field(description="服务版本")
    environment: str = Field(description="运行环境")


class VersionResponse(BaseModel):
    service: str
    version: str
    environment: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="存活探针",
    responses=ERROR_RESPONSES,
)
async def health(settings: SettingsDep) -> HealthResponse:
    """进程能处理请求就返回 200，不查下游。

    就绪探针等 A05 接了数据库再单独加，两者混在一起会让探针把好进程重启掉。
    """
    return HealthResponse(
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
    )


@router.get(
    "/version",
    response_model=VersionResponse,
    summary="版本信息",
    responses=ERROR_RESPONSES,
)
async def version(settings: SettingsDep) -> VersionResponse:
    return VersionResponse(
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
    )
