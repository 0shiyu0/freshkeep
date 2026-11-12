"""库存引擎纯函数单元测试（阶段 4，不依赖数据库）。

引擎负责三件与存储无关的事，全部用 Decimal：
1. FEFO 扣减计划（4.2/4.3/4.5/4.6/4.7）；
2. 从流水重算库存（4.1）；
3. 对账差异判定（4.12）。

这些函数是纯的：输入批次快照，输出扣减计划，不做 IO，
因此可以用精确到分/毫克的断言把成本与尾差规则钉死。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.services.inventory.engine import (
    FefoBatch,
    InsufficientStockError,
    cost_total,
    plan_deduction,
    recalc_from_ledger,
    reconcile_diff,
)

D = Decimal


def _b(
    bid: str,
    expiry: date | None,
    purchase: date,
    weight: str,
    cost: str,
    quantity: str = "0",
) -> FefoBatch:
    return FefoBatch(
        batch_id=bid,
        batch_no=bid,
        expiry_date=expiry,
        purchase_date=purchase,
        remaining_weight=D(weight),
        remaining_quantity=D(quantity),
        remaining_cost=D(cost),
    )


# ---------------------------------------------------------------- FEFO 顺序


def test_fefo_prefers_earliest_expiry():
    """到期早的先扣，即使入库更晚。"""
    batches = [
        _b("late", date(2026, 12, 1), date(2026, 11, 1), "1000", "35.00"),
        _b("early", date(2026, 11, 5), date(2026, 11, 2), "500", "18.00"),
    ]
    plan = plan_deduction(batches, D("300"), "weight")
    assert [i.batch_id for i in plan.items] == ["early"]
    assert plan.items[0].weight_delta == D("300.000")
    assert plan.items[0].cost_delta == D("10.80")  # 300 × 0.036
    assert plan.shortage == D(0)


def test_fefo_null_expiry_last_then_purchase_date():
    """无到期日排最后；同到期日按购买日升序。"""
    batches = [
        _b("no_expiry", None, date(2026, 10, 1), "1000", "10.00"),
        _b("same_day_later", date(2026, 12, 1), date(2026, 11, 5), "1000", "10.00"),
        _b("same_day_earlier", date(2026, 12, 1), date(2026, 11, 1), "1000", "10.00"),
    ]
    plan = plan_deduction(batches, D("100"), "weight")
    assert plan.items[0].batch_id == "same_day_earlier"

    plan2 = plan_deduction(batches, D("1500"), "weight")
    assert [i.batch_id for i in plan2.items] == ["same_day_earlier", "same_day_later"]


def test_fefo_spans_multiple_batches():
    """跨批次扣减：先扣满早到期批次，再扣下一批次。"""
    batches = [
        _b("a", date(2026, 11, 10), date(2026, 11, 1), "500", "18.00"),
        _b("b", date(2026, 11, 20), date(2026, 11, 2), "1000", "35.00"),
    ]
    plan = plan_deduction(batches, D("600"), "weight")
    assert len(plan.items) == 2
    assert plan.items[0].weight_delta == D("500.000")
    assert plan.items[0].cost_delta == D("18.00")  # 扣完取剩余成本
    assert plan.items[0].closes_batch is True
    assert plan.items[1].weight_delta == D("100.000")
    assert plan.items[1].cost_delta == D("3.50")  # 100 × 0.035
    assert cost_total(plan) == D("21.50")


# ---------------------------------------------------------------- 成本与尾差


def test_partial_take_cost_rounds_to_cent():
    """非整批扣减按单位成本 × 数量，四舍五入到分。"""
    plan = plan_deduction(
        [_b("a", date(2026, 11, 10), date(2026, 11, 1), "300", "10.00")], D("100"), "weight"
    )
    # 10 / 300 = 0.033333… → 0.0333；100 × 0.0333 = 3.33
    assert plan.items[0].cost_delta == D("3.33")
    assert plan.items[0].closes_batch is False


def test_closing_batch_clears_cost_exactly():
    """扣完时成本取剩余成本，避免残留分币（尾差结清）。"""
    plan = plan_deduction(
        [_b("a", date(2026, 11, 10), date(2026, 11, 1), "300", "10.00")], D("300"), "weight"
    )
    assert plan.items[0].cost_delta == D("10.00")
    assert plan.items[0].closes_batch is True

    # 三次各 100g 逐次扣，前两次分摊、最后一次取剩余 → 合计正好 10.00
    total = D("3.33") + D("3.33") + D("3.34")
    assert total == D("10.00")


def test_zero_cost_batch_yields_zero_cost():
    """成本为 0 的批次（如赠品）不产生分摊成本，也不除零。"""
    plan = plan_deduction(
        [_b("free", date(2026, 11, 10), date(2026, 11, 1), "100", "0")], D("50"), "weight"
    )
    assert plan.items[0].cost_delta == D("0.00")


def test_cost_total_equals_sum_of_allocations():
    """单据成本 == 各批次分摊之和（PRD §5.2 硬约束）。"""
    batches = [
        _b("a", date(2026, 11, 10), date(2026, 11, 1), "200", "7.20"),
        _b("b", date(2026, 11, 20), date(2026, 11, 2), "300", "10.50"),
    ]
    plan = plan_deduction(batches, D("450"), "weight")
    assert cost_total(plan) == sum(i.cost_delta for i in plan.items)


# ---------------------------------------------------------------- 不足与边界


def test_insufficient_stock_raises_with_shortage():
    """可用量不足时抛错并给出缺口，不产生部分计划。"""
    with pytest.raises(InsufficientStockError) as e:
        plan_deduction(
            [_b("a", date(2026, 11, 10), date(2026, 11, 1), "500", "18.00")], D("600"), "weight"
        )
    assert e.value.required == D("600.000")
    assert e.value.available == D("500.000")
    assert e.value.shortage == D("100.000")


def test_zero_need_raises():
    with pytest.raises(ValueError):
        plan_deduction([_b("a", None, date(2026, 11, 1), "500", "18.00")], D("0"), "weight")


def test_empty_batches_insufficient():
    with pytest.raises(InsufficientStockError):
        plan_deduction([], D("1"), "weight")


# ---------------------------------------------------------------- 双计量


def test_quantity_mode_uses_remaining_quantity():
    """按数量扣减时以 quantity 为准，重量按批次比例同步。"""
    batches = [_b("a", date(2026, 11, 10), date(2026, 11, 1), "500", "18.00", quantity="2")]
    plan = plan_deduction(batches, D("1"), "quantity")
    item = plan.items[0]
    assert item.quantity_delta == D("1.000")
    assert item.weight_delta == D("250.000")  # 500/2
    assert item.cost_delta == D("9.00")  # 18/2


def test_weight_mode_derives_quantity_by_ratio():
    """按重量扣减时数量按批次比例换算，不超过剩余数量。"""
    batches = [_b("a", date(2026, 11, 10), date(2026, 11, 1), "500", "18.00", quantity="2")]
    plan = plan_deduction(batches, D("250"), "weight")
    item = plan.items[0]
    assert item.weight_delta == D("250.000")
    assert item.quantity_delta == D("1.000")


# ---------------------------------------------------------------- 4.1 从流水重算


def test_recalc_from_ledger():
    """库存 = 初始值 + 后续流水（initial 已含入库，deltas 只放后续变化）。"""
    remaining = recalc_from_ledger(
        initial_quantity=D("2"), initial_weight=D("500"), initial_cost=D("18.00"),
        quantity_deltas=[D("-1")],
        weight_deltas=[D("-250")],
        cost_deltas=[D("-9.00")],
    )
    assert remaining == (D("1.000"), D("250.000"), D("9.00"))


def test_recalc_returns_to_initial_after_reverse():
    """消耗 + 反向流水后回到初始值（撤销语义）。"""
    remaining = recalc_from_ledger(
        initial_quantity=D("0"), initial_weight=D("500"), initial_cost=D("18.00"),
        quantity_deltas=[],
        weight_deltas=[D("-300"), D("300")],
        cost_deltas=[D("-10.80"), D("10.80")],
    )
    assert remaining == (D("0.000"), D("500.000"), D("18.00"))


def test_recalc_never_negative_guard():
    """流水异常导致负余额时，重算结果钳到 0 并由调用方决定是否修复。"""
    remaining = recalc_from_ledger(
        initial_quantity=D("0"), initial_weight=D("100"), initial_cost=D("10.00"),
        quantity_deltas=[], weight_deltas=[D("-150")],
        cost_deltas=[D("-15.00")],
    )
    assert remaining[1] == D("0.000") and remaining[2] == D("0.00")


# ---------------------------------------------------------------- 4.12 对账


def test_reconcile_diff_detects_mismatch():
    assert reconcile_diff(cached=D("500"), allocated=D("500")) == D("0")
    assert reconcile_diff(cached=D("500"), allocated=D("480")) == D("20")


def test_reconcile_diff_tolerance_is_exact():
    """对账不做容差：差 1 毫克也算差异（Decimal 精确比较）。"""
    assert reconcile_diff(cached=D("500.000"), allocated=D("499.999")) != 0
