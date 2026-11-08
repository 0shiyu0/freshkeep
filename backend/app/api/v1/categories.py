"""食材分类：增删改查与排序（两级，同级不重名）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.core.errors import conflict, not_found, validation_error
from app.db.session import get_db
from app.models import Category, Ingredient
from app.schemas.catalog import CategoryIn, CategoryOut, CategorySortIn, CategoryUpdate
from app.schemas.common import ok

router = APIRouter(prefix="/categories", tags=["catalog"])


def _counts(db: Session) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Ingredient.category_id, func.count())
        .where(Ingredient.category_id.is_not(None))
        .group_by(Ingredient.category_id)
    ).all()
    return {cid: n for cid, n in rows if cid}


def _to_out(cat: Category, parent_name: str | None, counts: dict[uuid.UUID, int]) -> CategoryOut:
    return CategoryOut(
        id=cat.id,
        name=cat.name,
        parent_id=cat.parent_id,
        parent_name=parent_name,
        sort_order=cat.sort_order,
        is_active=cat.is_active,
        ingredient_count=counts.get(cat.id, 0),
    )


@router.get("", summary="分类列表（默认按父级→排序号返回）")
def list_categories(
    request: Request,
    include_inactive: bool = False,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Category).order_by(Category.parent_id.nulls_first(), Category.sort_order, Category.name)
    if not include_inactive:
        stmt = stmt.where(Category.is_active.is_(True))
    rows = db.execute(stmt).scalars().all()

    name_by_id = {c.id: c.name for c in rows}
    # 父级可能被过滤掉（停用），单独补查
    missing = {c.parent_id for c in rows if c.parent_id and c.parent_id not in name_by_id}
    if missing:
        for cid, name in db.execute(
            select(Category.id, Category.name).where(Category.id.in_(missing))
        ).all():
            name_by_id[cid] = name

    counts = _counts(db)
    items = [_to_out(c, name_by_id.get(c.parent_id), counts).model_dump(mode="json") for c in rows]
    return ok(request, {"items": items, "total": len(items)})


@router.post("", status_code=201, summary="新建分类")
def create_category(
    request: Request,
    payload: CategoryIn,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    if payload.parent_id is not None:
        parent = db.get(Category, payload.parent_id)
        if parent is None:
            raise not_found("父分类不存在")
        if parent.parent_id is not None:
            raise validation_error("最多支持两级分类，不能在子分类下继续建子分类")
    cat = Category(**payload.model_dump())
    db.add(cat)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("同级分类已存在同名项") from None
    return ok(request, _to_out(cat, None, {}).model_dump(mode="json"), "分类已创建")


@router.put("/sort", summary="批量调整排序")
def sort_categories(
    request: Request,
    payload: CategorySortIn,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    ids = [item.id for item in payload.items]
    rows = db.execute(select(Category).where(Category.id.in_(ids))).scalars().all()
    found = {c.id: c for c in rows}
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise not_found(f"分类不存在：{', '.join(missing[:3])}")
    for item in payload.items:
        found[item.id].sort_order = item.sort_order
    db.commit()
    return ok(request, {"updated": len(payload.items)}, "排序已保存")


@router.put("/{category_id}", summary="修改分类")
def update_category(
    request: Request,
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    cat = db.get(Category, category_id)
    if cat is None:
        raise not_found("分类不存在")

    data = payload.model_dump(exclude_unset=True)
    if "parent_id" in data and data["parent_id"] == category_id:
        raise validation_error("分类不能作为自己的父级")
    if "parent_id" in data and data["parent_id"] is not None:
        parent = db.get(Category, data["parent_id"])
        if parent is None:
            raise not_found("父分类不存在")
        if parent.parent_id is not None:
            raise validation_error("最多支持两级分类")
        has_child = db.execute(
            select(func.count()).select_from(Category).where(Category.parent_id == category_id)
        ).scalar_one()
        if has_child:
            raise conflict("该分类下已有子分类，不能再挂到别的父级")

    for key, value in data.items():
        setattr(cat, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("同级分类已存在同名项") from None
    parent_name = db.get(Category, cat.parent_id).name if cat.parent_id else None
    return ok(request, _to_out(cat, parent_name, _counts(db)).model_dump(mode="json"), "已保存")


@router.delete("/{category_id}", summary="删除分类（有子分类或食材时拒绝）")
def delete_category(
    request: Request,
    category_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    cat = db.get(Category, category_id)
    if cat is None:
        raise not_found("分类不存在")
    child = db.execute(
        select(func.count()).select_from(Category).where(Category.parent_id == category_id)
    ).scalar_one()
    if child:
        raise conflict("该分类下还有子分类，请先删除子分类")
    used = db.execute(
        select(func.count()).select_from(Ingredient).where(Ingredient.category_id == category_id)
    ).scalar_one()
    if used:
        raise conflict(f"该分类下还有 {used} 个食材，不能删除；可改为停用")
    db.delete(cat)
    db.commit()
    return ok(request, {"deleted": True}, "分类已删除")
