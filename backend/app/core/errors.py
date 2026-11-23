"""统一错误码与业务异常。

约定：**任何**对外错误响应都长这样，绝不裸 500 把栈吐给调用方。

    {
      "code": "TOOL_NOT_FOUND",
      "message": "工具 weather_v2 未注册",
      "trace_id": "0f3c1e9a8b7d4c56",
      "details": {"tool_name": "weather_v2"}
    }

``code`` 是机器读的稳定枚举，``message`` 是给人读的一句话，
``trace_id`` 让一次失败能被日志串起来。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """稳定错误码。新增只能追加，不能改名——前端和评测脚本都依赖它。"""

    # 4xx —— 调用方的问题
    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"

    # 5xx —— 我们的问题
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"


#: 错误码到 HTTP 状态码的映射。未列出的按 500 处理。
_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
}


class AppError(Exception):
    """所有业务异常的基类。

    路由层只负责抛，转换 HTTP 响应由全局异常处理器统一做。

    >>> err = AppError(ErrorCode.NOT_FOUND, "run 不存在", details={"run_id": "r1"})
    >>> err.http_status
    404
    """

    http_status: int = 500

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_override: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        if status_override is not None:
            self.http_status = status_override
        else:
            self.http_status = _HTTP_STATUS.get(code, 500)

    def to_payload(self, trace_id: str) -> dict[str, Any]:
        """转成对外响应体。``trace_id`` 由中间件注入。"""
        payload: dict[str, Any] = {
            "code": str(self.code),
            "message": self.message,
            "trace_id": trace_id,
        }
        if self.details:
            payload["details"] = self.details
        return payload

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"AppError(code={self.code!s}, message={self.message!r})"
