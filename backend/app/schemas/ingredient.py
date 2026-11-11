"""食材档案的请求与响应模型。

关于换算（AGENTS.md §4.1 / PRD §5.3）：
- `default_unit_weight` = 1 个数量单位折合多少**克**；NULL 表示"无换算关系"。
- 无换算关系时后端**不推算**另一个维度，前端也不能拿 0 当结果。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import Dec3, Dec4, ORMBase


class BarcodeIn(BaseModel):
    barcode: str = Field(min_length=4, max_length=64)
    barcode_type: str = Field(default="ean13", pattern="^(ean8|ean13|upc|code128|qr|other)$")

    @field_validator("barcode")
    @classmethod
    def _digits(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("条码不能为空")
        if not v.replace("-", "").isalnum():
            raise ValueError("条码只能包含字母、数字与连字符")
        return v


class NutritionIn(BaseModel):
    code: str = Field(min_length=1, max_length=32, description="营养项目 code，如 calories")
    value: Dec4 = Field(gt=-1)
    basis_amount: Dec3 = Field(gt=0, description="基准量，如 100")
    basis_unit_id: uuid.UUID
    # 7.9 数据来源：手动录入 / 包装标识 / 数据库
    source: str = Field(default="manual", pattern="^(manual|packaging_label|database)$")


class IngredientIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    category_id: uuid.UUID | None = None
    image_asset_id: uuid.UUID | None = None
    brand: str = Field(default="", max_length=50)
    specification: str = Field(default="", max_length=50)

    default_quantity_unit_id: uuid.UUID | None = None
    default_weight_unit_id: uuid.UUID | None = None
    default_unit_weight: Dec3 | None = None  # 每包重量（克）

    nutrition_basis_amount: Dec3 | None = None
    nutrition_basis_unit_id: uuid.UUID | None = None

    default_storage_location_id: uuid.UUID | None = None
    minimum_quantity: Dec3 = Field(default=Decimal("0"), ge=0)
    minimum_weight: Dec3 = Field(default=Decimal("0"), ge=0)
    note: str = Field(default="", max_length=500)

    barcodes: list[BarcodeIn] = Field(default_factory=list, max_length=5)
    nutrition: list[NutritionIn] = Field(default_factory=list, max_length=12)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("食材名称不能为空")
        return v

    @model_validator(mode="after")
    def _check_conversion(self):
        # 有换算关系必须两端单位齐全；没有换算关系则不允许只给一半
        if self.default_unit_weight is not None:
            if not self.default_quantity_unit_id or not self.default_weight_unit_id:
                raise ValueError("设置了每包重量时，必须同时选择数量单位与重量单位")
            if self.default_unit_weight <= 0:
                raise ValueError("每包重量必须大于 0")
        if self.nutrition_basis_amount is not None and not self.nutrition_basis_unit_id:
            raise ValueError("填写营养基准量时必须选择基准单位")
        return self


class IngredientUpdate(BaseModel):
    """全部字段可选；传 null 表示清空（如取消换算关系）。"""

    name: str | None = Field(default=None, min_length=1, max_length=50)
    category_id: uuid.UUID | None = None
    image_asset_id: uuid.UUID | None = None
    brand: str | None = Field(default=None, max_length=50)
    specification: str | None = Field(default=None, max_length=50)
    default_quantity_unit_id: uuid.UUID | None = None
    default_weight_unit_id: uuid.UUID | None = None
    default_unit_weight: Dec3 | None = None
    nutrition_basis_amount: Dec3 | None = None
    nutrition_basis_unit_id: uuid.UUID | None = None
    default_storage_location_id: uuid.UUID | None = None
    minimum_quantity: Dec3 | None = Field(default=None, ge=0)
    minimum_weight: Dec3 | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=500)
    nutrition: list[NutritionIn] | None = None


class UnitBrief(BaseModel):
    id: uuid.UUID
    name: str
    symbol: str
    dimension: str


class CategoryBrief(BaseModel):
    id: uuid.UUID
    name: str
    parent_name: str | None = None
    path: str = ""          # 形如「肉类 · 常见食材」


class IngredientListItem(ORMBase):
    id: uuid.UUID
    name: str
    category_id: uuid.UUID | None = None
    category_path: str = ""
    image_url: str | None = None
    quantity_unit: UnitBrief | None = None
    weight_unit: UnitBrief | None = None
    unit_weight_display: str = ""      # 250g 或「未设置」
    minimum_stock_display: str = ""
    location_name: str | None = None
    is_active: bool
    updated_at: datetime | None = None


class IngredientDetail(IngredientListItem):
    brand: str = ""
    specification: str = ""
    note: str = ""
    nutrition_basis_display: str = ""     # 每100g
    default_unit_weight: Dec3 | None = None
    minimum_quantity: Dec3 | None = None
    minimum_weight: Dec3 | None = None
    can_convert: bool = False             # 是否存在数量↔重量换算关系
    barcodes: list[BarcodeIn] = Field(default_factory=list)
    nutrition: list[dict] = Field(default_factory=list)
    created_at: datetime | None = None


class IngredientQuery(BaseModel):
    q: str | None = None
    category_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    is_active: bool | None = None
    only_low_stock: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    sort_by: str = Field(default="updated_at", pattern="^(name|updated_at|created_at)$")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")


class NutritionReplace(BaseModel):
    """PUT /ingredients/{id}/nutrition：整体替换「当前版本」营养档案。"""

    items: list[NutritionIn] = Field(default_factory=list, max_length=12)
