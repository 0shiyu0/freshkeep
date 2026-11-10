"""库存操作：盘点调整与报损（M5）。

同样遵守 AGENTS.md §4.2 五步事务：流水 → 分配 → 批次缓存 → 一致性断言。
区别只在业务语义：
- 盘点（`adjustment`）提交**实际值**，服务端反算 delta，可正可负；
- 报损（`spoilage`）按 FEFO 扣批次，只能为负。

盘盈的成本按批次**当前单位成本**计入；盘亏按单位成本扣减，
扣到归零时直接取剩余成本结清尾差（与消耗一致，避免残留分币）。
"""
from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import not_found, validation_error
from app.core.time import biz_today
from app.models import Batch, InventoryTransaction, TransactionAllocation
from app.services.consumption import resolve_measure
from app.services.inventory import fefo_order
from app.services.inventory.state import refresh_batch_status

Q2, Q3, Q4 = Decimal("0.01"), Decimal("0.001"), Decimal("0.0001")


def _q(v: Decimal, unit: Decimal) -> Decimal:
    return v.quantize(unit, rounding=ROUND_HALF_UP)


def _seq(db: Session, prefix: str) -> int:
    from sqlalchemy import func

    n = db.execute(
        select(func.count())
        .select_from(InventoryTransaction)
        .where(InventoryTransaction.transaction_no.like(f"{prefix}%"))
    ).scalar() or 0
    return n + 1


def _tx_no(db: Session, kind: str) -> str:
    day = biz_today().strftime("%Y%m%d")
    prefix = f"TX-{kind}-{day}"
    return f"{prefix}-{_seq(db, prefix):03d}"


def _lock_batch(db: Session, batch_id: uuid.UUID) -> Batch | None:
    """行锁取批次；`of=Batch` 避免 lazy="joined" 的 OUTER JOIN 冲突。"""
    return db.scalars(
        select(Batch).where(Batch.id == batch_id).with_for_update(of=Batch)
    ).first()


def _unit_cost(batch: Batch, dimension: str) -> Decimal:
    """当前单位成本（元/克 或 元/个）；批次已清零时回落到入库时的单位成本。"""
    if dimension == "weight":
        rem, init = batch.remaining_weight, batch.initial_weight
    else:
        rem, init = batch.remaining_quantity, batch.initial_quantity
    if rem and rem > 0:
        return _q(batch.remaining_cost / rem, Q4)
    if init and init > 0:
        return _q(batch.purchase_cost / init, Q4)
    return Decimal(0)


def _assert_consistent(tx: InventoryTransaction, allocs: list[tuple[Decimal, Decimal, Decimal]]) -> None:
    sq = sum(a[0] for a in allocs)
    sw = sum(a[1] for a in allocs)
    sc = sum(a[2] for a in allocs)
    if (sq, sw, sc) != (tx.quantity_delta, tx.weight_delta, tx.cost_delta):
        raise validation_error(
            "库存写入不变式校验失败：分配与流水不一致",
            allocated_quantity=str(sq), allocated_weight=str(sw), allocated_cost=str(sc),
        )


# ---------------------------------------------------------------- 盘点


def adjust_batch(
    db: Session,
    *,
    batch_id: uuid.UUID,
    actual_weight: Decimal | None,
    actual_quantity: Decimal | None,
    reason: str,
    device_id: uuid.UUID | None,
) -> dict:
    """盘点单个批次：提交实际值 → 反算 delta → 写 adjustment 流水 + 分配。"""
    if not reason.strip():
        raise validation_error("盘点必须填写原因（如「盘点」「化冻失水」）")
    if actual_weight is None and actual_quantity is None:
        raise validation_error("实际重量与实际数量至少填一项")

    batch = _lock_batch(db, batch_id)
    if batch is None:
        raise not_found("批次不存在")

    # 以重量为主维度计算成本；只改数量时按数量维度
    if actual_weight is not None:
        delta_w = _q(actual_weight - batch.remaining_weight, Q3)
        delta_q = Decimal(0)
        if actual_quantity is not None:
            delta_q = _q(actual_quantity - batch.remaining_quantity, Q3)
        dimension, delta = "weight", delta_w
    else:
        delta_w = Decimal(0)
        delta_q = _q(actual_quantity - batch.remaining_quantity, Q3)
        dimension, delta = "quantity", delta_q

    unit = _unit_cost(batch, dimension)
    base_remaining = batch.remaining_weight if dimension == "weight" else batch.remaining_quantity

    if delta == 0:
        cost_delta = Decimal(0)
    elif delta < 0 and -delta >= base_remaining:
        # 扣到归零：直接取剩余成本，结清尾差
        cost_delta = -batch.remaining_cost
    else:
        cost_delta = _q(delta * unit, Q2)

    # 缓存更新 + 状态机
    batch.remaining_weight = _q(batch.remaining_weight + delta_w, Q3)
    batch.remaining_quantity = _q(batch.remaining_quantity + delta_q, Q3)
    batch.remaining_cost = _q(batch.remaining_cost + cost_delta, Q2)

    # 盘盈会把剩余量抬到初始量之上，而 DDL 的 ck_batch_remaining_le_initial 要求
    # remaining <= initial。语义上盘盈 = 当初入库少记了，因此同步上调初始量与采购成本
    # （只升不降：用 max 保证不会抹掉已有记录）。
    if delta_w > 0:
        batch.initial_weight = max(batch.initial_weight, batch.remaining_weight)
    if delta_q > 0:
        batch.initial_quantity = max(batch.initial_quantity, batch.remaining_quantity)
    if cost_delta > 0:
        batch.purchase_cost = max(batch.purchase_cost, batch.remaining_cost)

    refresh_batch_status(batch)

    tx = InventoryTransaction(
        transaction_no=_tx_no(db, "A"),
        type="adjustment",
        ingredient_id=batch.ingredient_id,
        quantity_delta=delta_q,
        weight_delta=delta_w,
        cost_delta=cost_delta,
        related_object_type="batch",
        related_object_id=batch.id,
        reason=reason.strip(),
        device_id=device_id,
    )
    db.add(tx)
    db.flush()

    db.add(
        TransactionAllocation(
            transaction_id=tx.id,
            batch_id=batch.id,
            quantity_delta=delta_q,
            weight_delta=delta_w,
            cost_delta=cost_delta,
            unit_cost=unit if unit > 0 else None,
        )
    )
    db.flush()
    _assert_consistent(tx, [(delta_q, delta_w, cost_delta)])

    return {
        "transaction_id": tx.id,
        "transaction_no": tx.transaction_no,
        "batch_id": batch.id,
        "batch_no": batch.batch_no,
        "quantity_delta": delta_q,
        "weight_delta": delta_w,
        "cost_delta": cost_delta,
        "batch_remaining_weight": batch.remaining_weight,
        "batch_remaining_quantity": batch.remaining_quantity,
        "batch_remaining_cost": batch.remaining_cost,
        "status": batch.status,
    }


def stocktake(
    db: Session, *, items: list, device_id: uuid.UUID | None
) -> list[dict]:
    """批量盘点：任一项失败 → 抛异常，调用方事务整体回滚。"""
    return [
        adjust_batch(
            db,
            batch_id=item.batch_id,
            actual_weight=item.actual_weight,
            actual_quantity=item.actual_quantity,
            reason=item.reason or "盘点",
            device_id=device_id,
        )
        for item in items
    ]


# ---------------------------------------------------------------- 报损


def spoil(
    db: Session,
    *,
    ingredient_id: uuid.UUID,
    weight: Decimal | None,
    quantity: Decimal | None,
    reason: str,
    batch_ids: list[uuid.UUID] | None,
    device_id: uuid.UUID | None,
) -> dict:
    """报损：按 FEFO 扣批次，写 spoilage 流水（负 delta）。"""
    from app.core.errors import insufficient_stock
    from app.models import Ingredient

    if not reason.strip():
        raise validation_error("报损必须填写原因（如「变质」「过期」）")

    ingredient = db.get(Ingredient, ingredient_id)
    if ingredient is None:
        raise not_found("食材不存在")

    w_need, q_need, mode = resolve_measure(ingredient, weight, quantity)
    need = w_need if mode == "weight" else q_need

    base = select(Batch).where(
        Batch.ingredient_id == ingredient_id, Batch.status == "active"
    )
    locked = db.scalars(fefo_order(base).with_for_update(of=Batch)).unique().all()
    wanted = set(batch_ids) if batch_ids else None
    batches = [
        b for b in locked
        if (wanted is None or b.id in wanted)
        and ((b.remaining_weight if mode == "weight" else b.remaining_quantity) > 0)
    ]
    available = sum(
        (b.remaining_weight if mode == "weight" else b.remaining_quantity) for b in batches
    )
    if available < need:
        raise insufficient_stock(str(_q(need, Q3)), str(_q(available, Q3)), str(_q(need - available, Q3)))

    left = need
    plans: list[dict] = []
    for b in batches:
        if left <= 0:
            break
        base_amount = b.remaining_weight if mode == "weight" else b.remaining_quantity
        if base_amount <= 0:
            continue
        take = min(base_amount, left)
        unit_cost = _q(b.remaining_cost / base_amount, Q4)
        cost = b.remaining_cost if take == base_amount else _q(take * unit_cost, Q2)

        if mode == "weight":
            w_delta = _q(take, Q3)
            q_delta = (
                _q(take * b.remaining_quantity / b.remaining_weight, Q3)
                if b.remaining_weight > 0 else Decimal(0)
            )
            q_delta = min(q_delta, b.remaining_quantity)
        else:
            q_delta = _q(take, Q3)
            w_delta = (
                _q(take * b.remaining_weight / b.remaining_quantity, Q3)
                if b.remaining_quantity > 0 else Decimal(0)
            )
            w_delta = min(w_delta, b.remaining_weight)

        b.remaining_weight = _q(b.remaining_weight - w_delta, Q3)
        b.remaining_quantity = _q(b.remaining_quantity - q_delta, Q3)
        b.remaining_cost = _q(b.remaining_cost - cost, Q2)
        refresh_batch_status(b)

        plans.append({
            "batch": b, "quantity_delta": q_delta, "weight_delta": w_delta,
            "cost_delta": cost, "unit_cost": unit_cost,
        })
        left -= take

    if left > 0:
        raise insufficient_stock(str(_q(need, Q3)), str(_q(available, Q3)), str(_q(left, Q3)))

    total_q = _q(sum(p["quantity_delta"] for p in plans), Q3)
    total_w = _q(sum(p["weight_delta"] for p in plans), Q3)
    total_c = _q(sum(p["cost_delta"] for p in plans), Q2)

    tx = InventoryTransaction(
        transaction_no=_tx_no(db, "S"),
        type="spoilage",
        ingredient_id=ingredient_id,
        quantity_delta=-total_q,
        weight_delta=-total_w,
        cost_delta=-total_c,
        related_object_type="spoilage",
        reason=reason.strip(),
        device_id=device_id,
    )
    db.add(tx)
    db.flush()

    for p in plans:
        db.add(
            TransactionAllocation(
                transaction_id=tx.id,
                batch_id=p["batch"].id,
                quantity_delta=-p["quantity_delta"],
                weight_delta=-p["weight_delta"],
                cost_delta=-p["cost_delta"],
                unit_cost=p["unit_cost"],
            )
        )
    db.flush()
    _assert_consistent(
        tx, [(-p["quantity_delta"], -p["weight_delta"], -p["cost_delta"]) for p in plans]
    )

    return {
        "transaction_id": tx.id,
        "transaction_no": tx.transaction_no,
        "weight": total_w,
        "quantity": total_q,
        "cost": total_c,
        "allocations": [
            {
                "batch_id": p["batch"].id,
                "batch_no": p["batch"].batch_no,
                "weight_delta": -p["weight_delta"],
                "cost_delta": -p["cost_delta"],
                "batch_remaining_weight": p["batch"].remaining_weight,
                "batch_remaining_cost": p["batch"].remaining_cost,
            }
            for p in plans
        ],
    }
