"""0003 · AI 识别草稿表

阶段 8 的硬约束：AI 识别结果**只能**落到本表，禁止直接写 batches / inventory_transactions。
人工确认后，才由确认接口调用既有的建档或入库服务（五步事务）。

`draft` 存规范化后的待确认字段（name/brand/spec/nutrition/dates/barcode），
`warnings` 存校验提示（如生产日期与保质期疑似互错），前端据此要求人工修正。
"""
from __future__ import annotations

from alembic import op

revision = "0003_recognition_drafts"
down_revision = "0002_ingredient_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS recognition_drafts (
          id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          image_asset_id        uuid REFERENCES file_assets (id) ON DELETE SET NULL,
          provider              text NOT NULL DEFAULT 'manual',
          model                 text NOT NULL DEFAULT '',
          status                text NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'confirmed', 'rejected')),
          draft                 jsonb NOT NULL DEFAULT '{}'::jsonb,
          warnings              jsonb NOT NULL DEFAULT '[]'::jsonb,
          confirmed_entity_type text
                                CHECK (confirmed_entity_type IN ('ingredient', 'batch')),
          confirmed_entity_id   uuid,
          device_id             uuid REFERENCES devices (id) ON DELETE SET NULL,
          created_at            timestamptz NOT NULL DEFAULT now(),
          confirmed_at          timestamptz,
          CONSTRAINT ck_recognition_confirmed CHECK (
            (status = 'pending' AND confirmed_entity_type IS NULL AND confirmed_at IS NULL)
            OR (status = 'confirmed' AND confirmed_entity_type IS NOT NULL AND confirmed_at IS NOT NULL)
            OR (status = 'rejected' AND confirmed_entity_type IS NULL)
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recognition_status "
        "ON recognition_drafts (status, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recognition_drafts")
