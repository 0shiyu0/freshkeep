"""临期/过期/低库存扫描与通知中心（阶段 8.7 / 8.8）。

设计要点：
- 扫描**幂等**：同一 `(type, batch_id)` 或 `(type, ingredient_id)` 已存在 `pending` 通知就不再插入；
- 只用 `INSERT ... SELECT ... WHERE NOT EXISTS`，不锁库存、不改批次；
- 通知只是提醒，不触发任何库存变动；真正处理仍走盘点/报损/入库。
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

EXPIRING_DAYS = 7

_EXPIRING_SQL = """
INSERT INTO notifications (type, batch_id, ingredient_id, scheduled_at, status, payload)
SELECT 'expiring', b.id, b.ingredient_id, now(), 'pending',
       jsonb_build_object(
         'batch_no', b.batch_no,
         'expiry_date', b.expiry_date,
         'remaining_weight', b.remaining_weight,
         'remaining_quantity', b.remaining_quantity
       )
  FROM batches b
 WHERE b.status = 'active'
   AND (b.remaining_weight > 0 OR b.remaining_quantity > 0)
   AND b.expiry_date IS NOT NULL
   AND b.expiry_date >= CURRENT_DATE
   AND b.expiry_date <= CURRENT_DATE + :days
   AND NOT EXISTS (
     SELECT 1 FROM notifications n
      WHERE n.type = 'expiring' AND n.batch_id = b.id AND n.status = 'pending'
   )
"""

_EXPIRED_SQL = """
INSERT INTO notifications (type, batch_id, ingredient_id, scheduled_at, status, payload)
SELECT 'expired', b.id, b.ingredient_id, now(), 'pending',
       jsonb_build_object(
         'batch_no', b.batch_no,
         'expiry_date', b.expiry_date,
         'remaining_weight', b.remaining_weight
       )
  FROM batches b
 WHERE b.status = 'active'
   AND (b.remaining_weight > 0 OR b.remaining_quantity > 0)
   AND b.expiry_date IS NOT NULL
   AND b.expiry_date < CURRENT_DATE
   AND NOT EXISTS (
     SELECT 1 FROM notifications n
      WHERE n.type = 'expired' AND n.batch_id = b.id AND n.status = 'pending'
   )
"""

_LOW_STOCK_SQL = """
INSERT INTO notifications (type, ingredient_id, scheduled_at, status, payload)
SELECT 'low_stock', v.ingredient_id, now(), 'pending',
       jsonb_build_object(
         'total_weight', v.total_weight,
         'total_quantity', v.total_quantity,
         'minimum_weight', i.minimum_weight,
         'minimum_quantity', i.minimum_quantity
       )
  FROM v_inventory v
  JOIN ingredients i ON i.id = v.ingredient_id
 WHERE v.is_low_stock
   AND NOT EXISTS (
     SELECT 1 FROM notifications n
      WHERE n.type = 'low_stock' AND n.ingredient_id = v.ingredient_id AND n.status = 'pending'
   )
"""


def scan(db: Session, *, days: int = EXPIRING_DAYS) -> dict:
    """扫描并生成待处理通知，返回各类型新增条数。"""
    counts = {}
    for key, sql, params in (
        ("expiring", _EXPIRING_SQL, {"days": days}),
        ("expired", _EXPIRED_SQL, {}),
        ("low_stock", _LOW_STOCK_SQL, {}),
    ):
        result = db.execute(text(sql), params)
        counts[key] = result.rowcount or 0
    db.flush()
    return {"created": sum(counts.values()), "by_type": counts}


def summary(db: Session) -> dict:
    """首页铃铛与提醒条用：待处理数 + 类型分布。"""
    rows = db.execute(
        text(
            "SELECT type, COUNT(*) AS n FROM notifications "
            "WHERE status = 'pending' GROUP BY type"
        )
    ).all()
    by_type = {r.type: int(r.n) for r in rows}
    return {
        "unread": sum(by_type.values()),
        "expiring": by_type.get("expiring", 0),
        "expired": by_type.get("expired", 0),
        "low_stock": by_type.get("low_stock", 0),
    }


def list_notifications(
    db: Session, *, status: str | None = "pending", page: int = 1, page_size: int = 20
) -> dict:
    where = "WHERE 1=1"
    params: dict = {}
    if status:
        where += " AND n.status = :status"
        params["status"] = status

    total = db.execute(
        text(f"SELECT COUNT(*) FROM notifications n {where}"), params  # noqa: S608 - 静态串
    ).scalar() or 0
    rows = db.execute(
        text(
            f"""
            SELECT n.id, n.type, n.batch_id, n.ingredient_id, n.status, n.payload,
                   n.created_at, n.sent_at,
                   COALESCE(i.name, '') AS ingredient_name,
                   COALESCE(b.batch_no, '') AS batch_no
              FROM notifications n
              LEFT JOIN ingredients i ON i.id = n.ingredient_id
              LEFT JOIN batches b ON b.id = n.batch_id
              {where}
             ORDER BY n.created_at DESC
             LIMIT :limit OFFSET :offset
            """  # noqa: S608 - where 由固定分支拼成，值全部参数化
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).all()

    return {
        "items": [
            {
                "id": r.id,
                "type": r.type,
                "batch_id": r.batch_id,
                "ingredient_id": r.ingredient_id,
                "ingredient_name": r.ingredient_name or (r.payload or {}).get("ingredient_name", ""),
                "batch_no": r.batch_no,
                "status": r.status,
                "payload": r.payload,
                "created_at": r.created_at,
                "sent_at": r.sent_at,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def mark_read(db: Session, notification_id: uuid.UUID) -> bool:
    """标记已读（status='sent'），前端通知中心用。"""
    result = db.execute(
        text(
            "UPDATE notifications SET status = 'sent', sent_at = now() "
            "WHERE id = CAST(:i AS uuid) AND status = 'pending'"
        ),
        {"i": str(notification_id)},
    )
    db.flush()
    return bool(result.rowcount)


def mark_all_read(db: Session) -> int:
    result = db.execute(
        text("UPDATE notifications SET status = 'sent', sent_at = now() WHERE status = 'pending'")
    )
    db.flush()
    return result.rowcount or 0
