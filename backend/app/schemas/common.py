"""通用类型：数值一律按字符串输出（前端不做浮点运算）。"""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, PlainSerializer

# 金额 2 位、数量/重量 3 位、营养 4 位；序列化为字符串，避免 JS 浮点误差
# when_used="json" 很关键：model_dump()（python 模式）必须返回 Decimal，
# 否则内部计算会拿到字符串（曾导致 `unit_weight <= 0` 抛 TypeError）。
_ser = lambda fmt: PlainSerializer(  # noqa: E731
    lambda v: None if v is None else format(v, fmt), return_type=str | None, when_used="json"
)

Dec2 = Annotated[Decimal, _ser(".2f")]
Dec3 = Annotated[Decimal, _ser(".3f")]
Dec4 = Annotated[Decimal, _ser(".4f")]


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PageMeta(BaseModel):
    total: int
    page: int
    page_size: int


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


def ok(request, data: Any, message: str = "") -> dict:
    """统一成功信封（docs/api.md §1.2）。"""
    return {
        "success": True,
        "data": data,
        "message": message,
        "request_id": getattr(request.state, "request_id", ""),
    }
