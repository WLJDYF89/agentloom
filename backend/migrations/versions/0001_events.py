"""events 表：事件溯源的主干。

DDL 取 ``app.db.ddl.EVENTS_DDL``，不在这里手抄 —— 迁移脚本和测试对拍
用的是同一份字符串，改一处就同步。

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""

from __future__ import annotations

from alembic import op
from app.db.ddl import EVENTS_DDL, EVENTS_DROP

revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    for statement in EVENTS_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in EVENTS_DROP:
        op.execute(statement)
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
