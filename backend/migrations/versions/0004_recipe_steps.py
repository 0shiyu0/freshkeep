"""0004 · 菜谱步骤结构化

阶段 8 收尾：把 `recipes.steps`（纯文本）升级为独立表 `recipe_steps`，
支持统一解析（顺序、单步时长）与前端有序展示。

兼容策略：
- 保留 `recipes.steps` 旧列，读取时若新表为空则按行拆分返回（标记 `legacy`）；
- 写入时字符串按行拆分、数组按结构化存；旧数据不需要迁移脚本。
"""
from __future__ import annotations

from alembic import op

revision = "0004_recipe_steps"
down_revision = "0003_recognition_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_steps (
          id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          recipe_id        uuid NOT NULL REFERENCES recipes (id) ON DELETE CASCADE,
          seq              integer NOT NULL CHECK (seq >= 0),
          text             text NOT NULL,
          duration_minutes integer CHECK (duration_minutes >= 0),
          created_at       timestamptz NOT NULL DEFAULT now(),
          UNIQUE (recipe_id, seq)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recipe_steps_recipe ON recipe_steps (recipe_id, seq)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recipe_steps")
