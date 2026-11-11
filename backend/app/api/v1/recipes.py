"""菜谱接口（阶段 8.11 / 8.12）。"""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.db.session import get_db
from app.schemas.common import ok
from app.schemas.recipe import RecipeIn
from app.services import recipes as svc

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.get("", summary="菜谱列表")
def list_recipes(
    request: Request,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    return ok(request, svc.list_recipes(db, q=q, page=page, page_size=page_size))


@router.post("", status_code=201, summary="新建菜谱")
def create_recipe(
    request: Request,
    payload: RecipeIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = svc.create_recipe(db, payload)
    db.commit()
    return ok(request, data, "菜谱已创建")


@router.get("/{recipe_id}", summary="菜谱详情（含食材与当前库存）")
def get_recipe(
    request: Request,
    recipe_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    return ok(request, svc.get_recipe(db, recipe_id))


@router.put("/{recipe_id}", summary="更新菜谱（整体替换食材）")
def update_recipe(
    request: Request,
    recipe_id: uuid.UUID,
    payload: RecipeIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = svc.update_recipe(db, recipe_id, payload)
    db.commit()
    return ok(request, data, "菜谱已更新")


@router.delete("/{recipe_id}", summary="删除菜谱")
def delete_recipe(
    request: Request,
    recipe_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    svc.delete_recipe(db, recipe_id)
    db.commit()
    return ok(request, {"deleted": True}, "菜谱已删除")


@router.get("/{recipe_id}/match", summary="按现有库存匹配（可指定份数）")
def match_recipe(
    request: Request,
    recipe_id: uuid.UUID,
    servings: Decimal | None = Query(default=None, gt=0, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    return ok(request, svc.match(db, recipe_id, servings=servings))
