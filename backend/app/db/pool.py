"""asyncpg 连接池。

用 asyncpg 而不是 ORM：events 是 append-only，只有「插入」和「按 run_id 顺序读」，
没有对象图，ORM 能给的在这里都不成立；而 seq 冲突重试、部分唯一索引、jsonb 查询
这三处恰恰需要手写 SQL。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from types import TracebackType

import asyncpg

from app.core.config import Settings

_LOG = logging.getLogger(__name__)

ConnectionInit = Callable[[asyncpg.Connection], Awaitable[None]]


def _server_settings(settings: Settings) -> dict[str, str]:
    # 会话统一 UTC：时间戳比较不受宿主机时区影响。
    return {
        "application_name": f"{settings.app_name}-{settings.environment}",
        "timezone": "UTC",
    }


def _make_init(settings: Settings) -> ConnectionInit:
    # statement_timeout 兜住忘加超时的查询，否则一条慢 SQL 会占住整个连接。
    timeout_ms = int(settings.db_command_timeout_s * 1000)

    async def _init(conn: asyncpg.Connection) -> None:
        await conn.execute(f"SET statement_timeout = {timeout_ms}")

    return _init


async def create_pool(settings: Settings) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(
        dsn=settings.asyncpg_dsn,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_size,
        timeout=settings.db_pool_timeout_s,
        command_timeout=settings.db_command_timeout_s,
        server_settings=_server_settings(settings),
        init=_make_init(settings),
    )
    _LOG.info(
        "数据库连接池就绪（%s~%s 条连接）",
        settings.db_pool_min_size,
        settings.db_pool_size,
    )
    return pool


class Database:
    """连接池的生命周期包装。懒连接，``ping()`` 供就绪探针使用。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("连接池未初始化：先 await db.connect()")
        return self._pool

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await create_pool(self._settings)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            _LOG.info("数据库连接池已关闭")

    async def ping(self) -> bool:
        """探针用：任何异常都算不可用，只返回真假，不抛。"""
        try:
            async with self.pool.acquire() as conn:
                value: object = await conn.fetchval("SELECT 1")
                return value == 1
        except (RuntimeError, asyncpg.PostgresError, OSError, TimeoutError) as exc:
            _LOG.warning("数据库探测失败：%s: %s", type(exc).__name__, exc)
            return False

    async def __aenter__(self) -> Database:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
