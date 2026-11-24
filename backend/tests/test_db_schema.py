"""events 表的结构与幂等性。

这些用例真的连库：表结构对不对，只能问数据库本身。
库连不上就整体 skip —— 没开 Docker 的机器仍能跑其余用例。
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any, TypeVar

import asyncpg
import pytest
from app.core.config import get_settings
from app.db.ddl import ENVELOPE_FIELDS, EVENTS_DDL, EVENTS_DROP
from app.db.pool import Database
from app.db.rows import INSERT_SQL, encode_payload, row_to_event, split_event
from app.events.schema import Actor, RunStarted

DSN_ENV = "AGENTLOOM_TEST_PG_DSN"
DEFAULT_DSN = "postgresql://agentloom:agentloom@localhost:5432/agentloom"

T = TypeVar("T")


def _dsn() -> str:
    return os.environ.get(DSN_ENV, DEFAULT_DSN)


def _run[T](body: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """每个用例一个独立事件循环：asyncpg 的连接不能跨循环复用。"""
    return asyncio.run(body())


@asynccontextmanager
async def _connect() -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(_dsn())
    try:
        yield conn
    finally:
        await conn.close()


def _mark_skip_if_down() -> None:
    async def probe() -> None:
        async with _connect():
            pass

    try:
        _run(probe)
    except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
        pytest.skip(f"PostgreSQL 不可用：{type(exc).__name__}: {exc}")


@pytest.fixture
def pg() -> None:
    _mark_skip_if_down()


def make_event() -> RunStarted:
    return RunStarted(
        run_id="run-1",
        seq=1,
        trace_id="trace-1",
        actor=Actor.AGENT,
        task="查一下工单 42",
        model="deepseek-chat",
    )


class TestTableShape:
    def test_table_exists(self, pg: None) -> None:
        async def body() -> None:
            async with _connect() as conn:
                assert await conn.fetchval("SELECT to_regclass('public.events') IS NOT NULL")

        _run(body)

    def test_columns_match_envelope(self, pg: None) -> None:
        async def body() -> None:
            async with _connect() as conn:
                rows = await conn.fetch(
                    """
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'events'
                    """,
                )
            actual = {
                r["column_name"]: (r["data_type"], r["is_nullable"], r["column_default"])
                for r in rows
            }

            for field in ENVELOPE_FIELDS:
                assert field in actual, f"缺列：{field}"
                assert actual[field][1] == "NO", f"{field} 不应可为 NULL"
                assert actual[field][2] is None, f"{field} 不该有默认值：漏填要报错，不能被悄悄补上"

            assert actual["created_at"][0] == "timestamp with time zone"
            assert actual["payload"][0] == "jsonb"
            assert actual["recorded_at"][0] == "timestamp with time zone"
            assert actual["recorded_at"][2] is not None, "recorded_at 由库侧填默认值"

        _run(body)

    def test_run_seq_unique(self, pg: None) -> None:
        """A06 的并发重试全靠这条约束兜底，缺了它就会写出重复 seq。"""

        async def body() -> None:
            async with _connect() as conn:
                conname = await conn.fetchval(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'public.events'::regclass
                      AND contype = 'u'
                      AND conkey = ARRAY[
                          (SELECT attnum FROM pg_attribute
                            WHERE attrelid = 'public.events'::regclass AND attname = 'run_id'),
                          (SELECT attnum FROM pg_attribute
                            WHERE attrelid = 'public.events'::regclass AND attname = 'seq')
                      ]::smallint[]
                    """,
                )
            assert conname == "uq_events_run_seq"

        _run(body)

    def test_duplicate_run_seq_rejected(self, pg: None) -> None:
        async def body() -> None:
            async with _connect() as conn:
                sql = """
                    INSERT INTO events
                        (event_id, run_id, seq, type, trace_id, schema_version, actor, created_at)
                    VALUES ($1, 'run-dup', 1, 'run.started', 't', 1, 'system', now())
                """
                try:
                    await conn.execute(sql, "e-dup-1")
                    with pytest.raises(asyncpg.UniqueViolationError):
                        await conn.execute(sql, "e-dup-2")
                finally:
                    await conn.execute("DELETE FROM events WHERE run_id = 'run-dup'")

        _run(body)

    def test_indexes_exist(self, pg: None) -> None:
        async def body() -> None:
            async with _connect() as conn:
                rows = await conn.fetch(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'public' AND tablename = 'events'",
                )
            names = {r["indexname"] for r in rows}
            assert {
                "ix_events_run_type",
                "ix_events_trace",
                "ix_events_created_at",
                "ix_events_payload_gin",
            } <= names

        _run(body)

    def test_gin_index_usable(self, pg: None) -> None:
        """jsonb_path_ops 的 GIN 只有 @> 能走，确认它真被用上。

        空表下规划器一定选顺序扫描，故先关掉 seqscan 逼它走索引。
        """

        async def body() -> None:
            async with _connect() as conn, conn.transaction():
                await conn.execute("SET LOCAL enable_seqscan = off")
                plan = await conn.fetch(
                    'EXPLAIN SELECT 1 FROM events WHERE payload @> \'{"decision": "deny"}\'::jsonb',
                )
            text = " ".join(r["QUERY PLAN"] for r in plan)
            assert "ix_events_payload_gin" in text

        _run(body)

    def test_seq_must_be_positive(self, pg: None) -> None:
        async def body() -> None:
            async with _connect() as conn:
                with pytest.raises(asyncpg.CheckViolationError):
                    await conn.execute(
                        """
                        INSERT INTO events
                            (event_id, run_id, seq, type, trace_id, schema_version, actor, created_at)
                        VALUES ('e-neg', 'r-neg', 0, 'run.started', 't', 1, 'system', now())
                        """,
                    )

        _run(body)


class TestDdlIdempotent:
    def test_rerun_is_noop(self, pg: None) -> None:
        """A05 验收原文：「建表 SQL + 迁移脚本，可重复执行」。"""

        async def body() -> None:
            async with _connect() as conn:
                for statement in EVENTS_DDL:
                    await conn.execute(statement)
                assert await conn.fetchval("SELECT to_regclass('public.events') IS NOT NULL")

        _run(body)

    def test_drop_statements_match_table(self) -> None:
        assert EVENTS_DROP == ("DROP TABLE IF EXISTS events CASCADE",)


class TestRowMapping:
    def test_split_puts_envelope_in_columns(self) -> None:
        event = make_event()
        params = split_event(event)
        assert params[0] == event.event_id
        assert params[1] == "run-1"
        assert params[2] == 1
        assert params[3] == "run.started"
        payload = json.loads(params[8])
        assert set(payload) & ENVELOPE_FIELDS == set()
        assert payload["task"] == "查一下工单 42"
        assert payload["model"] == "deepseek-chat"

    def test_encode_payload_is_deterministic(self) -> None:
        """A07 的 state hash 吃这段字节，同一事件必须每次都算出同一串。"""
        event = make_event()
        first = encode_payload(event)
        assert first == encode_payload(event)
        assert first == encode_payload(event.model_copy())
        assert first.startswith('{"'), "紧凑分隔符：不能带空格"
        assert ", " not in first and '": ' not in first

    def test_roundtrip_through_db(self, pg: None) -> None:
        event = make_event()

        async def body() -> None:
            async with _connect() as conn:
                await conn.execute("DELETE FROM events WHERE run_id = $1", event.run_id)
                try:
                    await conn.execute(INSERT_SQL, *split_event(event))
                    row = await conn.fetchrow(
                        "SELECT * FROM events WHERE run_id = $1",
                        event.run_id,
                    )
                    assert row is not None
                    assert row_to_event(row) == event
                finally:
                    await conn.execute("DELETE FROM events WHERE run_id = $1", event.run_id)

        _run(body)

    def test_payload_is_compact_json(self, pg: None) -> None:
        """中文不能被转义成 \\uXXXX，否则 A07 的 hash 会跟 canonical_json 对不上。"""

        async def body() -> None:
            event = make_event().model_copy(update={"run_id": "run-cjk"})
            async with _connect() as conn:
                await conn.execute("DELETE FROM events WHERE run_id = $1", event.run_id)
                try:
                    await conn.execute(INSERT_SQL, *split_event(event))
                    raw = await conn.fetchval(
                        "SELECT payload::text FROM events WHERE run_id = $1",
                        event.run_id,
                    )
                    assert "查一下工单 42" in raw
                    assert "\\u" not in raw
                finally:
                    await conn.execute("DELETE FROM events WHERE run_id = $1", event.run_id)

        _run(body)


class TestDatabase:
    def test_ping_true_when_up(self, pg: None) -> None:
        settings = get_settings()

        async def body() -> None:
            async with Database(settings) as db:
                assert await db.ping() is True

        _run(body)

    def test_ping_false_when_not_connected(self) -> None:
        db = Database(get_settings())

        async def body() -> Any:
            return await db.ping()

        assert _run(body) is False
