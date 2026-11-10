"""库存域接口（M5）：库存聚合、汇总、流水、盘点、批量盘点、报损。

约定：
- 列表响应统一 `data={items:[...], total, page, page_size}`（与阶段 2 一致）；
- 盘点提交**实际值**、服务端反算 delta（PRD §4.6）；
- 所有写操作走 services/inventory/ops.py 的五步事务，不在路由里改余额；
- SQL 一律参数化（AGENTS.md §9.5）。
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.core.time import biz_today, days_until
from app.db.session import get_db
from app.models import Ingredient, InventoryTransaction
from app.schemas.common import ok
from app.schemas.inventory import (
    AdjustmentIn,
    AdjustmentOut,
    InventoryRow,
    InventorySummary,
    SpoilageIn,
    SpoilageOut,
    StocktakeIn,
    StocktakeOut,
    TransactionRow,
)
from app.services.inventory.ops import adjust_batch, spoil, stocktake as do_stocktake

router = APIRouter(prefix="/inventory", tags=["inventory"])

_BASE_SELECT = """
SELECT v.ingredient_id, v.name, v.category_id, v.total_quantity, v.total_weight,
       v.total_cost, v.batch_count, v.nearest_expiry, v.is_low_stock,
       i.minimum_weight, i.minimum_quantity,
       c.name AS category_name, pc.name AS parent_name,
       wu.symbol AS weight_symbol, qu.name AS quantity_unit_name
  FROM v_inventory v
  JOIN ingredients i ON i.id = v.ingredient_id
  LEFT JOIN categories c ON c.id = i.category_id
  LEFT JOIN categories pc ON pc.id = c.parent_id
  LEFT JOIN units wu ON wu.id = i.default_weight_unit_id
  LEFT JOIN units qu ON qu.id = i.default_quantity_unit_id
 WHERE (CAST(:category_id AS uuid) IS NULL
        OR i.category_id = CAST(:category_id AS uuid)
        OR c.parent_id = CAST(:category_id AS uuid))
   AND (CAST(:low_stock AS boolean) = false OR v.is_low_stock = true)
   AND (i.name ILIKE COALESCE(CAST(:q_like AS text), i.name)
        OR i.name_pinyin ILIKE COALESCE(CAST(:q_like AS text), i.name_pinyin)
        OR i.name_initials = COALESCE(CAST(:q_raw AS text), i.name_initials))
   AND (CAST(:location_id AS uuid) IS NULL
        OR EXISTS (SELECT 1 FROM batches b
                    WHERE b.ingredient_id = i.id
                      AND b.storage_location_id = CAST(:location_id AS uuid)
                      AND b.status = 'active'
                      AND (b.remaining_weight > 0 OR b.remaining_quantity > 0)))
"""


@router.get("", summary="库存列表（读 v_inventory）")
def list_inventory(
    request: Request,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    is_low_stock: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    keyword = (q or "").strip()
    params = {
        "category_id": str(category_id) if category_id else None,
        "location_id": str(location_id) if location_id else None,
        "low_stock": is_low_stock,
        "q_like": f"%{keyword.lower()}%" if keyword else None,
        "q_raw": keyword.lower() if keyword else None,
    }

    count_sql = f"SELECT COUNT(*) FROM ({_BASE_SELECT}) t"  # noqa: S608 - SQL 为静态串，值全部参数化
    total = db.execute(text(count_sql), params).scalar() or 0

    rows = db.execute(
        text(
            _BASE_SELECT
            + " ORDER BY v.total_cost DESC, v.name LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).all()

    items = []
    for r in rows:
        path = " · ".join(x for x in (r.parent_name, r.category_name) if x) or "未分类"
        items.append(
            InventoryRow(
                ingredient_id=r.ingredient_id,
                name=r.name,
                category_id=r.category_id,
                category_path=path,
                total_quantity=r.total_quantity,
                total_weight=r.total_weight,
                total_cost=r.total_cost,
                batch_count=r.batch_count,
                nearest_expiry=r.nearest_expiry,
                days_to_expiry=days_until(r.nearest_expiry),
                is_low_stock=r.is_low_stock,
                minimum_weight=r.minimum_weight,
                minimum_quantity=r.minimum_quantity,
                weight_unit_symbol=r.weight_symbol,
                quantity_unit_name=r.quantity_unit_name,
            ).model_dump(mode="json")
        )
    return ok(request, {"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/summary", summary="库存汇总")
def inventory_summary(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    row = db.execute(
        text(
            "SELECT COALESCE(SUM(total_weight),0) AS w, COALESCE(SUM(total_cost),0) AS c, "
            "COALESCE(SUM(total_quantity),0) AS q, COUNT(*) AS n, "
            "COALESCE(SUM(batch_count),0) AS b, "
            "COUNT(*) FILTER (WHERE is_low_stock) AS low FROM v_inventory"
        )
    ).one()

    today = biz_today()
    from datetime import timedelta

    alive = (
        "status = 'active' AND (remaining_weight > 0 OR remaining_quantity > 0) "
        "AND expiry_date IS NOT NULL"
    )
    expiring = db.execute(
        text(
            f"SELECT COUNT(*) FROM batches WHERE {alive} "  # noqa: S608 - 静态串
            "AND expiry_date >= :today AND expiry_date <= :until"
        ),
        {"today": today, "until": today + timedelta(days=7)},
    ).scalar() or 0
    expired = db.execute(
        text(f"SELECT COUNT(*) FROM batches WHERE {alive} AND expiry_date < :today"),
        {"today": today},
    ).scalar() or 0

    return ok(
        request,
        InventorySummary(
            total_weight=row.w,
            total_cost=row.c,
            total_quantity=row.q,
            ingredient_count=row.n,
            batch_count=row.b,
            low_stock_count=row.low,
            expiring_count=expiring,
            expired_count=expired,
        ).model_dump(mode="json"),
    )


@router.get("/transactions", summary="全部库存流水")
def list_transactions(
    request: Request,
    type: str | None = Query(default=None, pattern="^(purchase|consume|spoilage|adjustment|reverse)$"),
    ingredient_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    from sqlalchemy import func, select

    stmt = select(InventoryTransaction, Ingredient.name).join(
        Ingredient, Ingredient.id == InventoryTransaction.ingredient_id
    )
    if type:
        stmt = stmt.where(InventoryTransaction.type == type)
    if ingredient_id:
        stmt = stmt.where(InventoryTransaction.ingredient_id == ingredient_id)
    if batch_id:
        # 一笔流水可能跨多个批次，按分配表反查它是否影响了该批次
        from app.models import TransactionAllocation

        stmt = stmt.where(
            InventoryTransaction.id.in_(
                select(TransactionAllocation.transaction_id).where(
                    TransactionAllocation.batch_id == batch_id
                )
            )
        )
    if from_date:
        stmt = stmt.where(InventoryTransaction.created_at >= from_date)
    if to_date:
        stmt = stmt.where(InventoryTransaction.created_at <= to_date)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = db.execute(
        stmt.order_by(InventoryTransaction.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()

    items = [
        TransactionRow(
            id=tx.id, transaction_no=tx.transaction_no, type=tx.type,
            ingredient_id=tx.ingredient_id, ingredient_name=name,
            quantity_delta=tx.quantity_delta, weight_delta=tx.weight_delta,
            cost_delta=tx.cost_delta, reason=tx.reason,
            related_object_type=tx.related_object_type,
            related_object_id=tx.related_object_id, created_at=tx.created_at,
        ).model_dump(mode="json")
        for tx, name in rows
    ]
    return ok(request, {"items": items, "total": total, "page": page, "page_size": page_size})


@router.post("/adjustments", status_code=201, summary="盘点调整（提交实际值）")
def create_adjustment(
    request: Request,
    payload: AdjustmentIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = adjust_batch(
        db,
        batch_id=payload.batch_id,
        actual_weight=payload.actual_weight,
        actual_quantity=payload.actual_quantity,
        reason=payload.reason,
        device_id=auth.device.id,
    )
    db.commit()
    return ok(request, AdjustmentOut.model_validate(data).model_dump(mode="json"), message="已调整")


@router.post("/stocktake", status_code=201, summary="批量盘点（整批事务）")
def create_stocktake(
    request: Request,
    payload: StocktakeIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    items = do_stocktake(db, items=payload.items, device_id=auth.device.id)
    db.commit()
    return ok(
        request,
        StocktakeOut(
            items=[AdjustmentOut.model_validate(i) for i in items]
        ).model_dump(mode="json"),
        message=f"已盘点 {len(items)} 个批次",
    )


@router.post("/spoilage", status_code=201, summary="报损（FEFO 扣批次）")
def create_spoilage(
    request: Request,
    payload: SpoilageIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    data = spoil(
        db,
        ingredient_id=payload.ingredient_id,
        weight=payload.weight,
        quantity=payload.quantity,
        reason=payload.reason,
        batch_ids=payload.batch_ids,
        device_id=auth.device.id,
    )
    db.commit()
    return ok(request, SpoilageOut.model_validate(data).model_dump(mode="json"), message="已报损")
