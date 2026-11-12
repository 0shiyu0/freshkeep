"""统计聚合（阶段 6）：库存价值、采购/消耗趋势、分类占比、排行、周转。

口径（每个数字都能对回流水）：
- 库存价值 = `Σ batches.remaining_cost`，**不是**采购总额；
- 采购金额 = `Σ purchase.cost_delta`；消耗金额 = `-(Σ consume + Σ reverse)`，
  撤销后净额自动抵消；
- 分类占比按**消耗成本**分组（采购不进这个维度，避免与消耗重复计算）；
- 排行与周转只看消耗；周转的 `consume_times` 只数 `consume` 流水，不含反向；
- 时间窗口按 Asia/Shanghai 自然日，含首日、不含结束日的次日。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.core.errors import validation_error
from app.core.time import biz_today
from sqlalchemy import text
from sqlalchemy.orm import Session

BIZ_TZ = ZoneInfo("Asia/Shanghai")
Q2, Q3, Q4 = Decimal("0.01"), Decimal("0.001"), Decimal("0.0001")

GRANULARITY = {"day", "week", "month", "year"}
DEFAULT_DAYS = {"day": 30, "week": 84, "month": 365, "year": 1825}


def _q(v: Decimal, unit: Decimal) -> Decimal:
    return v.quantize(unit, rounding=ROUND_HALF_UP)


def _window(from_date: date | None, to_date: date | None, granularity: str) -> tuple[date, date]:
    today = biz_today()
    end = to_date or today
    start = from_date or (end - timedelta(days=DEFAULT_DAYS[granularity] - 1))
    if start > end:
        raise validation_error("起始日期不能晚于结束日期")
    return start, end


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(start, time.min, tzinfo=BIZ_TZ),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=BIZ_TZ),
    )


def _buckets(start: date, end: date, granularity: str) -> list[date]:
    """生成完整时间轴（含没有数据的桶），保证图表连续。"""
    out: list[date] = []
    if granularity == "day":
        cur = start
        while cur <= end:
            out.append(cur)
            cur += timedelta(days=1)
    elif granularity == "week":
        cur = start - timedelta(days=start.weekday())  # 对齐到周一
        while cur <= end:
            out.append(cur)
            cur += timedelta(days=7)
    elif granularity == "month":
        cur = start.replace(day=1)
        while cur <= end:
            out.append(cur)
            cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:  # year
        cur = start.replace(month=1, day=1)
        while cur <= end:
            out.append(cur)
            cur = cur.replace(year=cur.year + 1)
    return out


def _label(d: date, granularity: str) -> str:
    if granularity == "day":
        return d.strftime("%m-%d")
    if granularity == "week":
        return f"{d.month}/{d.day} 周"
    if granularity == "month":
        return d.strftime("%Y-%m")
    return str(d.year)


def overview(
    db: Session,
    *,
    granularity: str = "day",
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict:
    if granularity not in GRANULARITY:
        raise validation_error("粒度只能是 day / week / month / year")
    start, end = _window(from_date, to_date, granularity)
    start_dt, end_dt = _bounds(start, end)
    params = {"start": start_dt, "end": end_dt}

    # ---- 库存价值（剩余成本）
    stock = db.execute(
        text(
            "SELECT COALESCE(SUM(total_cost),0) AS cost, COALESCE(SUM(total_weight),0) AS weight, "
            "COUNT(*) AS n, COALESCE(SUM(batch_count),0) AS b FROM v_inventory"
        )
    ).one()

    # ---- 按粒度聚合流水（purchase 与 consume+reverse 分开）
    rows = db.execute(
        text(
            """
            SELECT date_trunc(:g, created_at AT TIME ZONE 'Asia/Shanghai')::date AS bucket,
                   SUM(cost_delta)   FILTER (WHERE type = 'purchase') AS p_cost,
                   SUM(weight_delta) FILTER (WHERE type = 'purchase') AS p_weight,
                   SUM(cost_delta)   FILTER (WHERE type IN ('consume','reverse')) AS c_cost,
                   SUM(weight_delta) FILTER (WHERE type IN ('consume','reverse')) AS c_weight,
                   COUNT(*)          FILTER (WHERE type = 'purchase') AS p_cnt,
                   COUNT(*)          FILTER (WHERE type = 'consume')  AS c_cnt
              FROM inventory_transactions
             WHERE created_at >= :start AND created_at < :end
             GROUP BY 1 ORDER BY 1
            """
        ),
        {**params, "g": granularity},
    ).all()
    by_bucket = {r.bucket: r for r in rows}

    series = []
    p_total = c_total = Decimal(0)
    p_weight_total = c_weight_total = Decimal(0)
    op_count = 0
    for b in _buckets(start, end, granularity):
        r = by_bucket.get(b)
        p_cost = Decimal(r.p_cost or 0) if r else Decimal(0)
        c_cost = -(Decimal(r.c_cost or 0)) if r else Decimal(0)
        p_w = Decimal(r.p_weight or 0) if r else Decimal(0)
        c_w = -(Decimal(r.c_weight or 0)) if r else Decimal(0)
        if r:
            op_count += int(r.p_cnt or 0) + int(r.c_cnt or 0)
        p_total += p_cost
        c_total += c_cost
        p_weight_total += p_w
        c_weight_total += c_w
        series.append({
            "bucket": b, "label": _label(b, granularity),
            "purchase_amount": _q(p_cost, Q2), "consumption_amount": _q(c_cost, Q2),
            "purchase_weight": _q(p_w, Q3), "consumption_weight": _q(c_w, Q3),
        })

    # ---- 分类占比（按消耗成本，含反向抵消）
    cat_rows = db.execute(
        text(
            """
            SELECT COALESCE(c.name, '未分类') AS name,
                   COALESCE(-SUM(t.cost_delta), 0) AS amount,
                   COALESCE(-SUM(t.weight_delta), 0) AS weight
              FROM inventory_transactions t
              JOIN ingredients i ON i.id = t.ingredient_id
              LEFT JOIN categories c ON c.id = i.category_id
             WHERE t.type IN ('consume','reverse')
               AND t.created_at >= :start AND t.created_at < :end
             GROUP BY c.name
             HAVING COALESCE(-SUM(t.cost_delta), 0) <> 0
             ORDER BY amount DESC
            """
        ),
        params,
    ).all()
    cat_total = sum((Decimal(r.amount) for r in cat_rows), Decimal(0))
    categories = [
        {
            "name": r.name,
            "amount": _q(Decimal(r.amount), Q2),
            "ratio": _q(Decimal(r.amount) / cat_total, Q4) if cat_total else Decimal(0),
            "weight": _q(Decimal(r.weight), Q3),
        }
        for r in cat_rows
    ]

    # ---- 消耗排行（按重量）
    top_rows = db.execute(
        text(
            """
            SELECT i.id, i.name,
                   COALESCE(-SUM(t.weight_delta), 0) AS weight,
                   COALESCE(-SUM(t.cost_delta), 0) AS cost,
                   COUNT(*) FILTER (WHERE t.type = 'consume') AS times
              FROM inventory_transactions t
              JOIN ingredients i ON i.id = t.ingredient_id
             WHERE t.type IN ('consume','reverse')
               AND t.created_at >= :start AND t.created_at < :end
             GROUP BY i.id, i.name
             HAVING COALESCE(-SUM(t.weight_delta), 0) > 0
             ORDER BY weight DESC, i.name
             LIMIT 10
            """
        ),
        params,
    ).all()

    # ---- 周转（采购次数、消耗次数、消耗重量）
    turnover_rows = db.execute(
        text(
            """
            SELECT i.id, i.name,
                   COUNT(*) FILTER (WHERE t.type = 'purchase') AS p_times,
                   COUNT(*) FILTER (WHERE t.type = 'consume')  AS c_times,
                   COALESCE(-SUM(t.weight_delta) FILTER (WHERE t.type IN ('consume','reverse')), 0) AS c_weight
              FROM ingredients i
              JOIN inventory_transactions t
                ON t.ingredient_id = i.id
               AND t.created_at >= :start AND t.created_at < :end
             GROUP BY i.id, i.name
             ORDER BY c_times DESC, c_weight DESC, i.name
             LIMIT 20
            """
        ),
        params,
    ).all()

    # ---- 最近操作
    recent = db.execute(
        text(
            """
            SELECT t.id, t.transaction_no, t.type, i.name, t.weight_delta, t.cost_delta,
                   t.reason, t.created_at
              FROM inventory_transactions t
              JOIN ingredients i ON i.id = t.ingredient_id
             ORDER BY t.created_at DESC, t.id DESC
             LIMIT 8
            """
        )
    ).all()

    return {
        "granularity": granularity,
        "start_date": start,
        "end_date": end,
        "has_data": op_count > 0,
        "stock": {
            "cost": _q(Decimal(stock.cost), Q2),
            "weight": _q(Decimal(stock.weight), Q3),
            "ingredient_count": stock.n,
            "batch_count": stock.b,
        },
        "purchase": {"total_amount": _q(p_total, Q2), "total_weight": _q(p_weight_total, Q3)},
        "consumption": {"total_amount": _q(c_total, Q2), "total_weight": _q(c_weight_total, Q3)},
        "series": series,
        "category_breakdown": categories,
        "top_consumed": [
            {
                "ingredient_id": r.id, "name": r.name,
                "weight": _q(Decimal(r.weight), Q3),
                "cost": _q(Decimal(r.cost), Q2),
                "times": int(r.times or 0),
            }
            for r in top_rows
        ],
        "turnover": [
            {
                "ingredient_id": r.id, "name": r.name,
                "purchase_times": int(r.p_times or 0),
                "consume_times": int(r.c_times or 0),
                "consumed_weight": _q(Decimal(r.c_weight), Q3),
            }
            for r in turnover_rows
        ],
        "recent_operations": [
            {
                "id": r.id, "transaction_no": r.transaction_no, "type": r.type,
                "ingredient_name": r.name, "weight_delta": r.weight_delta,
                "cost_delta": r.cost_delta, "reason": r.reason, "created_at": r.created_at,
            }
            for r in recent
        ],
    }
