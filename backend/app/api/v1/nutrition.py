"""营养项目字典（食材营养档案引用它）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.db.session import get_db
from app.models import NutritionDefinition
from app.schemas.catalog import NutritionDefinitionOut
from app.schemas.common import ok

router = APIRouter(prefix="/nutrition", tags=["catalog"])


@router.get("/definitions", summary="营养项目列表（热量、蛋白质、脂肪、碳水、膳食纤维、钠…）")
def definitions(
    request: Request,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        select(NutritionDefinition)
        .where(NutritionDefinition.is_active.is_(True))
        .order_by(NutritionDefinition.sort_order, NutritionDefinition.code)
    ).scalars().all()
    items = [NutritionDefinitionOut.model_validate(r).model_dump(mode="json") for r in rows]
    return ok(request, {"items": items, "total": len(items)})
