"""采购建议（阶段 8.10）：只读计算，不创建任何单据。

建议量口径（可解释、可复核）：
1. 有最低重量：`max(minimum_weight - total_weight, 0)`；
2. 只设了最低数量：`max(minimum_quantity - total_quantity, 0)`（换算成重量需 unit_weight，
   没有换算关系时按数量给建议，`suggested_weight` 为 None）；
3. 两者都没设但判定为低库存（通常库存为 0）：按最近 30 天日均消耗 × 7 天估算，
   没有消耗记录时给默认 500g（并标注 `reason=DEFAULT`）。
预估金额 = 建议重量 × 最近一次采购的单位成本；没有采购记录时为 None。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_SUGGEST_WEIGHT = Decimal("500")


def _s(value: Decimal | None, unit: str = "0.001") -> str | None:
    """数值统一输出字符串：直接返回 dict 时 Decimal 会被序列化成 float。"""
    if value is None:
        return None
    return format(value.quantize(Decimal(unit)), "f")
COVER_DAYS = 7
LOOKBACK_DAYS = 30


def suggestions(db: Session, *, limit: int = 50) -> dict:
    rows = db.execute(
        text(
            """
            SELECT v.ingredient_id, v.name, v.total_weight, v.total_quantity,
                   v.total_cost, i.minimum_weight, i.minimum_quantity,
                   i.default_unit_weight, i.default_weight_unit_id,
                   wu.symbol AS weight_symbol
              FROM v_inventory v
              JOIN ingredients i ON i.id = v.ingredient_id
              LEFT JOIN units wu ON wu.id = i.default_weight_unit_id
             WHERE v.is_low_stock
             ORDER BY v.total_weight ASC, v.name
             LIMIT :limit
            """
        ),
        {"limit": limit},
    ).all()

    # 最近 30 天消耗（按食材），用于估算覆盖量
    consumed = {
        r.ingredient_id: Decimal(r.w)
        for r in db.execute(
            text(
                """
                SELECT t.ingredient_id, COALESCE(-SUM(t.weight_delta), 0) AS w
                  FROM inventory_transactions t
                 WHERE t.type IN ('consume','reverse')
                   AND t.created_at >= now() - make_interval(days => :days)
                 GROUP BY t.ingredient_id
                """
            ),
            {"days": LOOKBACK_DAYS},
        ).all()
    }

    # 最近一次采购单位成本
    last_unit_cost = {}
    for r in db.execute(
        text(
            """
            SELECT DISTINCT ON (t.ingredient_id) t.ingredient_id, a.unit_cost
              FROM inventory_transactions t
              JOIN transaction_allocations a ON a.transaction_id = t.id
             WHERE t.type = 'purchase' AND a.unit_cost IS NOT NULL
             ORDER BY t.ingredient_id, t.created_at DESC
            """
        )
    ).all():
        last_unit_cost[r.ingredient_id] = Decimal(r.unit_cost)

    items = []
    total_est = Decimal(0)
    for r in rows:
        min_w = Decimal(r.minimum_weight or 0)
        min_q = Decimal(r.minimum_quantity or 0)
        total_w = Decimal(r.total_weight or 0)
        total_q = Decimal(r.total_quantity or 0)

        suggested = Decimal(0)
        reason = ""
        suggested_quantity = None

        if min_w > 0:
            suggested = max(min_w - total_w, Decimal(0))
            reason = "LOW_MIN_WEIGHT"
        elif min_q > 0:
            need_q = max(min_q - total_q, Decimal(0))
            suggested_quantity = need_q
            if r.default_unit_weight:
                suggested = (need_q * Decimal(r.default_unit_weight)).quantize(Decimal("0.001"))
                reason = "LOW_MIN_QUANTITY"
            else:
                reason = "LOW_MIN_QUANTITY_NO_CONVERSION"
        else:
            avg_daily = consumed.get(r.ingredient_id, Decimal(0)) / LOOKBACK_DAYS
            if avg_daily > 0:
                suggested = (avg_daily * COVER_DAYS).quantize(Decimal("0.001"))
                reason = "ESTIMATED_FROM_USAGE"
            else:
                suggested = DEFAULT_SUGGEST_WEIGHT
                reason = "DEFAULT"

        unit_cost = last_unit_cost.get(r.ingredient_id)
        est_cost = (suggested * unit_cost).quantize(Decimal("0.01")) if (unit_cost and suggested) else None
        if est_cost:
            total_est += est_cost

        items.append({
            "ingredient_id": r.ingredient_id,
            "name": r.name,
            "total_weight": _s(total_w),
            "total_quantity": _s(total_q),
            "minimum_weight": _s(min_w),
            "minimum_quantity": _s(min_q),
            "suggested_weight": _s(suggested) if suggested > 0 else None,
            "suggested_quantity": _s(suggested_quantity) if suggested_quantity is not None else None,
            "reason": reason,
            "last_unit_cost": _s(unit_cost, "0.0001"),
            "estimated_cost": _s(est_cost, "0.01"),
            "weight_symbol": r.weight_symbol or "g",
        })

    return {"items": items, "total": len(items), "estimated_total": _s(total_est, "0.01")}
