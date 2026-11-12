"""消耗域服务（M4，风险最高的一层）。

不变式（AGENTS.md §4.2 / PRD §5.1~5.5）：
1. 消耗 = 一个事务内的 `consume` 流水 + 每个批次一条分配 + 批次缓存更新 + 一致性断言；
2. FEFO 取批次带 `FOR UPDATE` 行锁，排序固定（到期日 → 购买日 → id），防并发超卖与死锁；
3. 全程 Decimal，成本按批次剩余成本分摊，**扣完时直接取剩余成本结清尾差**；
4. 多批次分摊成本之和 == 单据成本；库存不足整体回滚，不留部分流水；
5. 营养在消耗发生时快照（冻结基准值），后续改营养档案不影响历史；
6. 撤销走 `reverse` 反向流水，不物理删除任何记录。

双计量（ARCHITECTURE §7.3 / PRD §5.3）：
- 只给重量：有换算关系时按换算补齐数量，无换算关系时数量 delta 记 0；
- 只给数量：有换算关系时换算成重量；无换算关系时**按数量维度消耗**，不推算重量；
- 两者都给：有换算关系则校验自洽，无换算关系则两个维度各自独立记录。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.core.errors import (
    ApiError,
    conflict,
    inconsistent_measure,
    insufficient_stock,
    not_found,
    validation_error,
)
from app.core.time import biz_today
from app.models import (
    Batch,
    ConsumptionNutrition,
    ConsumptionRecord,
    Ingredient,
    IngredientNutrition,
    InventoryTransaction,
    NutritionDefinition,
    TransactionAllocation,
    Unit,
)
from app.services.consumption.state import mark_reversed
from app.services.inventory import fefo_order
from app.services.inventory.state import refresh_batch_status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

Q2, Q3, Q4 = Decimal("0.01"), Decimal("0.001"), Decimal("0.0001")


def _q(v: Decimal, unit: Decimal) -> Decimal:
    return v.quantize(unit, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- 双计量解析


def resolve_measure(
    ingredient: Ingredient, weight_in: Decimal | None, quantity_in: Decimal | None
) -> tuple[Decimal, Decimal, str]:
    """返回 (weight_need, quantity_need, mode)；mode = 'weight' | 'quantity'。"""
    w = weight_in or Decimal(0)
    qty = quantity_in or Decimal(0)
    if w <= 0 and qty <= 0:
        raise validation_error("重量与数量至少填写一项")

    uw: Decimal | None = ingredient.default_unit_weight

    if w > 0 and qty > 0:
        # 两个维度都明确给了：有换算关系就校验自洽，没有就各记各的（不推算）
        if uw is not None and abs(w - qty * uw) > Q3:
            raise inconsistent_measure(
                f"数量 {qty} × 每单位 {uw} 克 = {_q(qty * uw, Q3)} 克，与重量 {w} 克不一致"
            )
        return _q(w, Q3), _q(qty, Q3), "weight"

    if w > 0:
        derived_qty = _q(w / uw, Q3) if uw is not None else Decimal(0)
        return _q(w, Q3), derived_qty, "weight"

    # 只给数量
    if uw is not None:
        return _q(qty * uw, Q3), _q(qty, Q3), "weight"
    # 无换算关系：按数量维度消耗，重量 delta = 0（不推算）
    return Decimal(0), _q(qty, Q3), "quantity"


# ---------------------------------------------------------------- 编号


def _seq(db: Session, prefix: str, column, table) -> int:
    n = db.execute(
        select(func.count()).select_from(table).where(column.like(f"{prefix}%"))
    ).scalar() or 0
    return n + 1


# ---------------------------------------------------------------- 核心消耗


def consume(
    db: Session,
    *,
    ingredient_id: uuid.UUID,
    weight: Decimal | None,
    quantity: Decimal | None,
    batch_ids: list[uuid.UUID] | None,
    consumed_at: datetime | None,
    note: str,
    idempotency_key: str | None,
    device_id: uuid.UUID | None,
) -> dict:
    """单食材消耗：FEFO 分配 + 成本核算 + 营养快照，全部在**调用方的事务**里。

    返回可直接序列化的 dict（consumption / allocations / nutrition）。
    """
    ingredient = db.get(Ingredient, ingredient_id)
    if ingredient is None:
        raise not_found("食材不存在")

    w_need, q_need, mode = resolve_measure(ingredient, weight, quantity)
    need = w_need if mode == "weight" else q_need

    # ---- FEFO 取批次并加行锁（锁顺序固定，避免交叉死锁）
    base = select(Batch).where(
        Batch.ingredient_id == ingredient_id, Batch.status == "active"
    )
    # Batch 的 ingredient / storage_location 是 lazy="joined"（LEFT OUTER JOIN），
    # PostgreSQL 不允许 FOR UPDATE 作用于外连接的可空侧，因此显式限定只锁 batches 表。
    locked = db.scalars(
        fefo_order(base).with_for_update(of=Batch)
    ).unique().all()
    wanted = set(batch_ids) if batch_ids else None
    batches = [
        b for b in locked
        if (wanted is None or b.id in wanted)
        and ((b.remaining_weight if mode == "weight" else b.remaining_quantity) > 0)
    ]
    available = sum(
        (b.remaining_weight if mode == "weight" else b.remaining_quantity)
        for b in batches
    )
    if available < need:
        raise insufficient_stock(
            str(_q(need, Q3)), str(_q(available, Q3)), str(_q(need - available, Q3))
        )
    if wanted and any(bid not in {b.id for b in locked} for bid in wanted):
        raise validation_error("指定的批次不存在或已耗尽")

    # ---- 分配循环（按 FEFO 顺序，逐批扣减）
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
        # 尾差结清：本批次被扣完时成本直接取剩余成本
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

        # 第 3 步：更新批次缓存 + 状态机
        b.remaining_weight = _q(b.remaining_weight - w_delta, Q3)
        b.remaining_quantity = _q(b.remaining_quantity - q_delta, Q3)
        b.remaining_cost = _q(b.remaining_cost - cost, Q2)
        refresh_batch_status(b)

        plans.append({
            "batch": b, "batch_no": b.batch_no,
            "quantity_delta": q_delta, "weight_delta": w_delta,
            "cost_delta": cost, "unit_cost": unit_cost,
        })
        left -= take

    if left > 0:  # 理论上不会发生（可用量已校验），留作防御
        raise insufficient_stock(str(_q(need, Q3)), str(_q(available, Q3)), str(_q(left, Q3)))

    total_q = _q(sum(p["quantity_delta"] for p in plans), Q3)
    total_w = _q(sum(p["weight_delta"] for p in plans), Q3)
    total_c = _q(sum(p["cost_delta"] for p in plans), Q2)

    day = biz_today().strftime("%Y%m%d")
    # ---- 第 1 步：流水（consume 只能为负，DDL ck_tx_sign 兜底）
    tx = InventoryTransaction(
        transaction_no=f"TX-C-{day}-{_seq(db, f'TX-C-{day}', InventoryTransaction.transaction_no, InventoryTransaction):03d}",
        type="consume",
        ingredient_id=ingredient_id,
        quantity_delta=-total_q,
        weight_delta=-total_w,
        cost_delta=-total_c,
        related_object_type="consumption",
        device_id=device_id,
    )
    db.add(tx)
    db.flush()

    # ---- 业务单据
    record = ConsumptionRecord(
        consumption_no=f"CS-{day}-{_seq(db, f'CS-{day}', ConsumptionRecord.consumption_no, ConsumptionRecord):03d}",
        ingredient_id=ingredient_id,
        transaction_id=tx.id,
        quantity=total_q,
        weight=total_w,
        quantity_unit_id=ingredient.default_quantity_unit_id if total_q > 0 else None,
        weight_unit_id=ingredient.default_weight_unit_id if total_w > 0 else None,
        cost=total_c,
        consumed_at=consumed_at or datetime.now(UTC),
        note=note,
        status="completed",
        device_id=device_id,
        idempotency_key=idempotency_key,
    )
    db.add(record)
    db.flush()
    tx.related_object_id = record.id

    # ---- 第 2 步：每批次一条分配
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

    # ---- 第 4 步（AGENTS §4.2 第 5 条）：不变式断言
    if (
        sum(p["quantity_delta"] for p in plans) != total_q
        or sum(p["weight_delta"] for p in plans) != total_w
        or sum(p["cost_delta"] for p in plans) != total_c
    ):
        raise validation_error("库存写入不变式校验失败：消耗分配与流水不一致")

    # ---- 营养快照（冻结，不随档案变化）
    nutrition = _write_nutrition(db, record.id, ingredient_id, total_w)
    db.flush()

    return {
        "consumption": {
            "id": record.id,
            "consumption_no": record.consumption_no,
            "ingredient_id": ingredient_id,
            "ingredient_name": ingredient.name,
            "quantity": total_q,
            "weight": total_w,
            "cost": total_c,
            "consumed_at": record.consumed_at,
            "note": record.note,
            "status": record.status,
            "created_at": record.created_at,
        },
        "allocations": [
            {
                "batch_id": p["batch"].id,
                "batch_no": p["batch_no"],
                "quantity_delta": -p["quantity_delta"],
                "weight_delta": -p["weight_delta"],
                "cost_delta": -p["cost_delta"],
                "unit_cost": p["unit_cost"],
                "batch_remaining_quantity": p["batch"].remaining_quantity,
                "batch_remaining_weight": p["batch"].remaining_weight,
                "batch_remaining_cost": p["batch"].remaining_cost,
            }
            for p in plans
        ],
        "nutrition": nutrition,
    }


def _write_nutrition(
    db: Session, consumption_id: uuid.UUID, ingredient_id: uuid.UUID, weight: Decimal
) -> list[dict]:
    """消耗发生时冻结营养基准；后续改档案不会改这些行。"""
    if weight <= 0:
        return []  # 纯数量消耗没有重量，营养按重量估算无意义

    rows = db.scalars(
        select(IngredientNutrition).where(
            IngredientNutrition.ingredient_id == ingredient_id,
            IngredientNutrition.is_current.is_(True),
        )
    ).all()
    out: list[dict] = []
    for n in rows:
        basis_unit = db.get(Unit, n.basis_unit_id)
        # 只接受重量类基准单位（g/kg）；体积/份不做密度换算（PRD §8 决策）
        factor = {"g": Decimal(1), "kg": Decimal(1000)}.get(basis_unit.symbol if basis_unit else "")
        if factor is None:
            raise ApiError(
                "NUTRITION_BASIS_MISMATCH",
                f"营养基准单位「{basis_unit.name if basis_unit else '未知'}」无法与消耗重量换算，请改用克/千克",
                422,
            )
        basis_grams = _q(n.basis_amount * factor, Q3)
        actual = _q(weight * n.value / basis_grams, Q4)
        definition = db.get(NutritionDefinition, n.nutrition_definition_id)
        snapshot = {
            "value": str(n.value),
            "basis_amount": str(n.basis_amount),
            "basis_unit": basis_unit.symbol,
            "basis_grams": str(basis_grams),
            "source": n.source,
            "version": n.version,
        }
        db.add(
            ConsumptionNutrition(
                consumption_id=consumption_id,
                nutrition_definition_id=n.nutrition_definition_id,
                actual_value=actual,
                unit=definition.unit if definition else "",
                basis_snapshot=snapshot,
            )
        )
        out.append({
            "code": definition.code if definition else "",
            "name": definition.name if definition else "",
            "actual_value": actual,
            "unit": definition.unit if definition else "",
            "basis_snapshot": snapshot,
        })
    return out


# ---------------------------------------------------------------- 撤销


def reverse(
    db: Session,
    *,
    consumption_id: uuid.UUID,
    reason: str,
    device_id: uuid.UUID | None,
) -> dict:
    """撤销消耗：新增 reverse 流水 + 反向分配 + 恢复批次缓存，原记录保留。"""
    record = db.get(ConsumptionRecord, consumption_id)
    if record is None:
        raise not_found("消耗记录不存在")
    if record.status == "reversed":
        raise conflict("该消耗已撤销，不能重复操作", code="ALREADY_REVERSED")

    original_tx = db.get(InventoryTransaction, record.transaction_id)
    if original_tx is None or original_tx.type != "consume":
        raise conflict("原流水不是消耗流水，无法撤销", code="INVALID_STATE_TRANSITION")

    allocations = db.scalars(
        select(TransactionAllocation).where(
            TransactionAllocation.transaction_id == original_tx.id
        )
    ).all()

    day = biz_today().strftime("%Y%m%d")
    rev = InventoryTransaction(
        transaction_no=f"TX-R-{day}-{_seq(db, f'TX-R-{day}', InventoryTransaction.transaction_no, InventoryTransaction):03d}",
        type="reverse",
        ingredient_id=record.ingredient_id,
        quantity_delta=-original_tx.quantity_delta,
        weight_delta=-original_tx.weight_delta,
        cost_delta=-original_tx.cost_delta,
        related_object_type="transaction",
        related_object_id=original_tx.id,
        reason=reason,
        device_id=device_id,
    )
    db.add(rev)
    db.flush()

    for a in allocations:
        batch = db.get(Batch, a.batch_id)
        if batch is None:
            raise validation_error("原批次不存在，无法撤销")
        db.add(
            TransactionAllocation(
                transaction_id=rev.id,
                batch_id=a.batch_id,
                quantity_delta=-a.quantity_delta,
                weight_delta=-a.weight_delta,
                cost_delta=-a.cost_delta,
                unit_cost=a.unit_cost,
            )
        )
        batch.remaining_quantity = _q(batch.remaining_quantity - a.quantity_delta, Q3)
        batch.remaining_weight = _q(batch.remaining_weight - a.weight_delta, Q3)
        batch.remaining_cost = _q(batch.remaining_cost - a.cost_delta, Q2)
        refresh_batch_status(batch)

    mark_reversed(db, record, rev.id)
    db.flush()

    # 一致性断言：反向分配之和 == reverse 流水 delta
    if (
        _q(sum(-a.quantity_delta for a in allocations), Q3) != rev.quantity_delta
        or _q(sum(-a.weight_delta for a in allocations), Q3) != rev.weight_delta
        or _q(sum(-a.cost_delta for a in allocations), Q2) != rev.cost_delta
    ):
        raise validation_error("撤销不变式校验失败：反向分配与流水不一致")

    return {
        "consumption_no": record.consumption_no,
        "status": record.status,
        "reverse_transaction_no": rev.transaction_no,
        "restored_weight": str(-original_tx.weight_delta),
        "restored_cost": str(-original_tx.cost_delta),
    }
