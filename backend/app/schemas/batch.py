"""批次域的请求与响应模型（docs/api.md §3.3）。

数值规则与阶段 2 一致：金额/重量/数量一律字符串传输，服务端 Decimal。
数据库的重量以**克**为基准存储；API 允许传 weight_unit_id（kg 自动换算成克）。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from app.schemas.common import Dec2, Dec3, Dec4, ORMBase
from pydantic import BaseModel, ConfigDict, Field, model_validator


class BatchCreate(BaseModel):
    """POST /batches 请求：一次采购入库。"""

    ingredient_id: uuid.UUID
    purchase_date: date | None = None  # 缺省 = 今天（Asia/Shanghai）
    production_date: date | None = None
    expiry_date: date | None = None
    opened_date: date | None = None  # 开封日期（P1 的「开封后保质期」会用到）
    storage_location_id: uuid.UUID | None = None

    quantity: Dec3 = Field(default=Decimal("0"), ge=0, description="数量，如 2（包）")
    weight: Dec3 = Field(default=Decimal("0"), ge=0, description="重量（克）")
    purchase_cost: Dec2 = Field(default=Decimal("0"), ge=0, description="采购总价（元）")

    quantity_unit_id: uuid.UUID | None = None  # 数量类单位（校验维度用）
    weight_unit_id: uuid.UUID | None = None  # 重量类单位（kg 换算成克）
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _check_dates(self) -> BatchCreate:
        if (
            self.expiry_date
            and self.production_date
            and self.expiry_date < self.production_date
        ):
            raise ValueError("到期日期不能早于生产日期")
        return self


class BatchMetaUpdate(BaseModel):
    """PUT /batches/{id} 请求：只允许改元数据。

    extra="allow" 让未知字段进入 `__pydantic_extra__`，路由层检查到
    数量/成本/状态字段就 400（必须走盘点与状态机，PRD §4.6）。
    """

    model_config = ConfigDict(extra="allow")

    purchase_date: date | None = None
    production_date: date | None = None
    expiry_date: date | None = None
    opened_date: date | None = None
    storage_location_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _at_least_one(self) -> BatchMetaUpdate:
        if all(
            v is None
            for v in (
                self.purchase_date,
                self.production_date,
                self.expiry_date,
                self.opened_date,
                self.storage_location_id,
                self.note,
            )
        ):
            raise ValueError("至少修改一个字段")
        return self


class TransactionBrief(BaseModel):
    """入库响应里的流水摘要。"""

    model_config = ORMBase.model_config

    id: uuid.UUID
    transaction_no: str
    type: str
    quantity_delta: Dec3
    weight_delta: Dec3
    cost_delta: Dec2
    created_at: datetime


class BatchOut(BaseModel):
    """批次（列表项与详情共用）。"""

    model_config = ORMBase.model_config

    id: uuid.UUID
    batch_no: str
    ingredient_id: uuid.UUID
    ingredient_name: str
    purchase_date: date
    production_date: date | None
    expiry_date: date | None
    opened_date: date | None
    storage_location_id: uuid.UUID | None
    location_name: str | None
    initial_quantity: Dec3
    remaining_quantity: Dec3
    initial_weight: Dec3
    remaining_weight: Dec3
    purchase_cost: Dec2
    remaining_cost: Dec2
    # 入库时的单位成本快照（元/克 或 元/个）；由分配表取
    unit_cost: Dec4 | None
    status: str
    note: str
    days_to_expiry: int | None  # 今天(Asia/Shanghai)距到期日的天数；无到期日为 None
    created_at: datetime
