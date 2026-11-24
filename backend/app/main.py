from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.responses import Response

from app.api import build_api_router
from app.api.handlers import install_exception_handlers
from app.core.config import Settings, get_settings
from app.core.logging import (
    configure_logging,
    new_trace_id,
    reset_trace_id,
    set_trace_id,
)
from app.db.pool import Database

_LOG = logging.getLogger(__name__)

TRACE_HEADER = "X-Trace-Id"

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    _LOG.info(
        "启动 %s v%s（env=%s）",
        settings.app_name,
        app.version,
        settings.environment,
    )
    db = Database(settings)
    app.state.db = db
    if settings.db_pool_autostart:
        await db.connect()
    try:
        yield
    finally:
        await db.close()
        _LOG.info("关闭 %s", settings.app_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "可恢复的 Agent 执行内核 —— API\n\n"
            "- `/health` `/version` 运维接口，不带版本前缀\n"
            f"- `{API_PREFIX}/...` 业务接口，后续新增一律挂在这里"
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        debug=settings.debug,
        openapi_tags=[
            {"name": "ops", "description": "运维与健康检查"},
            {"name": "events", "description": "事件 schema 查询与规范化"},
        ],
    )
    app.state.settings = settings

    @app.middleware("http")
    async def trace_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        trace_id = request.headers.get(TRACE_HEADER) or new_trace_id()
        token = set_trace_id(trace_id)
        try:
            response = await call_next(request)
            response.headers[TRACE_HEADER] = trace_id
            return response
        finally:
            reset_trace_id(token)

    install_exception_handlers(app)
    app.include_router(build_api_router())
    return app


app = create_app()
