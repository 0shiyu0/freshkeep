"""AI 辅助服务：识别草稿、人工修正、确认建档/入库。

铁律（阶段 8 验收）：
- `create_draft` / `update_draft` **只写 `recognition_drafts`**，绝不触碰 batches / transactions；
- 只有 `confirm` 会调用既有的建档或入库服务（入库仍走五步事务）；
- 每次确认写 `audit_logs(action='recognition_confirm')`，可追溯"哪张图、哪个 provider、改了什么"。
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from app.core.errors import ApiError, not_found, validation_error
from app.core.time import biz_today
from app.models import (
    FileAsset,
    Ingredient,
    IngredientBarcode,
    IngredientNutrition,
    NutritionDefinition,
    RecognitionDraft,
    Unit,
)
from app.services import files as file_svc
from app.services.ai.config import read_ai
from app.services.ai.provider import AIProviderError, recognize
from app.services.ai.validate import normalize_barcode, validate_dates
from sqlalchemy import select, text
from sqlalchemy.orm import Session


def _warn(code: str, message: str, field: str = "") -> dict:
    return {"code": code, "field": field, "message": message, "before": None, "after": None}


def _load_image(db: Session, file_id: uuid.UUID | None) -> tuple[bytes | None, str]:
    if not file_id:
        return None, ""
    asset = db.get(FileAsset, file_id)
    if asset is None:
        raise not_found("图片不存在")
    try:
        return file_svc.absolute_path(asset).read_bytes(), asset.mime_type
    except OSError:
        return None, asset.mime_type or ""


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _normalize(db: Session, raw: dict, warnings: list[dict]) -> dict:
    """把 provider/人工输入规范化为草稿结构，并做日期校验。"""
    name = (raw.get("name") or "").strip()
    barcode = normalize_barcode(raw.get("barcode"))
    prod = _parse_date(raw.get("production_date"))
    exp = _parse_date(raw.get("expiry_date"))
    shelf = raw.get("shelf_life_days")
    try:
        shelf = int(shelf) if shelf not in (None, "") else None
    except (TypeError, ValueError):
        shelf = None

    prod, exp, days, date_warnings = validate_dates(
        production_date=prod, expiry_date=exp, shelf_life_days=shelf, today=biz_today()
    )
    warnings.extend(date_warnings)

    nutrition = []
    for item in raw.get("nutrition") or []:
        code = (item.get("code") or "").strip()
        try:
            value = Decimal(str(item.get("value")))
            basis = Decimal(str(item.get("basis_amount") or 100))
        except Exception:
            warnings.append(_warn("NUTRITION_ITEM_INVALID", f"营养项 {code or '?'} 数值无法解析，已跳过"))
            continue
        if not code or value < 0 or basis <= 0:
            continue
        nutrition.append({
            "code": code, "value": str(value), "basis_amount": str(basis),
            "basis_unit": (item.get("basis_unit") or "g").strip() or "g",
        })

    return {
        "name": name,
        "brand": (raw.get("brand") or "").strip(),
        "specification": (raw.get("specification") or "").strip(),
        "barcode": barcode,
        "category": (raw.get("category") or "").strip(),
        "nutrition": nutrition,
        "production_date": prod.isoformat() if prod else None,
        "expiry_date": exp.isoformat() if exp else None,
        "shelf_life_days": days,
        "storage_location_id": raw.get("storage_location_id"),
        # 入库用（确认 target=batch 时使用）
        "weight": str(raw.get("weight") or ""),
        "quantity": str(raw.get("quantity") or ""),
        "purchase_cost": str(raw.get("purchase_cost") or ""),
    }


def create_draft(
    db: Session,
    *,
    image_file_id: uuid.UUID | None,
    hint: str,
    manual: dict | None,
    device_id: uuid.UUID | None,
) -> dict:
    """创建待确认草稿。AI 或人工输入都只落到本表，不产生任何库存变动。"""
    warnings: list[dict] = []
    provider_name, model = "manual", ""

    if manual:
        raw = dict(manual)
    else:
        cfg = read_ai(db)
        image_bytes, mime = _load_image(db, image_file_id)
        try:
            result = recognize(cfg=cfg, image_bytes=image_bytes, mime=mime, hint=hint)
            raw, provider_name, model = result.draft, result.provider, result.model
            if provider_name == "manual":
                warnings.append(_warn(
                    "AI_NOT_CONFIGURED",
                    "未配置视觉模型，已创建空白草稿，请手动填写或粘贴包装信息",
                ))
        except AIProviderError as exc:
            raw, provider_name = {}, "manual"
            warnings.append(_warn("AI_FAILED", f"{exc}；已降级为空白草稿，可手动填写"))

    draft = _normalize(db, raw or {}, warnings)
    if not draft["name"]:
        warnings.append(_warn("NAME_MISSING", "商品名称未识别到，请填写", "name"))

    row = RecognitionDraft(
        image_asset_id=image_file_id,
        provider=provider_name,
        model=model,
        status="pending",
        draft=draft,
        warnings=warnings,
        device_id=device_id,
    )
    db.add(row)
    db.flush()
    return serialize(row)


def serialize(row: RecognitionDraft) -> dict:
    return {
        "id": row.id,
        "status": row.status,
        "provider": row.provider,
        "model": row.model,
        "draft": row.draft,
        "warnings": row.warnings,
        "image_url": f"/api/v1/files/{row.image_asset_id}/raw" if row.image_asset_id else None,
        "confirmed_entity_type": row.confirmed_entity_type,
        "confirmed_entity_id": row.confirmed_entity_id,
        "created_at": row.created_at,
        "confirmed_at": row.confirmed_at,
    }


def update_draft(db: Session, draft_id: uuid.UUID, patch: dict) -> dict:
    """人工修正：重新校验日期，写回草稿。仍然不碰库存。"""
    row = db.get(RecognitionDraft, draft_id)
    if row is None:
        raise not_found("识别草稿不存在")
    if row.status != "pending":
        raise ApiError("RECOGNITION_NOT_PENDING", "草稿已确认或已拒绝，不能修改", 409)

    merged = {**(row.draft or {}), **patch}
    warnings: list[dict] = []
    row.draft = _normalize(db, merged, warnings)
    row.warnings = warnings
    db.flush()
    return serialize(row)


def _ensure_unit(db: Session, symbol: str) -> uuid.UUID | None:
    unit = db.execute(select(Unit).where(Unit.symbol == symbol)).scalars().first()
    return unit.id if unit else None


def confirm(
    db: Session,
    draft_id: uuid.UUID,
    *,
    target: str,
    ingredient_id: uuid.UUID | None,
    patch: dict | None,
    device_id: uuid.UUID | None,
) -> dict:
    """人工确认后才产生业务数据：建档（ingredient）或入库（batch，五步事务）。"""
    row = db.get(RecognitionDraft, draft_id)
    if row is None:
        raise not_found("识别草稿不存在")
    if row.status != "pending":
        raise ApiError("RECOGNITION_NOT_PENDING", "草稿已处理", 409)

    if patch:
        merged = {**(row.draft or {}), **patch}
        warnings: list[dict] = []
        row.draft = _normalize(db, merged, warnings)
        row.warnings = warnings

    draft = row.draft or {}
    if target == "ingredient":
        entity_id, extra = _create_ingredient(db, draft)
    elif target == "batch":
        entity_id, extra = _create_batch(db, draft, ingredient_id, device_id)
    else:
        raise validation_error("target 只能是 ingredient 或 batch")

    row.status = "confirmed"
    row.confirmed_entity_type = target
    row.confirmed_entity_id = entity_id
    row.confirmed_at = datetime.now(UTC)
    db.execute(
        text(
            "INSERT INTO audit_logs (action, object_type, object_id, before_json, after_json, device_id) "
            "VALUES ('recognition_confirm', :ot, CAST(:oid AS uuid), CAST(:b AS jsonb), CAST(:a AS jsonb), "
            "CAST(:did AS uuid))"
        ),
        {
            "ot": target,
            "oid": str(entity_id),
            "b": json.dumps({"draft_id": str(row.id), "draft": draft}, ensure_ascii=False),
            "a": json.dumps({"entity_id": str(entity_id), **extra}, ensure_ascii=False),
            "did": str(device_id) if device_id else None,
        },
    )
    db.flush()
    return {"draft": serialize(row), **extra}


def _create_ingredient(db: Session, draft: dict) -> tuple[uuid.UUID, dict]:
    name = (draft.get("name") or "").strip()
    if not name:
        raise validation_error("确认建档前必须填写商品名称")

    existing = db.execute(select(Ingredient).where(Ingredient.name == name)).scalars().first()
    if existing is not None:
        raise ApiError(
            "INGREDIENT_EXISTS",
            f"已存在同名食材「{name}」，请改选「入库到已有食材」或修改名称",
            409,
            existing_id=str(existing.id),
        )

    gid = _ensure_unit(db, "g")
    ing = Ingredient(
        name=name,
        name_pinyin="",   # 由 service 统一生成（阶段 2 规则），此处留空后补
        name_initials="",
        brand=draft.get("brand") or "",
        specification=draft.get("specification") or "",
        default_weight_unit_id=gid,
    )
    db.add(ing)
    db.flush()

    # 拼音必须走统一生成（services/search.to_pinyin 返回 (全拼, 首字母)），否则搜不到
    from app.services.search import to_pinyin

    ing.name_pinyin, ing.name_initials = to_pinyin(name)

    defs = {d.code: d for d in db.execute(select(NutritionDefinition)).scalars()}
    for item in draft.get("nutrition") or []:
        definition = defs.get(item.get("code"))
        if definition is None:
            continue
        basis_unit_id = _ensure_unit(db, item.get("basis_unit") or "g") or gid
        if basis_unit_id is None:
            continue
        db.add(IngredientNutrition(
            ingredient_id=ing.id,
            nutrition_definition_id=definition.id,
            value=Decimal(item["value"]),
            basis_amount=Decimal(item["basis_amount"]),
            basis_unit_id=basis_unit_id,
            source="manual",
            version=1,
            is_current=True,
        ))

    barcode_note = ""
    code = draft.get("barcode") or ""
    if code:
        taken = db.execute(
            select(IngredientBarcode).where(IngredientBarcode.barcode == code)
        ).scalars().first()
        if taken is None:
            db.add(IngredientBarcode(ingredient_id=ing.id, barcode=code, barcode_type="ean13"))
        else:
            barcode_note = "条码已被其他食材占用，未绑定"

    db.flush()
    return ing.id, {"ingredient_id": str(ing.id), "note": barcode_note}


def _create_batch(
    db: Session, draft: dict, ingredient_id: uuid.UUID | None, device_id: uuid.UUID | None
) -> tuple[uuid.UUID, dict]:
    from app.services.inventory import create_batch

    if ingredient_id is None:
        raise validation_error("入库前必须选择已有食材")
    weight = Decimal(str(draft.get("weight") or "0"))
    quantity = Decimal(str(draft.get("quantity") or "0"))
    if weight <= 0 and quantity <= 0:
        raise validation_error("入库前必须填写重量或数量")

    ingredient = db.get(Ingredient, ingredient_id)
    if ingredient is None:
        raise not_found("食材不存在")

    batch, tx = create_batch(
        db,
        ingredient_id=ingredient_id,
        purchase_date=None,
        production_date=_parse_date(draft.get("production_date")),
        expiry_date=_parse_date(draft.get("expiry_date")),
        opened_date=None,
        storage_location_id=uuid.UUID(draft["storage_location_id"]) if draft.get("storage_location_id") else None,
        quantity=quantity,
        weight_in=weight,
        purchase_cost=Decimal(str(draft.get("purchase_cost") or "0")),
        quantity_unit_id=ingredient.default_quantity_unit_id,
        weight_unit_id=ingredient.default_weight_unit_id,
        note="AI 识别确认入库",
        device_id=device_id,
    )
    return batch.id, {"batch_id": str(batch.id), "transaction_no": tx.transaction_no}


def reject(db: Session, draft_id: uuid.UUID) -> dict:
    row = db.get(RecognitionDraft, draft_id)
    if row is None:
        raise not_found("识别草稿不存在")
    if row.status != "pending":
        raise ApiError("RECOGNITION_NOT_PENDING", "草稿已处理", 409)
    row.status = "rejected"
    db.flush()
    return serialize(row)
