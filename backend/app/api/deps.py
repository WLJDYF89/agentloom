from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.logging import get_trace_id


def get_settings_dep() -> Settings:
    return get_settings()


def get_trace_id_dep() -> str:
    return get_trace_id()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
TraceIdDep = Annotated[str, Depends(get_trace_id_dep)]


class ErrorBody(BaseModel):
    """对外错误响应的形状，只用于 OpenAPI 声明；实际响应由异常处理器构造。"""

    code: str = Field(description="稳定的机器可读错误码")
    message: str = Field(description="给人读的一句话")
    trace_id: str = Field(description="用来在日志里定位这次请求")
    details: dict[str, Any] | None = Field(default=None, description="补充信息，可为空")


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorBody, "description": "请求不合法"},
    401: {"model": ErrorBody, "description": "未认证"},
    403: {"model": ErrorBody, "description": "无权限"},
    404: {"model": ErrorBody, "description": "资源不存在"},
    409: {"model": ErrorBody, "description": "冲突"},
    422: {"model": ErrorBody, "description": "参数校验失败"},
    429: {"model": ErrorBody, "description": "限流"},
    500: {"model": ErrorBody, "description": "服务内部错误"},
    503: {"model": ErrorBody, "description": "依赖不可用"},
}
