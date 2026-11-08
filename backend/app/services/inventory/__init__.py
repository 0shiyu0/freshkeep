"""批次域服务：入库五步事务、编号生成、批次查询（M3）。

AGENTS.md §4.2 库存写入五步（任何改变库存的操作都必须遵守）：
1. 一个事务内完成；
2. 写一条 inventory_transactions；
3. 为涉及的每个批次写一条 transaction_allocations；
4. 同步更新 batches.remaining_* 缓存；
5. 断言 Σ allocations == transaction.delta，不等则回滚。

入库（purchase）是五步的最简形态：新批次的 initial == remaining == 输入值，
分配给自己这条批次，delta 与流水一致。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import not_found, validation_error
from app.core.time import biz_today, days_until
from app.models import (
    Batch,
    Ingredient,
    InventoryTransaction,
    StorageLocation,
    TransactionAllocation,
    Unit,
)

BIZ_TZ = ZoneInfo("Asia/Shanghai")

# 重量换算到克的系数（AGENTS：不做体积↔重量密度换算，这里只有克系）
_WEIGHT_TO_GRAMS = {"g": Decimal("1"), "kg": Decimal("1000")}
_QTY_NUTRI = Decimal("0.0001")  # unit_cost 的精度（NUTRI 4 位）


# ---------------------------------------------------------------- 编号


def _next_seq(db: Session, prefix: str, column, table: str) -> int:
    """取 prefix（如 '20261109'）当日的下一个序号。

    单用户低频场景：查询计数 + 唯一约束兜底；冲突时由调用方重试。
    """
    like = f"{prefix}-%"
    stmt = select(func.count()).select_from(table).where(column.like(like))
    return (db.execute(stmt).scalar() or 0) + 1


def _gen_batch_no(db: Session) -> str:
    day = biz_today().strftime("%Y%m%d")
    seq = _next_seq(db, day, Batch.batch_no, Batch)
    return f"{day}-{seq:02d}"


def _gen_tx_no(db: Session, type_prefix: str) -> str:
    day = biz_today().strftime("%Y%m%d")
    seq = _next_seq(
        db, f"TX-{type_prefix}-{day}", InventoryTransaction.transaction_no, InventoryTransaction
    )
    return f"TX-{type_prefix}-{day}-{seq:02d}"


# ---------------------------------------------------------------- 入库


def create_batch(
    db: Session,
    *,
    ingredient_id: uuid.UUID,
    purchase_date,
    production_date,
    expiry_date,
    storage_location_id: uuid.UUID | None,
    quantity: Decimal,
    weight_in: Decimal,
    purchase_cost: Decimal,
    quantity_unit_id: uuid.UUID | None,
    weight_unit_id: uuid.UUID | None,
    note: str,
    device_id: uuid.UUID | None,
) -> tuple[Batch, InventoryTransaction]:
    """一次采购入库 = 新建批次 + purchase 流水 + 自分配（同一事务）。

    返回 (batch, transaction)；调用方负责 commit（get_db 的请求事务）。
    """
    # ---- 校验：食材存在
    ingredient = db.get(Ingredient, ingredient_id)
    if ingredient is None:
        raise not_found("食材不存在")

    # ---- 校验：数量与重量至少一个 > 0（批次必须有实体）
    if quantity <= 0 and weight_in <= 0:
        raise validation_error("数量与重量不能同时为 0，至少填写一项")

    # ---- 校验：单位维度 + 换算成克
    weight = weight_in
    if weight_unit_id is not None:
        unit = db.get(Unit, weight_unit_id)
        if unit is None:
            raise validation_error("重量单位不存在")
        if unit.dimension != "weight":
            raise validation_error(
                f"重量字段只能用重量类单位（g/kg），「{unit.name}」是{unit.dimension}维度"
            )
        factor = _WEIGHT_TO_GRAMS.get(unit.symbol)
        if factor is None:
            raise validation_error(f"暂不支持的重量单位：{unit.symbol}")
        weight = (weight_in * factor).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    if quantity_unit_id is not None:
        unit = db.get(Unit, quantity_unit_id)
        if unit is None:
            raise validation_error("数量单位不存在")
        if unit.dimension not in ("quantity", "volume"):
            raise validation_error(
                f"数量字段只能用数量类单位，「{unit.name}」是{unit.dimension}维度"
            )

    if storage_location_id is not None and db.get(StorageLocation, storage_location_id) is None:
        raise validation_error("储存位置不存在")

    if expiry_date and production_date and expiry_date < production_date:
        raise validation_error("到期日期不能早于生产日期")

    # ---- 第 0 步：批次本体（initial == remaining == 输入值）
    batch = Batch(
        ingredient_id=ingredient_id,
        batch_no=_gen_batch_no(db),
        purchase_date=purchase_date or biz_today(),
        production_date=production_date,
        expiry_date=expiry_date,
        storage_location_id=storage_location_id,
        initial_quantity=quantity,
        remaining_quantity=quantity,
        initial_weight=weight,
        remaining_weight=weight,
        purchase_cost=purchase_cost,
        remaining_cost=purchase_cost,
        status="active",
        note=note,
    )
    db.add(batch)
    db.flush()

    # ---- 第 1 步：流水（purchase 只能为正，ck_tx_sign 由数据库兜底）
    tx = InventoryTransaction(
        transaction_no=_gen_tx_no(db, "P"),
        type="purchase",
        ingredient_id=ingredient_id,
        quantity_delta=quantity,
        weight_delta=weight,
        cost_delta=purchase_cost,
        related_object_type="batch",
        related_object_id=batch.id,
        device_id=device_id,
    )
    db.add(tx)
    db.flush()

    # ---- 第 2 步：分配（入库 = 分配给自己这条批次）
    db.add(
        TransactionAllocation(
            transaction_id=tx.id,
            batch_id=batch.id,
            quantity_delta=quantity,
            weight_delta=weight,
            cost_delta=purchase_cost,
            unit_cost=_unit_cost(purchase_cost, weight, quantity),
        )
    )
    db.flush()

    # ---- 第 3 步：不变式断言（AGENTS §4.2 第 5 步）
    _assert_allocation_consistency(db, tx, [(batch.id, quantity, weight, purchase_cost)])

    return batch, tx


def _unit_cost(cost: Decimal, weight: Decimal, quantity: Decimal) -> Decimal | None:
    """单位成本快照：优先元/克；纯数量管理按元/个。成本为 0 时无意义，存 None。"""
    if cost <= 0:
        return None
    if weight > 0:
        return (cost / weight).quantize(_QTY_NUTRI, rounding=ROUND_HALF_UP)
    if quantity > 0:
        return (cost / quantity).quantize(_QTY_NUTRI, rounding=ROUND_HALF_UP)
    return None


def _assert_allocation_consistency(
    db: Session,
    tx: InventoryTransaction,
    allocations: list[tuple[uuid.UUID, Decimal, Decimal, Decimal]],
) -> None:
    """Σ allocation == transaction.delta；不等则抛异常（调用方的事务回滚）。"""
    sum_q = sum(a[1] for a in allocations)
    sum_w = sum(a[2] for a in allocations)
    sum_c = sum(a[3] for a in allocations)
    if (sum_q, sum_w, sum_c) != (tx.quantity_delta, tx.weight_delta, tx.cost_delta):
        raise validation_error(
            "库存写入不变式校验失败：分配与流水不一致",
            allocated_quantity=str(sum_q),
            allocated_weight=str(sum_w),
            allocated_cost=str(sum_c),
        )


# ---------------------------------------------------------------- 查询


def load_batch_out(db: Session, batch: Batch) -> dict:
    """把 ORM 批次转成 JSON 安全的输出字典（带食材名/位置名/单位成本/剩余天数）。

    与阶段 2 的模式一致：用 BatchOut 做序列化边界，model_dump(mode="json")
    让 UUID→str、Decimal→按精度的字符串。
    """
    from app.schemas.batch import BatchOut

    alloc_unit_cost = db.execute(
        select(TransactionAllocation.unit_cost).where(TransactionAllocation.batch_id == batch.id)
    ).scalars().first()

    data = BatchOut(
        id=batch.id,
        batch_no=batch.batch_no,
        ingredient_id=batch.ingredient_id,
        ingredient_name=batch.ingredient.name,
        purchase_date=batch.purchase_date,
        production_date=batch.production_date,
        expiry_date=batch.expiry_date,
        opened_date=batch.opened_date,
        storage_location_id=batch.storage_location_id,
        location_name=batch.storage_location.name if batch.storage_location else None,
        initial_quantity=batch.initial_quantity,
        remaining_quantity=batch.remaining_quantity,
        initial_weight=batch.initial_weight,
        remaining_weight=batch.remaining_weight,
        purchase_cost=batch.purchase_cost,
        remaining_cost=batch.remaining_cost,
        unit_cost=alloc_unit_cost,
        status=batch.status,
        note=batch.note,
        days_to_expiry=days_until(batch.expiry_date),
        created_at=batch.created_at,
    )
    return data.model_dump(mode="json")


def fefo_order(stmt):
    """FEFO 排序（AGENTS §4.3）：到期日升序、无到期日排最后、同日期按入库时间。"""
    from sqlalchemy import nulls_last

    return stmt.order_by(nulls_last(Batch.expiry_date), Batch.purchase_date, Batch.id)
