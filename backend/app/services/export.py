"""CSV 导出（M7）：流式输出，带 BOM 便于 Excel 直接打开。"""
from __future__ import annotations

from sqlalchemy.orm import Session

BOM = "\ufeff".encode()

EXPORTS = {
    "transactions": """
        SELECT t.transaction_no, t.type, i.name AS ingredient_name,
               t.quantity_delta, t.weight_delta, t.cost_delta, t.reason, t.created_at
          FROM inventory_transactions t
          JOIN ingredients i ON i.id = t.ingredient_id
         ORDER BY t.created_at
    """,
    "consumptions": """
        SELECT c.consumption_no, i.name AS ingredient_name, c.quantity, c.weight,
               c.cost, c.status, c.consumed_at, c.note
          FROM consumption_records c
          JOIN ingredients i ON i.id = c.ingredient_id
         ORDER BY c.consumed_at
    """,
}


def stream_csv(db: Session, kind: str):
    """生成器：先发 BOM，再按 COPY 块流式输出。"""
    sql = EXPORTS.get(kind)
    if sql is None:
        raise ValueError(f"未知导出类型：{kind}")

    yield BOM
    conn = db.connection().connection
    with conn.cursor() as cur, cur.copy(
        f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER)"
    ) as cp:
        yield from cp
