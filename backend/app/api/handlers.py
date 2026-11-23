from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_trace_id

_LOG = logging.getLogger(__name__)

_HTTP_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    429: ErrorCode.RATE_LIMITED,
}


def _error_response(status: int, payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=payload)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        _LOG.warning("业务异常 %s: %s", exc.code, exc.message)
        return _error_response(exc.http_status, exc.to_payload(get_trace_id()))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
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
        return _error_response(error.http_status, error.to_payload(get_trace_id()))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        error = AppError(code, str(exc.detail), status_override=exc.status_code)
        return _error_response(exc.status_code, error.to_payload(get_trace_id()))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        _LOG.exception("未捕获异常: %s", exc)
        error = AppError(ErrorCode.INTERNAL_ERROR, "服务内部错误")
        return _error_response(error.http_status, error.to_payload(get_trace_id()))
