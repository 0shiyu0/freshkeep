"""ORM 实体（阶段 2 用到的 11 张表）。

只映射列，不在 ORM 里重复声明约束/索引——DDL 是唯一真相（database/001_init.sql），
ORM 改动必须与 DDL 对齐，否则 pre-commit 的文档同步检查会提醒。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, Text, text
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

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id", lazy="joined")


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

    barcodes: Mapped[list["IngredientBarcode"]] = relationship(
        back_populates="ingredient", cascade="all, delete-orphan", lazy="selectin"
    )
    nutrition: Mapped[list["IngredientNutrition"]] = relationship(
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


class IdempotencyKey(Base):
    """写操作幂等记录：同 key 同 body 返回原响应（见 app/core/middleware.py）。"""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _now()
