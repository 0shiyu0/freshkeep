"""首页与营养统计的请求/响应模型（docs/PRD §4.2、§4.7）。

关键口径：
- 金额/重量一律字符串；
- 消耗比例在「无采购」时返回 `null`，不返回 0（避免把无数据读成 0%）；
- 营养在「无消耗记录」时 `has_records=false`，数值仍为 0 但可区分（PRD §4.7）。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from app.schemas.common import Dec2, Dec3, Dec4
from pydantic import BaseModel, Field


class RecentBatch(BaseModel):
    batch_id: uuid.UUID
    batch_no: str
    ingredient_id: uuid.UUID
    ingredient_name: str
    weight: Dec3
    cost: Dec2
    purchase_date: date
    created_at: datetime


class DashboardSummary(BaseModel):
    stock_cost: Dec2
    stock_weight: Dec3
    stock_ingredient_count: int
    batch_count: int
    low_stock_count: int
    expiring_count: int
    expired_count: int

    period_start: date
    period_end: date
    purchase_amount: Dec2
    consumption_amount: Dec2
    spoilage_amount: Dec2
    consumption_ratio: Dec4 | None  # 无采购时为 null

    recent_batches: list[RecentBatch]


class NutritionItem(BaseModel):
    code: str
    name: str
    unit: str
    actual_value: Dec4
    target_value: Dec4 | None       # 日目标
    period_target: Dec4 | None      # 本窗口累计目标（日目标 × 天数）
    achievement: Dec4 | None        # 实际 / 窗口累计目标，目标为空则 null


class DashboardNutrition(BaseModel):
    period: str
    start_date: date
    end_date: date
    days: int
    has_records: bool  # False = 窗口内没有任何已完成消耗（与「0 摄入」区分）
    record_count: int
    items: list[NutritionItem]
    disclaimer: str


class TargetIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    target_value: Dec4 = Field(gt=0)
    period: str = Field(default="daily", pattern="^(daily|weekly)$")


class TargetsIn(BaseModel):
    items: list[TargetIn] = Field(min_length=1, max_length=12)


class TargetRow(BaseModel):
    code: str
    name: str
    unit: str
    target_value: Dec4
    period: str
    effective_from: date


class TargetsOut(BaseModel):
    items: list[TargetRow]
