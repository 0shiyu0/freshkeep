"""ORM 实体（阶段 2 用到的 11 张表）。

只映射列，不在 ORM 里重复声明约束/索引——DDL 是唯一真相（database/001_init.sql），
ORM 改动必须与 DDL 对齐，否则 pre-commit 的文档同步检查会提醒。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=text("now()"))


MONEY = Numeric(14, 2)
QTY = Numeric(14, 3)
NUTRI = Numeric(14, 4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    username: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, default="")
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PairCode(Base):
    __tablename__ = "pair_codes"

    id: Mapped[uuid.UUID] = _pk()
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class FileAsset(Base):
    __tablename__ = "file_assets"

    id: Mapped[uuid.UUID] = _pk()
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, default="image")
    created_at: Mapped[datetime] = _now()


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id")
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _now()

    parent: Mapped[Category | None] = relationship(remote_side="Category.id", lazy="joined")


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, default="")
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    precision: Mapped[int] = mapped_column(SmallInteger, default=3)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()


class StorageLocation(Base):
    __tablename__ = "storage_locations"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class NutritionDefinition(Base):
    __tablename__ = "nutrition_definitions"

    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_pinyin: Mapped[str] = mapped_column(Text, default="")
    name_initials: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id")
    )
    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("file_assets.id")
    )
    brand: Mapped[str] = mapped_column(Text, default="")
    specification: Mapped[str] = mapped_column(Text, default="")
    default_quantity_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id")
    )
    default_weight_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id")
    )
    # 1 个数量单位 = N 克（N 以"克"为基准存储）；NULL 表示不支持换算
    default_unit_weight: Mapped[Decimal | None] = mapped_column(QTY)
    nutrition_basis_amount: Mapped[Decimal | None] = mapped_column(QTY)
    nutrition_basis_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id")
    )
    default_storage_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("storage_locations.id")
    )
    minimum_quantity: Mapped[Decimal] = mapped_column(QTY, default=0)
    minimum_weight: Mapped[Decimal] = mapped_column(QTY, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()

    barcodes: Mapped[list[IngredientBarcode]] = relationship(
        back_populates="ingredient", cascade="all, delete-orphan", lazy="selectin"
    )
    nutrition: Mapped[list[IngredientNutrition]] = relationship(
        back_populates="ingredient", cascade="all, delete-orphan", lazy="selectin"
    )


class IngredientBarcode(Base):
    __tablename__ = "ingredient_barcodes"

    id: Mapped[uuid.UUID] = _pk()
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id")
    )
    barcode: Mapped[str] = mapped_column(Text, nullable=False)
    barcode_type: Mapped[str] = mapped_column(Text, default="ean13")
    created_at: Mapped[datetime] = _now()

    ingredient: Mapped[Ingredient] = relationship(back_populates="barcodes")


class IngredientNutrition(Base):
    __tablename__ = "ingredient_nutrition"

    id: Mapped[uuid.UUID] = _pk()
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id")
    )
    nutrition_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nutrition_definitions.id")
    )
    value: Mapped[Decimal] = mapped_column(NUTRI, nullable=False)
    basis_amount: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    basis_unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("units.id"))
    source: Mapped[str] = mapped_column(Text, default="manual")
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _now()

    ingredient: Mapped[Ingredient] = relationship(back_populates="nutrition")


class Batch(Base):
    """批次：某一次采购的库存实体（PRD §4.4）。

    remaining_* 是缓存，必须可由 transaction_allocations 聚合重算（v_batch_reconcile）。
    updated_at 由数据库触发器 trg_batches_updated 维护，ORM 不重复声明 onupdate。
    """

    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = _pk()
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id")
    )
    batch_no: Mapped[str] = mapped_column(Text, nullable=False)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    production_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    opened_date: Mapped[date | None] = mapped_column(Date)
    storage_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("storage_locations.id")
    )
    initial_quantity: Mapped[Decimal] = mapped_column(QTY, default=0)
    remaining_quantity: Mapped[Decimal] = mapped_column(QTY, default=0)
    initial_weight: Mapped[Decimal] = mapped_column(QTY, default=0)
    remaining_weight: Mapped[Decimal] = mapped_column(QTY, default=0)
    purchase_cost: Mapped[Decimal] = mapped_column(MONEY, default=0)
    remaining_cost: Mapped[Decimal] = mapped_column(MONEY, default=0)
    status: Mapped[str] = mapped_column(Text, default="active")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()

    ingredient: Mapped[Ingredient] = relationship(lazy="joined")
    storage_location: Mapped[StorageLocation | None] = relationship(lazy="joined")


class InventoryTransaction(Base):
    """库存流水：任何库存变化的唯一真相（PRD §3.3 原则 3）。"""

    __tablename__ = "inventory_transactions"

    id: Mapped[uuid.UUID] = _pk()
    transaction_no: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id")
    )
    quantity_delta: Mapped[Decimal] = mapped_column(QTY, default=0)
    weight_delta: Mapped[Decimal] = mapped_column(QTY, default=0)
    cost_delta: Mapped[Decimal] = mapped_column(MONEY, default=0)
    related_object_type: Mapped[str | None] = mapped_column(Text)
    related_object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(Text, default="")
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id")
    )
    created_at: Mapped[datetime] = _now()


class TransactionAllocation(Base):
    """分配：一笔流水对某个批次的作用量。Σ分配 == 流水 delta 是硬不变式。"""

    __tablename__ = "transaction_allocations"

    id: Mapped[uuid.UUID] = _pk()
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_transactions.id")
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("batches.id"))
    quantity_delta: Mapped[Decimal] = mapped_column(QTY, default=0)
    weight_delta: Mapped[Decimal] = mapped_column(QTY, default=0)
    cost_delta: Mapped[Decimal] = mapped_column(MONEY, default=0)
    unit_cost: Mapped[Decimal | None] = mapped_column(NUTRI)
    created_at: Mapped[datetime] = _now()


class ConsumptionRecord(Base):
    """消耗单：一次消耗的业务单据（PRD §4.5）。status 只能经 services/consumption/state.py 迁移。"""

    __tablename__ = "consumption_records"

    id: Mapped[uuid.UUID] = _pk()
    consumption_no: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id")
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_transactions.id"), unique=True
    )
    quantity: Mapped[Decimal] = mapped_column(QTY, default=0)
    weight: Mapped[Decimal] = mapped_column(QTY, default=0)
    quantity_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id")
    )
    weight_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id")
    )
    cost: Mapped[Decimal] = mapped_column(MONEY, default=0)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="completed")
    reversed_by_transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id")
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class ConsumptionNutrition(Base):
    """营养快照：消耗发生时冻结，后续改营养档案不影响历史（PRD §3.3 原则 7）。"""

    __tablename__ = "consumption_nutrition"

    id: Mapped[uuid.UUID] = _pk()
    consumption_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consumption_records.id")
    )
    nutrition_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nutrition_definitions.id")
    )
    actual_value: Mapped[Decimal] = mapped_column(NUTRI, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    basis_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _now()


class IdempotencyKey(Base):
    """写操作幂等记录：同 key 同 body 返回原响应（见 app/core/middleware.py）。"""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _now()


class RecognitionDraft(Base):
    """AI 识别草稿（阶段 8）：与库存表零耦合，确认后才触发建档/入库。"""

    __tablename__ = "recognition_drafts"

    id: Mapped[uuid.UUID] = _pk()
    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("file_assets.id")
    )
    provider: Mapped[str] = mapped_column(Text, default="manual")
    model: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="pending")
    draft: Mapped[dict] = mapped_column(JSONB, default=dict)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    confirmed_entity_type: Mapped[str | None] = mapped_column(Text)
    confirmed_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id")
    )
    created_at: Mapped[datetime] = _now()
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Recipe(Base):
    """菜谱（阶段 8.11）：步骤存 text，食材需求见 RecipeItem。"""

    __tablename__ = "recipes"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("file_assets.id")
    )
    category: Mapped[str] = mapped_column(Text, default="")
    servings: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=1)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    steps: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _now()


class RecipeItem(Base):
    __tablename__ = "recipe_items"

    id: Mapped[uuid.UUID] = _pk()
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE")
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id")
    )
    quantity: Mapped[Decimal | None] = mapped_column(QTY)
    weight: Mapped[Decimal | None] = mapped_column(QTY)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id")
    )
    note: Mapped[str] = mapped_column(Text, default="")


class RecipeStep(Base):
    """菜谱步骤（阶段 8 收尾）：按 seq 排序，单步可带时长。"""

    __tablename__ = "recipe_steps"

    id: Mapped[uuid.UUID] = _pk()
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now()
