"""首页统计与营养汇总（M6）。

口径约定（与 PRD §4.2 / §4.7 对齐）：
- 库存价值/重量读 `v_inventory`（缓存聚合，已由阶段 4 的流水口径接口对账）；
- 期间采购/消耗/报损金额按 `inventory_transactions.created_at` 落在窗口内统计；
- 消耗比例 = 期间消耗金额 ÷ 期间采购金额，采购为 0 时返回 None（不是 0）；
- 营养只统计 `consumption_records.status='completed'` 的**快照**，
  窗口按 Asia/Shanghai 的自然日边界；
- 窗口内没有消耗时 `has_records=False`，数值为 0 但可区分（空白天 ≠ 0 摄入）。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.time import biz_today

BIZ_TZ = ZoneInfo("Asia/Shanghai")
Q2, Q3, Q4 = Decimal("0.01"), Decimal("0.001"), Decimal("0.0001")
PERIOD_DAYS = {"today": 0, "3d": 2, "week": 6}
PERIODS = ("today", "3d", "week", "month")
DEFAULT_SUMMARY_DAYS = 30


def _q(v: Decimal, unit: Decimal) -> Decimal:
    return v.quantize(unit, rounding=ROUND_HALF_UP)


def day_window(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """自然日窗口 [start 00:00, end+1 00:00)，按 Asia/Shanghai。"""
    start = datetime.combine(start_date, time.min, tzinfo=BIZ_TZ)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=BIZ_TZ)
    return start, end


def nutrition_window(period: str) -> tuple[date, date, int]:
    """period → (起始日, 结束日, 天数跨度)；today 跨度为 0。

    month 取「本月 1 日 ~ 今天」的自然月至今，跨度 = 已过天数。
    """
    if period not in PERIODS:
        raise ValueError(f"未知周期：{period}")
    today = biz_today()
    if period == "month":
        start = today.replace(day=1)
        return start, today, (today - start).days
    days = PERIOD_DAYS[period]
    return today - timedelta(days=days), today, days


# ---------------------------------------------------------------- 首页汇总


def summary(db: Session, *, from_date: date | None = None, to_date: date | None = None) -> dict:
    today = biz_today()
    end_date = to_date or today
    start_date = from_date or (end_date - timedelta(days=DEFAULT_SUMMARY_DAYS - 1))
    start_dt, end_dt = day_window(start_date, end_date)

    stock = db.execute(
        text(
            "SELECT COALESCE(SUM(total_cost),0) AS cost, COALESCE(SUM(total_weight),0) AS weight, "
            "COUNT(*) AS ingredients, COALESCE(SUM(batch_count),0) AS batches, "
            "COUNT(*) FILTER (WHERE is_low_stock) AS low FROM v_inventory"
        )
    ).one()

    amounts = db.execute(
        text(
            "SELECT type, COALESCE(SUM(cost_delta),0) AS amount "
            "  FROM inventory_transactions "
            " WHERE created_at >= :start AND created_at < :end "
            " GROUP BY type"
        ),
        {"start": start_dt, "end": end_dt},
    ).all()
    by_type = {r.type: Decimal(r.amount) for r in amounts}

    purchase = by_type.get("purchase", Decimal(0))
    consume = -by_type.get("consume", Decimal(0))  # 流水为负，金额取正展示
    spoilage = -by_type.get("spoilage", Decimal(0))
    ratio = _q(consume / purchase, Q4) if purchase > 0 else None

    alive = "status='active' AND (remaining_weight > 0 OR remaining_quantity > 0) AND expiry_date IS NOT NULL"
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

    recent = db.execute(
        text(
            "SELECT b.id, b.batch_no, b.ingredient_id, i.name, b.initial_weight, b.purchase_cost, "
            "       b.purchase_date, b.created_at "
            "  FROM batches b JOIN ingredients i ON i.id = b.ingredient_id "
            " ORDER BY b.created_at DESC LIMIT 4"
        )
    ).all()

    return {
        "stock_cost": _q(Decimal(stock.cost), Q2),
        "stock_weight": _q(Decimal(stock.weight), Q3),
        "stock_ingredient_count": stock.ingredients,
        "batch_count": stock.batches,
        "low_stock_count": stock.low,
        "expiring_count": expiring,
        "expired_count": expired,
        "period_start": start_date,
        "period_end": end_date,
        "purchase_amount": _q(purchase, Q2),
        "consumption_amount": _q(consume, Q2),
        "spoilage_amount": _q(spoilage, Q2),
        "consumption_ratio": ratio,
        "recent_batches": [
            {
                "batch_id": r.id, "batch_no": r.batch_no,
                "ingredient_id": r.ingredient_id, "ingredient_name": r.name,
                "weight": r.initial_weight, "cost": r.purchase_cost,
                "purchase_date": r.purchase_date, "created_at": r.created_at,
            }
            for r in recent
        ],
    }


# ---------------------------------------------------------------- 营养汇总


def nutrition(db: Session, *, period: str = "today") -> dict:
    start_date, end_date, days = nutrition_window(period)
    start_dt, end_dt = day_window(start_date, end_date)

    counts = db.execute(
        text(
            "SELECT COUNT(*) AS n FROM consumption_records "
            " WHERE status = 'completed' AND consumed_at >= :start AND consumed_at < :end"
        ),
        {"start": start_dt, "end": end_dt},
    ).scalar() or 0

    rows = db.execute(
        text(
            """
            SELECT d.code, d.name, d.unit,
                   COALESCE(SUM(cn.actual_value), 0) AS total
              FROM nutrition_definitions d
              LEFT JOIN consumption_nutrition cn ON cn.nutrition_definition_id = d.id
              LEFT JOIN consumption_records c
                     ON c.id = cn.consumption_id
                    AND c.status = 'completed'
                    AND c.consumed_at >= :start AND c.consumed_at < :end
             WHERE d.is_active
             GROUP BY d.id, d.code, d.name, d.unit, d.sort_order
             ORDER BY d.sort_order, d.code
            """
        ),
        {"start": start_dt, "end": end_dt},
    ).all()

    targets = _current_targets(db)

    items = []
    for r in rows:
        total = _q(Decimal(r.total), Q4)
        target = targets.get((r.code, "daily"))
        # 目标按「日」设置；多日窗口要把日目标累加，否则达成率会被算高
        span = days + 1
        period_target = (target * span) if target else None
        items.append({
            "code": r.code, "name": r.name, "unit": r.unit,
            "actual_value": total,
            "target_value": target,          # 日目标，前端展示用
            "period_target": period_target,  # 本窗口累计目标
            "achievement": _q(total / period_target, Q4) if period_target else None,
        })

    return {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
        "has_records": counts > 0,
        "record_count": counts,
        "items": items,
        "disclaimer": "按库存消耗量估算，不代表实际摄入",
    }


def _current_targets(db: Session) -> dict[tuple[str, str], Decimal]:
    """每个 (code, period) 取 effective_from <= 今天的最新一行。"""
    rows = db.execute(
        text(
            """
            SELECT DISTINCT ON (d.code, t.period) d.code, t.period, t.target_value
              FROM nutrition_targets t
              JOIN nutrition_definitions d ON d.id = t.nutrition_definition_id
             WHERE t.effective_from <= CURRENT_DATE
             ORDER BY d.code, t.period, t.effective_from DESC
            """
        )
    ).all()
    return {(r.code, r.period): Decimal(r.target_value) for r in rows}


# ---------------------------------------------------------------- 营养目标


def upsert_targets(db: Session, items: list) -> int:
    """按 (code, period, 今天) 写入或覆盖；历史日期保留。"""
    from app.models import NutritionDefinition

    defs = {
        d.code: d
        for d in db.query(NutritionDefinition).filter(
            NutritionDefinition.code.in_([i.code for i in items])
        ).all()
    }
    missing = [i.code for i in items if i.code not in defs]
    if missing:
        from app.core.errors import validation_error

        raise validation_error("营养项目不存在", codes=missing)

    today = biz_today()
    for item in items:
        db.execute(
            text(
                """
                INSERT INTO nutrition_targets
                       (nutrition_definition_id, target_value, period, effective_from)
                VALUES (CAST(:did AS uuid), CAST(:val AS numeric), :period, CAST(:from AS date))
                ON CONFLICT (nutrition_definition_id, period, effective_from)
                DO UPDATE SET target_value = EXCLUDED.target_value
                """
            ),
            {
                "did": str(defs[item.code].id),
                "val": str(item.target_value),
                "period": item.period,
                "from": today,
            },
        )
    db.commit()
    return len(items)


def list_targets(db: Session) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT DISTINCT ON (d.code, t.period)
                   d.code, d.name, d.unit, t.target_value, t.period, t.effective_from
              FROM nutrition_targets t
              JOIN nutrition_definitions d ON d.id = t.nutrition_definition_id
             WHERE t.effective_from <= CURRENT_DATE
             ORDER BY d.code, t.period, t.effective_from DESC
            """
        )
    ).all()
    return [
        {
            "code": r.code, "name": r.name, "unit": r.unit,
            "target_value": Decimal(r.target_value),
            "period": r.period, "effective_from": r.effective_from,
        }
        for r in rows
    ]
