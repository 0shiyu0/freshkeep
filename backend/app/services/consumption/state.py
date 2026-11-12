"""消耗单状态机（AGENTS.md §4.5）。

`consumption_records.status` 只能经本模块迁移，禁止在 router 或别处直接赋值。

- completed → reversed：撤销消耗，必须同时给出反向流水 id
  （DDL 的 ck_consumption_reversed 约束会兜底校验）
- 其他迁移一律拒绝；撤销不可重复。
"""
from __future__ import annotations

import uuid

from app.core.errors import conflict
from app.models import ConsumptionRecord
from sqlalchemy.orm import Session


def mark_reversed(db: Session, record: ConsumptionRecord, reverse_tx_id: uuid.UUID) -> None:
    """把已完成的消耗单置为 reversed，并写入反向流水 id。"""
    if record.status == "reversed":
        raise conflict("该消耗已撤销，不能重复操作", code="ALREADY_REVERSED")
    if record.status != "completed":
        raise conflict(
            f"当前状态 {record.status} 不能撤销", code="INVALID_STATE_TRANSITION"
        )
    record.status = "reversed"
    record.reversed_by_transaction_id = reverse_tx_id
