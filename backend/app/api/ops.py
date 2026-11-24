from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import __version__
from app.api.deps import ERROR_RESPONSES, SettingsDep
from app.core.errors import AppError, ErrorCode
from app.db.pool import Database

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


class ReadyResponse(BaseModel):
    status: Literal["ready"] = "ready"
    database: Literal["ok"] = "ok"


def _database(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="存活探针",
    responses=ERROR_RESPONSES,
)
async def health(settings: SettingsDep) -> HealthResponse:
    """进程能处理请求就返回 200，不查下游。

    就绪与否看 ``/ready``：两者混在一起会让下游抖动把好进程重启掉。
    """
    return HealthResponse(
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
    )


@router.get(
    "/ready",
    response_model=ReadyResponse,
    summary="就绪探针",
    responses=ERROR_RESPONSES,
)
async def ready(request: Request) -> ReadyResponse:
    """数据库连得上才返回 200，否则 503。

    只摘流量、不重启进程 —— 数据库抖一下不该把整个服务重启一遍。
    """
    if not await _database(request).ping():
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, "数据库暂时不可用")
    return ReadyResponse()


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
