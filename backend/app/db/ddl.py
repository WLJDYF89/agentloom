"""events 表的唯一真相来源。

迁移脚本、部署用的 .sql、测试三方都从这里取 DDL，避免手抄漂移。
每条语句单独一条，因为 asyncpg 的 prepared statement 不接受多语句。
语句本身带 IF NOT EXISTS，重复执行不会报错。
"""

from __future__ import annotations

from typing import Final

TABLE_EVENTS: Final = "events"

ENVELOPE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "event_id",
        "run_id",
        "seq",
        "type",
        "trace_id",
        "created_at",
        "actor",
    }
)

EVENTS_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id        text        NOT NULL,
        run_id          text        NOT NULL,
        seq             integer     NOT NULL,
        type            text        NOT NULL,
        trace_id        text        NOT NULL,
        schema_version  smallint    NOT NULL,
        actor           text        NOT NULL,
        created_at      timestamptz NOT NULL,
        recorded_at     timestamptz NOT NULL DEFAULT now(),
        payload         jsonb       NOT NULL DEFAULT '{}'::jsonb,
        CONSTRAINT pk_events PRIMARY KEY (event_id),
        CONSTRAINT ck_events_seq_positive CHECK (seq >= 1),
        CONSTRAINT ck_events_schema_version_positive CHECK (schema_version >= 1),
        CONSTRAINT uq_events_run_seq UNIQUE (run_id, seq)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_events_run_type ON events (run_id, type, seq)",
    "CREATE INDEX IF NOT EXISTS ix_events_trace ON events (trace_id)",
    "CREATE INDEX IF NOT EXISTS ix_events_created_at ON events (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_events_payload_gin ON events USING gin (payload jsonb_path_ops)",
)

EVENTS_DROP: Final[tuple[str, ...]] = ("DROP TABLE IF EXISTS events CASCADE",)
