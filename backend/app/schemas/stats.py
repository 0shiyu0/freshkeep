"""统计接口的响应模型（阶段 6）。

数值一律字符串，金额 2 位、重量 3 位、比率 4 位。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from app.schemas.common import Dec2, Dec3, Dec4
from pydantic import BaseModel


class StockBlock(BaseModel):
    cost: Dec2
    weight: Dec3
    ingredient_count: int
    batch_count: int


class AmountBlock(BaseModel):
    total_amount: Dec2
    total_weight: Dec3


class SeriesPoint(BaseModel):
    bucket: date
    label: str
    purchase_amount: Dec2
    consumption_amount: Dec2
    purchase_weight: Dec3
    consumption_weight: Dec3


class CategoryRow(BaseModel):
    name: str
    amount: Dec2
    ratio: Dec4
    weight: Dec3


class TopConsumedRow(BaseModel):
    ingredient_id: uuid.UUID
    name: str
    weight: Dec3
    cost: Dec2
    times: int


class TurnoverRow(BaseModel):
    ingredient_id: uuid.UUID
    name: str
    purchase_times: int
    consume_times: int
    consumed_weight: Dec3


class OperationRow(BaseModel):
    id: uuid.UUID
    transaction_no: str
    type: str
    ingredient_name: str
    weight_delta: Dec3
    cost_delta: Dec2
    reason: str
    created_at: datetime


class StatsOverview(BaseModel):
    granularity: str
    start_date: date
    end_date: date
    has_data: bool
    stock: StockBlock
    purchase: AmountBlock
    consumption: AmountBlock
    series: list[SeriesPoint]
    category_breakdown: list[CategoryRow]
    top_consumed: list[TopConsumedRow]
    turnover: list[TurnoverRow]
    recent_operations: list[OperationRow]
