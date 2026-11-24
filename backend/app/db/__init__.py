"""事件表的读写接口。

只做 A05 的范围：表结构、DDL 来源、连接池、行映射。真正的 ``append_event``
（seq 冲突重试）是 A06，``replay`` 是 A07，这一层故意不实现。
"""

from __future__ import annotations

from app.db.ddl import ENVELOPE_FIELDS, EVENTS_DDL, EVENTS_DROP, TABLE_EVENTS
from app.db.pool import Database, create_pool
from app.db.rows import INSERT_SQL, encode_payload, row_to_event, split_event

__all__ = [
    "ENVELOPE_FIELDS",
    "EVENTS_DDL",
    "EVENTS_DROP",
    "INSERT_SQL",
    "TABLE_EVENTS",
    "Database",
    "create_pool",
    "encode_payload",
    "row_to_event",
    "split_event",
]
