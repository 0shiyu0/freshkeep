"""批次域接口：入库、列表、详情、元数据修改、临期/过期查询（M3）。

规则（AGENTS.md §4.2 / PRD §4.4、§4.6）：
- POST /batches = 一次采购入库，服务层五步事务；
- PUT /batches/{id} 只允许改元数据；数量/成本/状态的直接修改一律 400
  （数量要走盘点，状态要走 services/inventory/state.py 状态机）；
- 幂等由 IdempotencyMiddleware 全局承担（写方法带 Idempotency-Key 时生效）。
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.core.errors import not_found, validation_error
from app.core.time import biz_today
from app.db.session import get_db
from app.models import Batch, StorageLocation
from app.schemas.batch import (
    BatchCreate,
    BatchMetaUpdate,
    BatchOut,
    TransactionBrief,
)
from app.schemas.common import ok
from app.services.inventory import create_batch, load_batch_out

router = APIRouter(prefix="/batches", tags=["batches"])

# PUT 明确拒绝的字段：改数量走盘点（POST /inventory/adjustments，M5），
# 改状态走状态机，改成本没有任何合法入口。
_FORBIDDEN_FIELDS = {
    "initial_quantity",
    "remaining_quantity",
    "initial_weight",
    "remaining_weight",
    "purchase_cost",
    "remaining_cost",
    "status",
    "batch_no",
}


@router.post("", status_code=201, summary="采购入库：新建批次")
def create_batch_endpoint(
    payload: BatchCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    batch, tx = create_batch(
        db,
        ingredient_id=payload.ingredient_id,
        purchase_date=payload.purchase_date,
        production_date=payload.production_date,
        expiry_date=payload.expiry_date,
        storage_location_id=payload.storage_location_id,
        quantity=payload.quantity,
        weight_in=payload.weight,
        purchase_cost=payload.purchase_cost,
        quantity_unit_id=payload.quantity_unit_id,
        weight_unit_id=payload.weight_unit_id,
        note=payload.note,
        device_id=auth.device.id,
    )
    db.commit()
    db.refresh(batch)
    return ok(
        request,
        {
            "batch": load_batch_out(db, batch),
            "transaction": TransactionBrief.model_validate(tx).model_dump(mode="json"),
        },
        message="入库成功",
    )


@router.get("", summary="批次列表")
def list_batches(
    request: Request,
    ingredient_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(active|depleted|void)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    stmt = select(Batch)
    if ingredient_id:
        stmt = stmt.where(Batch.ingredient_id == ingredient_id)
    if location_id:
        stmt = stmt.where(Batch.storage_location_id == location_id)
    if status:
        stmt = stmt.where(Batch.status == status)

    from sqlalchemy import func

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    stmt = stmt.order_by(Batch.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    batches = db.scalars(stmt).unique().all()

    return ok(
        request,
        {
            "items": [load_batch_out(db, b) for b in batches],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.get("/expiring", summary="临期批次（按剩余天数升序）")
def expiring_batches(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    """到期日在窗口内（含今天到期、不含已过期）、仍有库存、active 的批次。"""
    today = biz_today()
    from datetime import timedelta

    stmt = (
        select(Batch)
        .where(
            Batch.status == "active",
            Batch.expiry_date.is_not(None),
            Batch.expiry_date >= today,  # 已过期的走 /expired，不混进临期
            Batch.expiry_date <= today + timedelta(days=days),
        )
        .order_by(Batch.expiry_date.asc(), Batch.purchase_date)
    )
    batches = db.scalars(stmt).unique().all()
    return ok(request, {"items": [load_batch_out(db, b) for b in batches]})


@router.get("/expired", summary="已过期但仍有库存的批次")
def expired_batches(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    today = biz_today()
    stmt = (
        select(Batch)
        .where(
            Batch.status == "active",
            Batch.expiry_date.is_not(None),
            Batch.expiry_date < today,
        )
        .order_by(Batch.expiry_date.asc())
    )
    batches = db.scalars(stmt).unique().all()
    return ok(request, {"items": [load_batch_out(db, b) for b in batches]})


@router.get("/{batch_id}", summary="批次详情")
def batch_detail(
    request: Request,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise not_found("批次不存在")
    return ok(request, load_batch_out(db, batch))


@router.put("/{batch_id}", summary="修改批次元数据（数量与成本不可直接改）")
def update_batch_meta(
    request: Request,
    batch_id: uuid.UUID,
    payload: BatchMetaUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise not_found("批次不存在")

    # 请求里带禁改字段 → 400（比"默默忽略"更安全：让调用方知道走错入口）
    extra = set(payload.__pydantic_extra__ or {}) & _FORBIDDEN_FIELDS
    if extra:
        raise validation_error(
            "批次数量/成本/状态不允许直接修改：数量走盘点（POST /inventory/adjustments），"
            "状态由系统维护",
            fields=sorted(extra),
        )

    if payload.production_date and payload.expiry_date and payload.expiry_date < payload.production_date:
        raise validation_error("到期日期不能早于生产日期")

    if payload.storage_location_id and db.get(StorageLocation, payload.storage_location_id) is None:
        raise validation_error("储存位置不存在")

    # 只有显式传了的字段才生效（note 传 null 表示清空）
    data = payload.model_dump(exclude_unset=True)
    for field in ("purchase_date", "production_date", "expiry_date", "opened_date"):
        if field in data:
            setattr(batch, field, data[field])
    if "storage_location_id" in data:
        batch.storage_location_id = data["storage_location_id"]
    if "note" in data:
        batch.note = data["note"] or ""

    db.commit()
    db.refresh(batch)
    return ok(request, load_batch_out(db, batch), message="已更新")
