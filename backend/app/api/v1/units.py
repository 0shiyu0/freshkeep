"""计量单位与储存位置：字典维护 + 引用计数保护。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.core.errors import conflict, not_found
from app.db.session import get_db
from app.models import Ingredient, StorageLocation, Unit
from app.schemas.catalog import (
    LocationIn,
    LocationOut,
    LocationUpdate,
    UnitIn,
    UnitOut,
    UnitUpdate,
)
from app.schemas.common import ok

unit_router = APIRouter(prefix="/units", tags=["catalog"])
loc_router = APIRouter(prefix="/storage-locations", tags=["catalog"])


# ---------------------------------------------------------------- 单位


def _unit_usage(db: Session) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Ingredient.default_quantity_unit_id, func.count()).group_by(
            Ingredient.default_quantity_unit_id
        )
    ).all()
    rows += db.execute(
        select(Ingredient.default_weight_unit_id, func.count()).group_by(
            Ingredient.default_weight_unit_id
        )
    ).all()
    usage: dict[uuid.UUID, int] = {}
    for uid, n in rows:
        if uid:
            usage[uid] = usage.get(uid, 0) + n
    return usage


@unit_router.get("", summary="单位列表（可按维度过滤）")
def list_units(
    request: Request,
    dimension: str | None = None,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Unit).order_by(Unit.dimension, Unit.name)
    if dimension:
        stmt = stmt.where(Unit.dimension == dimension)
    rows = db.execute(stmt).scalars().all()
    usage = _unit_usage(db)
    items = [
        UnitOut(
            id=u.id,
            name=u.name,
            symbol=u.symbol,
            dimension=u.dimension,
            precision=u.precision,
            is_system=u.is_system,
            usage_count=usage.get(u.id, 0),
        ).model_dump(mode="json")
        for u in rows
    ]
    return ok(request, {"items": items, "total": len(items)})


@unit_router.post("", status_code=201, summary="新建单位")
def create_unit(
    request: Request,
    payload: UnitIn,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    unit = Unit(**payload.model_dump())
    db.add(unit)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("单位名称已存在") from None
    return ok(request, UnitOut.model_validate(unit).model_dump(mode="json"), "单位已创建")


@unit_router.put("/{unit_id}", summary="修改单位")
def update_unit(
    request: Request,
    unit_id: uuid.UUID,
    payload: UnitUpdate,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise not_found("单位不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(unit, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("单位名称已存在") from None
    return ok(request, UnitOut.model_validate(unit).model_dump(mode="json"), "已保存")


@unit_router.delete("/{unit_id}", summary="删除单位（被引用时拒绝）")
def delete_unit(
    request: Request,
    unit_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise not_found("单位不存在")
    if unit.is_system:
        raise conflict("系统内置单位不可删除")
    used = db.execute(
        select(func.count())
        .select_from(Ingredient)
        .where(
            or_(
                Ingredient.default_quantity_unit_id == unit_id,
                Ingredient.default_weight_unit_id == unit_id,
                Ingredient.nutrition_basis_unit_id == unit_id,
            )
        )
    ).scalar_one()
    if used:
        raise conflict(f"该单位被 {used} 个食材引用，不能删除")
    db.delete(unit)
    db.commit()
    return ok(request, {"deleted": True}, "单位已删除")


# ---------------------------------------------------------------- 储存位置


@loc_router.get("", summary="储存位置列表")
def list_locations(
    request: Request,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        select(StorageLocation).order_by(StorageLocation.sort_order, StorageLocation.name)
    ).scalars().all()
    items = [LocationOut.model_validate(r).model_dump(mode="json") for r in rows]
    return ok(request, {"items": items, "total": len(items)})


@loc_router.post("", status_code=201, summary="新建储存位置")
def create_location(
    request: Request,
    payload: LocationIn,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    loc = StorageLocation(**payload.model_dump())
    db.add(loc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("位置名称已存在") from None
    return ok(request, LocationOut.model_validate(loc).model_dump(mode="json"), "位置已创建")


@loc_router.put("/{location_id}", summary="修改储存位置")
def update_location(
    request: Request,
    location_id: uuid.UUID,
    payload: LocationUpdate,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    loc = db.get(StorageLocation, location_id)
    if loc is None:
        raise not_found("储存位置不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(loc, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("位置名称已存在") from None
    return ok(request, LocationOut.model_validate(loc).model_dump(mode="json"), "已保存")


@loc_router.delete("/{location_id}", summary="删除储存位置（被引用时拒绝）")
def delete_location(
    request: Request,
    location_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    loc = db.get(StorageLocation, location_id)
    if loc is None:
        raise not_found("储存位置不存在")
    used = db.execute(
        select(func.count())
        .select_from(Ingredient)
        .where(Ingredient.default_storage_location_id == location_id)
    ).scalar_one()
    if used:
        raise conflict(f"该位置被 {used} 个食材引用，不能删除")
    db.delete(loc)
    db.commit()
    return ok(request, {"deleted": True}, "位置已删除")
