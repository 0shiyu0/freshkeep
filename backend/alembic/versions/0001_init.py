"""0001 · 初始结构

DDL 的唯一真相是 database/001_init.sql。本迁移只做两件事：
1. 找到那份 SQL 文件并执行；
2. 剥掉它自带的 BEGIN/COMMIT —— Alembic 已经在一个事务里，
   嵌套的 COMMIT 会提前提交 alembic 的版本记录，导致版本表与实际结构不一致。

改表结构时：改 database/001_init.sql，不要在这里手写 DDL。
"""
from __future__ import annotations

import re
from pathlib import Path

from alembic import op

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def _find_sql() -> Path:
    """向上逐级找 database/001_init.sql，兼容仓库根目录与容器 /app 两种布局。"""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "database" / "001_init.sql"
        if candidate.is_file():
            return candidate
    raise RuntimeError("找不到 database/001_init.sql")


def _load_sql() -> str:
    sql = _find_sql().read_text(encoding="utf-8")
    # 去掉独立成行的 BEGIN; / COMMIT;（保留语句内部的），交给 Alembic 管事务
    sql = re.sub(r"(?im)^\s*BEGIN\s*;\s*$", "", sql)
    sql = re.sub(r"(?im)^\s*COMMIT\s*;\s*$", "", sql)
    return sql


def upgrade() -> None:
    op.execute(_load_sql())


def downgrade() -> None:
    """整库回退：按依赖倒序删表。生产不靠它，只在本地重建时用。"""
    op.execute(
        """
        DROP VIEW IF EXISTS v_batch_reconcile;
        DROP VIEW IF EXISTS v_inventory;
        DROP TABLE IF EXISTS idempotency_keys, audit_logs, app_settings, notifications,
            recipe_items, recipes, shopping_list_items, shopping_lists,
            consumption_nutrition, consumption_records, transaction_allocations,
            inventory_transactions, batches, nutrition_targets, ingredient_nutrition,
            nutrition_definitions, ingredient_barcodes, ingredients, storage_locations,
            units, categories, file_assets, pair_codes, devices, users CASCADE;
        """
    )
