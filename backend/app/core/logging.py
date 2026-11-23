"""日志与 trace_id 上下文。

trace_id 是"一次请求/一次 run 的唯一身份证"：它进入日志、进入错误响应、
进入事件表。这里用 ``contextvars`` 保存，避免在每层函数里手动传递。
"""

from __future__ import annotations

import contextvars
import logging
import sys
import uuid
from typing import Any, Final

_TRACE_ID: Final[contextvars.ContextVar[str]] = contextvars.ContextVar("trace_id", default="-")
_LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)-7s [%(trace_id)s] %(name)s: %(message)s"
_DATE_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S%z"


def new_trace_id() -> str:
    """生成一个新的 trace_id（32 位十六进制，无连字符，省日志宽度）。"""
    return uuid.uuid4().hex


def get_trace_id() -> str:
    """读取当前上下文的 trace_id，没有则返回 ``-``。"""
    return _TRACE_ID.get()


def set_trace_id(trace_id: str) -> contextvars.Token[str]:
    """设置当前上下文的 trace_id，返回可用于 :func:`reset_trace_id` 的 token。"""
    return _TRACE_ID.set(trace_id)


def reset_trace_id(token: contextvars.Token[str]) -> None:
    """复位 trace_id。

    必须调用：contextvar 是任务/线程复用的，漏复位会让下一个请求
    继承上一个请求的 trace_id，日志就串了。
    """
    _TRACE_ID.reset(token)


class TraceIdFilter(logging.Filter):
    """把 contextvar 里的 trace_id 塞进每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _TRACE_ID.get()
        return True


def configure_logging(level: str = "INFO", *, stream: Any | None = None) -> None:
    """配置根 logger。

    幂等：重复调用只替换 handler，不会叠加（否则日志会翻倍）。
    """
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    handler.addFilter(TraceIdFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn 的 access log 自带时间戳，交给它，避免格式打架
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
