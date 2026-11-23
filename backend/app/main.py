"""FastAPI 应用工厂。

A01 只交付最小可运行骨架：中间件（trace_id）+ 全局异常处理 +
健康检查 + OpenAPI。路由分层与业务模块在 A04 及之后挂进来。

用工厂函数而不是模块级 ``app = FastAPI(...)``，是为了让测试能造出
互不干扰的多个实例。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.api import health_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import (
    configure_logging,
    get_trace_id,
    new_trace_id,
    reset_trace_id,
    set_trace_id,
)

_LOG = logging.getLogger(__name__)

TRACE_HEADER = "X-Trace-Id"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """进程级生命周期。启动/关闭的外部资源都挂在这里。

    A01 阶段没有真实外部资源，先把钩子留好；A05 的数据库连接池、
    A07 的快照加载都会加到这里。
    """
    settings = app.state.settings
    _LOG.info(
        "启动 %s v%s（env=%s）",
        settings.app_name,
        app.version,
        settings.environment,
    )
    yield
    _LOG.info("关闭 %s", settings.app_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """构造应用实例。

    >>> app = create_app()
    >>> app.title
    'agentloom'
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="可恢复的 Agent 执行内核 —— API",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        debug=settings.debug,
    )
    app.state.settings = settings

    @app.middleware("http")
    async def trace_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """为每个请求建立 trace_id，并原样回写到响应头。

        调用方（含前端、评测脚本）可以拿响应头里的 trace_id 直接去日志里搜。
        允许外部传入 ``X-Trace-Id`` 以便跨服务串联。
        """
        trace_id = request.headers.get(TRACE_HEADER) or new_trace_id()
        token = set_trace_id(trace_id)
        try:
            response = await call_next(request)
            response.headers[TRACE_HEADER] = trace_id
            return response
        finally:
            # contextvar 必须复位，否则线程/任务复用时 trace_id 会串
            reset_trace_id(token)

    _install_exception_handlers(app)
    app.include_router(health_router)
    return app


def _error_response(status: int, payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=payload)


def _install_exception_handlers(app: FastAPI) -> None:
    """把三类失败统一成 ``{code, message, trace_id}``。"""

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        """业务异常：按错误码映射状态码，日志用 warning（可预期，不告警）。"""
        trace_id = get_trace_id()
        _LOG.warning("业务异常 %s: %s", exc.code, exc.message)
        return _error_response(exc.http_status, exc.to_payload(trace_id))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        """请求体/参数校验失败 —— 422，并把字段级错误原样带出。"""
        trace_id = get_trace_id()
        fields = [
            {
                "loc": ".".join(str(p) for p in err.get("loc", ())),
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        error = AppError(
            ErrorCode.VALIDATION_FAILED,
            "请求参数校验失败",
            details={"fields": fields},
        )
        return _error_response(error.http_status, error.to_payload(trace_id))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        """框架抛的 HTTPException（404 / 405 等）也走统一格式。"""
        trace_id = get_trace_id()
        code = {
            400: ErrorCode.BAD_REQUEST,
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            409: ErrorCode.CONFLICT,
            429: ErrorCode.RATE_LIMITED,
        }.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        error = AppError(code, str(exc.detail), status_override=exc.status_code)
        return _error_response(exc.status_code, error.to_payload(trace_id))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        """兜底：绝不裸 500。栈只进日志，不外泄。"""
        trace_id = get_trace_id()
        _LOG.exception("未捕获异常: %s", exc)
        error = AppError(ErrorCode.INTERNAL_ERROR, "服务内部错误")
        return _error_response(error.http_status, error.to_payload(trace_id))


# ASGI 入口。uvicorn 用字符串形式的导入路径（``app.main:app``），这样
# ``--reload`` 才能重新导入模块。测试不要用它，请调 ``create_app()``。
app = create_app()
