"""库存引擎（阶段 4）：与存储无关的纯计算层。

职责边界（重要）：
- 本模块**不做 IO、不开事务、不碰 SQLAlchemy**，只接收批次快照、返回扣减计划；
- 事务、行锁、幂等、写库仍由 `services/consumption`、`services/inventory/ops` 负责；
- 这样 FEFO 顺序、成本分摊、尾差、双计量比例、流水重算都能用纯单元测试钉死，
  不必依赖数据库（`tests/unit/test_inventory_engine.py`）。

约定（AGENTS.md §4.1 / PRD §5.2~5.3）：
- 全程 Decimal：金额 2 位、重量/数量 3 位、单位成本 4 位；
- 扣完一个批次时成本直接取剩余成本（尾差结清），不按单位成本乘；
- 单据成本 = 各批次分摊之和；
- 库存 = 初始值 + Σ有效流水（反向流水也是流水，净额自然归零）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

Q2 = Decimal("0.01")
Q3 = Decimal("0.001")
Q4 = Decimal("0.0001")
ZERO = Decimal(0)


def _q(v: Decimal, unit: Decimal) -> Decimal:
    return v.quantize(unit, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- 数据契约


@dataclass(frozen=True)
class FefoBatch:
    """参与 FEFO 计算的批次快照（只读，不持有 ORM 对象）。"""

    batch_id: str
    batch_no: str
    expiry_date: date | None
    purchase_date: date
    remaining_weight: Decimal
    remaining_quantity: Decimal
    remaining_cost: Decimal


@dataclass(frozen=True)
class DeductionItem:
    """一个批次的扣减结果。delta 都是**正数**（扣减方向由调用方加负号）。"""

    batch_id: str
    batch_no: str
    weight_delta: Decimal
    quantity_delta: Decimal
    cost_delta: Decimal
    unit_cost: Decimal
    closes_batch: bool  # True = 本批次被扣完，成本已按剩余成本结清


@dataclass
class DeductionPlan:
    items: list[DeductionItem] = field(default_factory=list)
    required: Decimal = ZERO
    available: Decimal = ZERO
    shortage: Decimal = ZERO
    mode: str = "weight"


class InsufficientStockError(ValueError):
    """可用量不足。携带 required/available/shortage，供接口层组装 422。"""

    def __init__(self, required: Decimal, available: Decimal, shortage: Decimal) -> None:
        super().__init__(f"可用量不足：需要 {required}，可用 {available}，缺 {shortage}")
        self.required = required
        self.available = available
        self.shortage = shortage


# ---------------------------------------------------------------- FEFO


def fefo_sort_key(b: FefoBatch) -> tuple:
    """FEFO 排序键：到期日升序、无到期日排最后、同日期按购买日、最后按 id。

    与 AGENTS.md §4.3 的 SQL 排序（expiry NULLS LAST, purchase_date, id）保持一致。
    """
    return (
        b.expiry_date is None,
        b.expiry_date or date.min,
        b.purchase_date,
        b.batch_id,
    )


def available_amount(b: FefoBatch, mode: str) -> Decimal:
    return b.remaining_weight if mode == "weight" else b.remaining_quantity


def plan_deduction(batches: list[FefoBatch], need: Decimal, mode: str = "weight") -> DeductionPlan:
    """按 FEFO 生成扣减计划。不足时抛 InsufficientStockError，不返回部分计划。

    mode = "weight" 按克扣（另一维度按批次比例同步）；"quantity" 按数量扣。
    """
    if mode not in ("weight", "quantity"):
        raise ValueError(f"未知的扣减维度：{mode}")
    if need is None or need <= 0:
        raise ValueError("扣减量必须大于 0")

    candidates = [
        b for b in batches if available_amount(b, mode) > 0
    ]
    candidates.sort(key=fefo_sort_key)
    available = sum((available_amount(b, mode) for b in candidates), ZERO)

    required = _q(need, Q3)
    if available < required:
        raise InsufficientStockError(required, _q(available, Q3), _q(required - available, Q3))

    plan = DeductionPlan(required=required, available=_q(available, Q3), mode=mode)
    left = required

    for b in candidates:
        if left <= 0:
            break
        base = available_amount(b, mode)
        if base <= 0:
            continue

        take = min(base, left)
        unit_cost = _q(b.remaining_cost / base, Q4)
        closes = take == base
        # 尾差结清：扣完取剩余成本，否则按单位成本分摊
        cost = b.remaining_cost if closes else _q(take * unit_cost, Q2)

        if mode == "weight":
            w_delta = _q(take, Q3)
            q_delta = (
                _q(take * b.remaining_quantity / b.remaining_weight, Q3)
                if b.remaining_weight > 0 else ZERO
            )
            q_delta = min(q_delta, b.remaining_quantity)
        else:
            q_delta = _q(take, Q3)
            w_delta = (
                _q(take * b.remaining_weight / b.remaining_quantity, Q3)
                if b.remaining_quantity > 0 else ZERO
            )
            w_delta = min(w_delta, b.remaining_weight)

        plan.items.append(
            DeductionItem(
                batch_id=b.batch_id,
                batch_no=b.batch_no,
                weight_delta=w_delta,
                quantity_delta=q_delta,
                cost_delta=cost,
                unit_cost=unit_cost,
                closes_batch=closes,
            )
        )
        left = _q(left - take, Q3)

    if left > 0:  # 防御：可用量已校验，理论上不可达
        raise InsufficientStockError(required, _q(available, Q3), _q(left, Q3))
    return plan


def cost_total(plan: DeductionPlan) -> Decimal:
    """单据成本 = 各批次分摊之和（PRD §5.2 必须满足）。"""
    return _q(sum((i.cost_delta for i in plan.items), ZERO), Q2)


def plan_totals(plan: DeductionPlan) -> tuple[Decimal, Decimal, Decimal]:
    """(总数量, 总重量, 总成本)，用于与流水 delta 做一致性断言。"""
    return (
        _q(sum((i.quantity_delta for i in plan.items), ZERO), Q3),
        _q(sum((i.weight_delta for i in plan.items), ZERO), Q3),
        cost_total(plan),
    )


# ---------------------------------------------------------------- 4.1 流水重算


def recalc_from_ledger(
    *,
    initial_quantity: Decimal,
    initial_weight: Decimal,
    initial_cost: Decimal,
    quantity_deltas: list[Decimal],
    weight_deltas: list[Decimal],
    cost_deltas: list[Decimal],
) -> tuple[Decimal, Decimal, Decimal]:
    """4.1：库存 = 初始值 + Σ有效流水；负余额钳到 0（由调用方决定是否修复缓存）。

    「有效流水」指 `inventory_transactions` 里的全部行——反向流水也是流水，
    撤销后净额自然回到原值，不需要额外过滤。
    """
    q = _q(initial_quantity + sum(quantity_deltas, ZERO), Q3)
    w = _q(initial_weight + sum(weight_deltas, ZERO), Q3)
    c = _q(initial_cost + sum(cost_deltas, ZERO), Q2)
    return (max(q, ZERO), max(w, ZERO), max(c, ZERO))


# ---------------------------------------------------------------- 4.12 对账


def reconcile_diff(*, cached: Decimal, allocated: Decimal) -> Decimal:
    """缓存与流水分配聚合的差；不做容差，差 1 毫克/1 分都算差异。"""
    return cached - allocated


def is_consistent(*, cached_q: Decimal, cached_w: Decimal, cached_c: Decimal,
                  alloc_q: Decimal, alloc_w: Decimal, alloc_c: Decimal) -> bool:
    return (
        reconcile_diff(cached=cached_q, allocated=alloc_q) == 0
        and reconcile_diff(cached=cached_w, allocated=alloc_w) == 0
        and reconcile_diff(cached=cached_c, allocated=alloc_c) == 0
    )
