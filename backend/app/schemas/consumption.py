"""消耗域请求与响应模型（docs/api.md §3.4）。

数值一律字符串传输；服务端全程 Decimal。weight 的基准是克。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.common import Dec2, Dec3, Dec4, ORMBase
from pydantic import BaseModel, Field


class ConsumptionIn(BaseModel):
    """单食材消耗。quantity / weight 至少一个 > 0。

    batch_ids = null（缺省）→ FEFO 自动分配；给数组 → 按指定顺序取（仍校验可用量）。
    """

    ingredient_id: uuid.UUID
    weight: Dec3 | None = Field(default=None, ge=0, description="消耗重量（克）")
    quantity: Dec3 | None = Field(default=None, ge=0, description="消耗数量（包/个）")
    consumed_at: datetime | None = None
    note: str = Field(default="", max_length=500)
    batch_ids: list[uuid.UUID] | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class BatchConsumptionIn(BaseModel):
    """批量消耗：整批成功或整批回滚（PRD §7.1 用例 9）。"""

    items: list[ConsumptionIn] = Field(min_length=1, max_length=50)
    consumed_at: datetime | None = None
    note: str = Field(default="", max_length=500)


class ReverseIn(BaseModel):
    reason: str = Field(default="", max_length=200)


class ConsumptionOut(BaseModel):
    model_config = ORMBase.model_config

    id: uuid.UUID
    consumption_no: str
    ingredient_id: uuid.UUID
    ingredient_name: str
    quantity: Dec3
    weight: Dec3
    cost: Dec2
    consumed_at: datetime
    note: str
    status: str
    created_at: datetime


class AllocationOut(BaseModel):
    batch_id: uuid.UUID
    batch_no: str
    quantity_delta: Dec3
    weight_delta: Dec3
    cost_delta: Dec2
    unit_cost: Dec4 | None
    batch_remaining_quantity: Dec3
    batch_remaining_weight: Dec3
    batch_remaining_cost: Dec2


class NutritionOut(BaseModel):
    code: str
    name: str
    actual_value: Dec4
    unit: str
    basis_snapshot: dict


class ConsumptionDetail(ConsumptionOut):
    allocations: list[AllocationOut]
    nutrition: list[NutritionOut]


class ConsumptionResult(BaseModel):
    """POST /consumptions 的 data（与 api.md §3.4 一致）。"""

    consumption: ConsumptionOut
    allocations: list[AllocationOut]
    nutrition: list[NutritionOut]
