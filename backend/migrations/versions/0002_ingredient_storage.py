"""0002 · ingredients 增加默认储存位置

阶段 2 的食材档案详情要展示「储存位置」，PRD §4.3 的库存策略字段组也包含"默认储存位置"，
但 0001 建表时漏了这一列。批次上的 storage_location_id 仍然保留（批次可覆盖档案默认值）。

幂等：ADD COLUMN IF NOT EXISTS，新建库（0001 已含该列）执行本迁移为空操作。
"""
from __future__ import annotations

from alembic import op

revision = "0002_ingredient_storage"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ingredients "
        "ADD COLUMN IF NOT EXISTS default_storage_location_id uuid "
        "REFERENCES storage_locations (id) ON DELETE SET NULL"
    )
    # 按默认位置筛选食材时会用到
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ingredients_location "
        "ON ingredients (default_storage_location_id) WHERE is_active"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ingredients_location")
    op.execute("ALTER TABLE ingredients DROP COLUMN IF EXISTS default_storage_location_id")
