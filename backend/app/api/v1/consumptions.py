"""消耗域接口（M4）：单笔/批量消耗、列表、详情、撤销。

路由注册顺序有意为之：`/batch` 必须在 `/{consumption_id}` 之前，
否则 "batch" 会被当作 UUID 解析而返回 400（阶段 2 的分类 /sort 踩过同一个问题）。

批量消耗与单笔消耗共用同一请求事务：任一子项失败 → 抛异常 → session 关闭时
整体回滚，不产生任何部分流水（PRD §7.1 用例 9）。
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.core.errors import not_found
from app.db.session import get_db
from app.models import (
    Batch,
    ConsumptionNutrition,
    ConsumptionRecord,
    NutritionDefinition,
    TransactionAllocation,
)
from app.schemas.common import ok
from app.schemas.consumption import (
    BatchConsumptionIn,
    ConsumptionDetail,
    ConsumptionIn,
    ConsumptionResult,
    ReverseIn,
)
from app.services.consumption import consume as do_consume
from app.services.consumption import reverse as do_reverse

router = APIRouter(prefix="/consumptions", tags=["consumptions"])


def _out(db: Session, record: ConsumptionRecord) -> dict:
    """把消耗单 ORM 转成 JSON 安全的输出（含分配明细与营养快照）。"""
    from app.models import Ingredient

    ing = db.get(Ingredient, record.ingredient_id)
    alloc_rows = db.execute(
        select(TransactionAllocation, Batch)
        .join(Batch, Batch.id == TransactionAllocation.batch_id)
        .where(TransactionAllocation.transaction_id == record.transaction_id)
    ).all()
    allocations = [
        {
            "batch_id": a.batch_id,
            "batch_no": b.batch_no,
            "quantity_delta": a.quantity_delta,
            "weight_delta": a.weight_delta,
            "cost_delta": a.cost_delta,
            "unit_cost": a.unit_cost,
            # 详情展示的是批次**当前**余额（撤销后也会变化）
            "batch_remaining_quantity": b.remaining_quantity,
            "batch_remaining_weight": b.remaining_weight,
            "batch_remaining_cost": b.remaining_cost,
        }
        for a, b in alloc_rows
    ]
    nutri_rows = db.execute(
        select(ConsumptionNutrition, NutritionDefinition)
        .join(NutritionDefinition, NutritionDefinition.id == ConsumptionNutrition.nutrition_definition_id)
        .where(ConsumptionNutrition.consumption_id == record.id)
    ).all()
    nutrition = [
        {
            "code": d.code,
            "name": d.name,
            "actual_value": n.actual_value,
            "unit": n.unit,
            "basis_snapshot": n.basis_snapshot,
        }
        for n, d in nutri_rows
    ]
    data = {
        **{c: getattr(record, c) for c in (
            "id", "consumption_no", "ingredient_id", "quantity", "weight", "cost",
            "consumed_at", "note", "status", "created_at",
        )},
        "ingredient_name": ing.name if ing else "",
        "allocations": allocations,
        "nutrition": nutrition,
    }
    return ConsumptionDetail.model_validate(data).model_dump(mode="json")


@router.post("", status_code=201, summary="记录消耗（FEFO 自动分配）")
def create_consumption(
    payload: ConsumptionIn,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = do_consume(
        db,
        ingredient_id=payload.ingredient_id,
        weight=payload.weight,
        quantity=payload.quantity,
        batch_ids=payload.batch_ids,
        consumed_at=payload.consumed_at,
        note=payload.note,
        idempotency_key=payload.idempotency_key or request.headers.get("idempotency-key"),
        device_id=auth.device.id,
    )
    db.commit()
    return ok(request, ConsumptionResult.model_validate(data).model_dump(mode="json"), message="已记录消耗")


@router.post("/batch", status_code=201, summary="批量消耗（整批成功或整批回滚）")
def create_batch_consumptions(
    payload: BatchConsumptionIn,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    results = []
    for item in payload.items:
        results.append(
            do_consume(
                db,
                ingredient_id=item.ingredient_id,
                weight=item.weight,
                quantity=item.quantity,
                batch_ids=item.batch_ids,
                consumed_at=item.consumed_at or payload.consumed_at,
                note=item.note or payload.note,
                idempotency_key=item.idempotency_key,
                device_id=auth.device.id,
            )
        )
    db.commit()
    return ok(
        request,
        {"items": [ConsumptionResult.model_validate(r).model_dump(mode="json") for r in results],
         "total": len(results)},
        message=f"已记录 {len(results)} 笔消耗",
    )


@router.get("", summary="消耗记录列表")
def list_consumptions(
    request: Request,
    ingredient_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(completed|reversed)$"),
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    stmt = select(ConsumptionRecord)
    if ingredient_id:
        stmt = stmt.where(ConsumptionRecord.ingredient_id == ingredient_id)
    if status:
        stmt = stmt.where(ConsumptionRecord.status == status)
    if from_date:
        stmt = stmt.where(ConsumptionRecord.consumed_at >= from_date)
    if to_date:
        stmt = stmt.where(ConsumptionRecord.consumed_at <= to_date)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = db.scalars(
        stmt.order_by(ConsumptionRecord.consumed_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ok(request, {
        "items": [_out(db, r) for r in rows],
        "total": total, "page": page, "page_size": page_size,
    })


@router.get("/{consumption_id}", summary="消耗详情（含批次分配与营养快照）")
def consumption_detail(
    request: Request,
    consumption_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    record = db.get(ConsumptionRecord, consumption_id)
    if record is None:
        raise not_found("消耗记录不存在")
    return ok(request, _out(db, record))


@router.post("/{consumption_id}/reverse", status_code=201, summary="撤销消耗（反向流水）")
def reverse_consumption(
    request: Request,
    consumption_id: uuid.UUID,
    payload: ReverseIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = do_reverse(
        db, consumption_id=consumption_id, reason=payload.reason, device_id=auth.device.id
    )
    db.commit()
    return ok(request, data, message="已撤销，库存已恢复")
