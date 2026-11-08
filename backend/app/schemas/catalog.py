"""基础资料（分类 / 单位 / 储存位置 / 营养项目）的请求与响应模型。"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import ORMBase


# ---------------------------------------------------------------- 分类


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    parent_id: uuid.UUID | None = None
    sort_order: int = Field(default=0, ge=0, le=9999)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("分类名不能为空")
        return v


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    parent_id: uuid.UUID | None = None
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    is_active: bool | None = None


class CategoryOut(ORMBase):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    parent_name: str | None = None
    sort_order: int
    is_active: bool
    ingredient_count: int = 0


class CategorySortItem(BaseModel):
    id: uuid.UUID
    sort_order: int = Field(ge=0, le=9999)


class CategorySortIn(BaseModel):
    items: list[CategorySortItem] = Field(min_length=1, max_length=200)


# ---------------------------------------------------------------- 单位


class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    symbol: str = Field(default="", max_length=10)
    dimension: str = Field(pattern="^(quantity|weight|volume)$")
    precision: int = Field(default=3, ge=0, le=4)
    is_system: bool = False

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("单位名不能为空")
        return v


class UnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=20)
    symbol: str | None = Field(default=None, max_length=10)
    precision: int | None = Field(default=None, ge=0, le=4)


class UnitOut(ORMBase):
    id: uuid.UUID
    name: str
    symbol: str
    dimension: str
    precision: int
    is_system: bool
    usage_count: int = 0


# ---------------------------------------------------------------- 储存位置


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    description: str = Field(default="", max_length=200)
    sort_order: int = Field(default=0, ge=0, le=9999)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("位置名不能为空")
        return v


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=30)
    description: str | None = Field(default=None, max_length=200)
    sort_order: int | None = Field(default=None, ge=0, le=9999)


class LocationOut(ORMBase):
    id: uuid.UUID
    name: str
    description: str
    sort_order: int


# ---------------------------------------------------------------- 营养项目


class NutritionDefinitionOut(ORMBase):
    id: uuid.UUID
    code: str
    name: str
    unit: str
    sort_order: int
    is_active: bool


# ---------------------------------------------------------------- 引用校验


class UnitRef(BaseModel):
    """食材里引用单位时的约束：dimension 必须与用途匹配。"""

    quantity_unit_id: uuid.UUID | None = None
    weight_unit_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _not_same(self):
        if self.quantity_unit_id and self.quantity_unit_id == self.weight_unit_id:
            raise ValueError("数量单位与重量单位不能是同一个")
        return self


class TimestampMixin(BaseModel):
    created_at: datetime | None = None
