"""菜谱与采购清单请求模型（阶段 8.11 / 8.13）。"""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.schemas.common import Dec3
from pydantic import BaseModel, Field


class RecipeItemIn(BaseModel):
    ingredient_id: uuid.UUID
    weight: Dec3 | None = Field(default=None, ge=0)
    quantity: Dec3 | None = Field(default=None, ge=0)
    unit_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=100)


class RecipeStepIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)


class RecipeIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category: str = Field(default="", max_length=40)
    servings: Dec3 = Field(default=Decimal("1"), gt=0, le=100)
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    # 兼容：字符串按行拆分；数组按结构化存（阶段 8 收尾起推荐数组）
    steps: str | list[RecipeStepIn] = Field(default="")
    note: str = Field(default="", max_length=500)
    items: list[RecipeItemIn] = Field(min_length=1, max_length=50)


class ShoppingListFromRecipesIn(BaseModel):
    recipe_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    servings_map: dict[str, str] | None = None
    name: str = Field(default="", max_length=80)


class ShoppingItemPatchIn(BaseModel):
    is_completed: bool
