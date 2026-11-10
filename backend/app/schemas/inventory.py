"""库存域的请求与响应模型（docs/api.md §2.5）。

数值一律字符串传输；weight 基准为克，quantity 为食材默认数量单位。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import Dec2, Dec3, ORMBase


class InventoryRow(BaseModel):
    """v_inventory 的一行 + 展示用的名称/单位/分类路径。"""

    ingredient_id: uuid.UUID
    name: str
    category_id: uuid.UUID | None
    category_path: str
    total_quantity: Dec3
    total_weight: Dec3
    total_cost: Dec2
    batch_count: int
    nearest_expiry: date | None
    days_to_expiry: int | None
    is_low_stock: bool
    minimum_weight: Dec3
    minimum_quantity: Dec3
    weight_unit_symbol: str | None
    quantity_unit_name: str | None


class InventorySummary(BaseModel):
    total_weight: Dec3
    total_cost: Dec2
    total_quantity: Dec3
    ingredient_count: int
    batch_count: int
    low_stock_count: int
    expiring_count: int  # 7 天内到期且仍有库存
    expired_count: int


class TransactionRow(BaseModel):
    model_config = ORMBase.model_config

    id: uuid.UUID
    transaction_no: str
    type: str
    ingredient_id: uuid.UUID
    ingredient_name: str
    quantity_delta: Dec3
    weight_delta: Dec3
    cost_delta: Dec2
    reason: str
    related_object_type: str | None
    related_object_id: uuid.UUID | None
    created_at: datetime


class AdjustmentIn(BaseModel):
    """盘点：提交**实际值**，服务端反算 delta（PRD §4.6）。"""

    batch_id: uuid.UUID
    actual_weight: Dec3 | None = Field(default=None, ge=0)
    actual_quantity: Dec3 | None = Field(default=None, ge=0)
    reason: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _has_measure(self) -> "AdjustmentIn":
        if self.actual_weight is None and self.actual_quantity is None:
            raise ValueError("实际重量与实际数量至少填一项")
        return self


class StocktakeIn(BaseModel):
    items: list[AdjustmentIn] = Field(min_length=1, max_length=200)


class SpoilageIn(BaseModel):
    """报损：按 FEFO 扣批次，写 spoilage 流水。"""

    ingredient_id: uuid.UUID
    weight: Dec3 | None = Field(default=None, ge=0)
    quantity: Dec3 | None = Field(default=None, ge=0)
    reason: str = Field(default="", max_length=200)
    batch_ids: list[uuid.UUID] | None = None

    @model_validator(mode="after")
    def _has_measure(self) -> "SpoilageIn":
        if (self.weight or Decimal(0)) <= 0 and (self.quantity or Decimal(0)) <= 0:
            raise ValueError("重量与数量至少填写一项")
        return self


class AdjustmentOut(BaseModel):
    transaction_id: uuid.UUID
    transaction_no: str
    batch_id: uuid.UUID
    batch_no: str
    quantity_delta: Dec3
    weight_delta: Dec3
    cost_delta: Dec2
    batch_remaining_weight: Dec3
    batch_remaining_quantity: Dec3
    batch_remaining_cost: Dec2
    status: str


class StocktakeOut(BaseModel):
    items: list[AdjustmentOut]


class SpoilageAlloc(BaseModel):
    batch_id: uuid.UUID
    batch_no: str
    weight_delta: Dec3
    cost_delta: Dec2
    batch_remaining_weight: Dec3
    batch_remaining_cost: Dec2


class SpoilageOut(BaseModel):
    transaction_id: uuid.UUID
    transaction_no: str
    weight: Dec3
    quantity: Dec3
    cost: Dec2
    allocations: list[SpoilageAlloc]


class LedgerStockRow(BaseModel):
    """4.1：按流水重算的库存，与批次缓存对照。"""

    ingredient_id: uuid.UUID
    name: str
    ledger_weight: Dec3
    ledger_cost: Dec2
    cached_weight: Dec3
    cached_cost: Dec2
    consistency: str  # ok / mismatch


class LedgerStockOut(BaseModel):
    items: list[LedgerStockRow]
    inconsistent_count: int


class ReconcileRow(BaseModel):
    """4.12：批次缓存的差异明细（只列出 diff 非 0 的批次）。"""

    batch_id: uuid.UUID
    batch_no: str
    ingredient_id: uuid.UUID
    ingredient_name: str
    cached_quantity: Dec3
    allocated_quantity: Dec3
    diff_quantity: Dec3
    cached_weight: Dec3
    allocated_weight: Dec3
    diff_weight: Dec3
    cached_cost: Dec2
    allocated_cost: Dec2
    diff_cost: Dec2


class ReconcileOut(BaseModel):
    items: list[ReconcileRow]
    total: int


class ReconcileRepairIn(BaseModel):
    """指定要修复的批次；不传则修复全部有差异的批次。"""

    batch_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    reason: str = Field(default="", max_length=200)
