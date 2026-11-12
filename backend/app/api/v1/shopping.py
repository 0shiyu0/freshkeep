"""采购清单接口（阶段 8.13）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.db.session import get_db
from app.schemas.common import ok
from app.schemas.recipe import ShoppingItemPatchIn, ShoppingListFromRecipesIn
from app.services import recipes as svc

router = APIRouter(prefix="/shopping-lists", tags=["shopping"])


@router.post("/from-recipes", status_code=201, summary="按菜谱合并生成采购清单")
def from_recipes(
    request: Request,
    payload: ShoppingListFromRecipesIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    """需求相加后减库存，只保留缺口；不产生任何库存变动。"""
    data = svc.build_shopping_list(
        db,
        recipe_ids=payload.recipe_ids,
        servings_map=payload.servings_map,
        name=payload.name,
    )
    db.commit()
    return ok(request, data, "采购清单已生成")


@router.get("", summary="采购清单列表")
def list_lists(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    return ok(request, svc.list_shopping_lists(db, page=page, page_size=page_size))


@router.get("/{list_id}", summary="采购清单详情")
def get_list(
    request: Request,
    list_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    return ok(request, svc.get_shopping_list(db, list_id))


@router.post("/from-low-stock", status_code=201, summary="按低库存建议生成采购清单")
def from_low_stock(
    request: Request,
    name: str = "",
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = svc.build_from_low_stock(db, name=name)
    db.commit()
    return ok(request, data, "采购清单已生成")


@router.post("/{list_id}/complete", summary="整单标记完成")
def complete(
    request: Request,
    list_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = svc.complete_list(db, list_id)
    db.commit()
    return ok(request, data, "清单已完成")


# 清单项用独立前缀，避免与 /{list_id} 的 UUID 解析冲突
items_router = APIRouter(prefix="/shopping-list-items", tags=["shopping"])


@items_router.patch("/{item_id}", summary="勾选/取消清单项")
def patch_item(
    request: Request,
    item_id: uuid.UUID,
    payload: ShoppingItemPatchIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = svc.set_item_completed(db, item_id, payload.is_completed)
    db.commit()
    return ok(request, data)


@router.post("/{list_id}/import", summary="清单一键入库（成本按最近单价估算）")
def import_list(
    request: Request,
    list_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    """逐项走五步事务入库；完成后清单自动标记 completed。"""
    data = svc.import_shopping_list(db, list_id, device_id=auth.device.id)
    db.commit()
    return ok(request, data, f"已入库 {len(data['batches'])} 个批次")
