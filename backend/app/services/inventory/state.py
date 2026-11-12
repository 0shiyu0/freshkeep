"""批次状态机（AGENTS.md §4.5）。

`batches.status` 只能通过这里的函数修改，禁止在 router 或别处直接赋值。

状态定义（database/001_init.sql 的 CHECK）：
- active    有库存的批次
- depleted  库存已耗尽（数量、重量同时为 0）
- void      作废（需反向流水冲销，M4/M5 实现，本模块禁止走到 void）

迁移规则：
- active → depleted  ：refresh_batch_status 在剩余归零时自动执行
- depleted → active  ：允许（撤销消耗恢复库存时用到，M4）
- 其他任何迁移      ：INVALID_STATE_TRANSITION
"""
from __future__ import annotations

from app.core.errors import conflict
from app.models import Batch
from sqlalchemy.orm import Session

_ALLOWED = {("active", "depleted"), ("depleted", "active")}


def transition(db: Session, batch: Batch, to_status: str) -> Batch:
    """显式状态迁移：校验合法性后写入。"""
    if to_status not in ("active", "depleted", "void"):
        raise conflict(f"未知状态：{to_status}", code="INVALID_STATE_TRANSITION")
    if to_status == "void":
        raise conflict(
            "批次作废需要反向流水冲销，尚未开放", code="INVALID_STATE_TRANSITION"
        )
    if (batch.status, to_status) not in _ALLOWED:
        raise conflict(
            f"不允许的状态迁移：{batch.status} → {to_status}",
            code="INVALID_STATE_TRANSITION",
        )
    batch.status = to_status
    return batch


def refresh_batch_status(batch: Batch) -> Batch:
    """根据剩余量刷新状态：归零 → depleted；有量 → active。

    在每次批次缓存更新之后调用（入库后天然 active，无需重复调用；
    消耗/盘点/撤销之后必须调用）。纯内存操作，不查库。
    """
    empty = (
        batch.remaining_quantity == 0
        and batch.remaining_weight == 0
        and batch.remaining_cost == 0
    )
    if empty and batch.status == "active":
        batch.status = "depleted"
    elif not empty and batch.status == "depleted":
        batch.status = "active"
    return batch
