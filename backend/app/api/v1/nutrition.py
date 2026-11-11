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
from app.schemas.dashboard import TargetsIn

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


# ---------------------------------------------------------------- 营养目标（M6）


@router.get("/targets", summary="当前生效的营养目标")
def get_targets(
    request: Request,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    from app.schemas.dashboard import TargetsOut
    from app.services.dashboard import list_targets

    rows = list_targets(db)
    return ok(request, TargetsOut.model_validate({"items": rows}).model_dump(mode="json"))


@router.put("/targets", summary="设置营养目标（同日重复设置覆盖）")
def put_targets(
    request: Request,
    payload: TargetsIn,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    from app.services.dashboard import upsert_targets

    n = upsert_targets(db, payload.items)
    return ok(request, {"updated": n}, "营养目标已保存")
