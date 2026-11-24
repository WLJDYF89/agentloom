"""事件信封 ↔ 数据库行。

信封字段拆成列（便于建唯一约束和索引），其余载荷整体进 payload jsonb。
这样 A06 的 ``UNIQUE (run_id, seq)`` 才有地方落，A07 重放读回来也能还原成原对象。
"""

from __future__ import annotations

import json
from typing import Any, Final

from app.db.ddl import ENVELOPE_FIELDS
from app.events.schema import EventBase, parse_event

INSERT_SQL: Final = """
INSERT INTO events (
    event_id, run_id, seq, type, trace_id, schema_version, actor, created_at, payload
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
"""


def encode_payload(event: EventBase) -> str:
    """载荷按 canonical 规则序列化。

    中文不转义、键排序：A07 的状态 hash 直接吃这段字节，
    让数据库里的 jsonb 文本和 Python 侧算出的 hash 是同一份输入。
    """
    dumped = event.model_dump(mode="json")
    payload = {k: v for k, v in dumped.items() if k not in ENVELOPE_FIELDS}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def split_event(event: EventBase) -> tuple[Any, ...]:
    """拆成 INSERT 需要的位置参数。"""
    dumped = event.model_dump(mode="json")
    return (
        event.event_id,
        event.run_id,
        event.seq,
        dumped["type"],
        event.trace_id,
        event.schema_version,
        str(event.actor),
        event.created_at,
        encode_payload(event),
    )


def row_to_event(row: Any) -> EventBase:
    """把查询结果还原成事件对象。``recorded_at`` 是库侧写入时间，不属于 schema。"""
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return parse_event(
        {
            "schema_version": row["schema_version"],
            "event_id": row["event_id"],
            "run_id": row["run_id"],
            "seq": row["seq"],
            "type": row["type"],
            "trace_id": row["trace_id"],
            "actor": row["actor"],
            "created_at": row["created_at"],
            **payload,
        }
    )
