"""AI 识别与商品源的请求模型（阶段 8）。"""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class RecognitionIn(BaseModel):
    """创建待确认草稿。`manual` 用于人工先填/粘贴，此时不调用视觉模型。"""

    image_file_id: uuid.UUID | None = None
    hint: str = Field(default="", max_length=100)
    manual: dict | None = None


class RecognitionPatch(BaseModel):
    patch: dict = Field(min_length=0)


class RecognitionConfirmIn(BaseModel):
    target: Literal["ingredient", "batch"]
    ingredient_id: uuid.UUID | None = None
    patch: dict | None = None


class ProviderSettingsIn(BaseModel):
    kind: str = Field(default="none", pattern="^(none|stub|openai_compatible)$")
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    enabled: bool = False
    timeout_seconds: int = Field(default=30, ge=3, le=120)


class ProductSourceIn(BaseModel):
    kind: str = Field(default="none", pattern="^(none|openfoodfacts|custom)$")
    base_url: str = ""
    api_key: str = ""
    enabled: bool = False
    timeout_seconds: int = Field(default=8, ge=3, le=60)
