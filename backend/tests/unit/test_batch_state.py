"""批次状态机单元测试（AGENTS.md §4.5：status 只能经 services/inventory/state.py 迁移）。

纯内存测试（不落库）：用假批次对象验证迁移规则本身。
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.errors import ApiError
from app.models import Batch
from app.services.inventory.state import refresh_batch_status, transition


def _batch(status: str = "active", q: str = "1", w: str = "500", c: str = "18.00") -> Batch:
    # ORM 的 Numeric 列返回 Decimal，这里保持一致（字符串 "0" 不会等于数字 0）
    return Batch(
        id=uuid.uuid4(),
        ingredient_id=uuid.uuid4(),
        batch_no="20261109-01",
        purchase_date=date(2026, 11, 9),
        status=status,
        remaining_quantity=Decimal(q),
        remaining_weight=Decimal(w),
        remaining_cost=Decimal(c),
    )


class TestTransition:
    def test_active_to_depleted_allowed(self):
        b = transition(None, _batch("active"), "depleted")
        assert b.status == "depleted"

    def test_depleted_to_active_allowed(self):
        """撤销消耗恢复库存时用到（M4）。"""
        b = transition(None, _batch("depleted"), "active")
        assert b.status == "active"

    def test_void_rejected_before_m4(self):
        """作废需要反向流水，M3 阶段禁止。"""
        with pytest.raises(ApiError) as e:
            transition(None, _batch("active"), "void")
        assert e.value.code == "INVALID_STATE_TRANSITION"

    def test_unknown_status_rejected(self):
        with pytest.raises(ApiError):
            transition(None, _batch("active"), "frozen")

    def test_self_transition_rejected(self):
        with pytest.raises(ApiError):
            transition(None, _batch("active"), "active")


class TestRefresh:
    def test_zeroed_batch_becomes_depleted(self):
        b = refresh_batch_status(_batch(q="0", w="0", c="0"))
        assert b.status == "depleted"

    def test_nonzero_stays_active(self):
        b = refresh_batch_status(_batch())
        assert b.status == "active"

    def test_partial_zero_stays_active(self):
        """纯重量批次：quantity 一直为 0，weight 还有 → 不能误判 depleted。"""
        b = refresh_batch_status(_batch(q="0", w="200", c="7.20"))
        assert b.status == "active"

    def test_depleted_revived_when_stock_returns(self):
        from decimal import Decimal

        b = refresh_batch_status(_batch("depleted", q="0", w="0", c="0"))
        b.remaining_weight = Decimal("200")
        b.remaining_cost = Decimal("7.20")
        refresh_batch_status(b)
        assert b.status == "active"
