"""食材档案：新增、编辑、详情、停用、搜索（中文/拼音/首字母）。

换算规则（PRD §5.3）：
- `default_unit_weight` = 1 个数量单位折合多少克；为 NULL 即"无换算关系"
- 无换算关系时**任何数量↔重量的自动推算都必须被拒绝**（见 /conversion 接口）
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.core.errors import ApiError, conflict, not_found, validation_error
from app.db.session import get_db
from app.models import (
    Category,
    FileAsset,
    Ingredient,
    IngredientBarcode,
    IngredientNutrition,
    NutritionDefinition,
    StorageLocation,
    Unit,
)
from app.schemas.common import ok
from app.schemas.ingredient import (
    BarcodeIn,
    CategoryBrief,
    IngredientDetail,
    IngredientIn,
    IngredientListItem,
    IngredientUpdate,
    NutritionReplace,
    UnitBrief,
)
from app.services.search import relevance_order, search_filter, to_pinyin

router = APIRouter(prefix="/ingredients", tags=["ingredients"])


# ---------------------------------------------------------------- 小工具


def _fmt_num(value: Decimal | None) -> str:
    """250.000 → '250'；1.5 → '1.5'。用于展示，不参与计算。"""
    if value is None:
        return "0"
    text = format(value.normalize(), "f")
    return text


def _unit_brief(unit: Unit | None) -> UnitBrief | None:
    if unit is None:
        return None
    return UnitBrief(id=unit.id, name=unit.name, symbol=unit.symbol, dimension=unit.dimension)


def _cat_brief(cat: Category | None, parent: Category | None) -> CategoryBrief | None:
    if cat is None:
        return None
    path = f"{parent.name} · {cat.name}" if parent else cat.name
    return CategoryBrief(
        id=cat.id, name=cat.name, parent_name=parent.name if parent else None, path=path
    )


def _lookups(db: Session, rows: list[Ingredient]) -> dict:
    """批量取引用对象，避免 N+1。"""
    cat_ids = {r.category_id for r in rows if r.category_id}
    unit_ids = {u for r in rows for u in (r.default_quantity_unit_id, r.default_weight_unit_id)}
    loc_ids = {r.default_storage_location_id for r in rows if r.default_storage_location_id}
    img_ids = {r.image_asset_id for r in rows if r.image_asset_id}

    cats = {c.id: c for c in db.execute(select(Category).where(Category.id.in_(cat_ids))).scalars()} if cat_ids else {}
    parent_ids = {c.parent_id for c in cats.values() if c.parent_id}
    parents = (
        {p.id: p for p in db.execute(select(Category).where(Category.id.in_(parent_ids))).scalars()}
        if parent_ids
        else {}
    )
    units = {u.id: u for u in db.execute(select(Unit).where(Unit.id.in_(unit_ids))).scalars()} if unit_ids else {}
    locs = (
        {l.id: l for l in db.execute(select(StorageLocation).where(StorageLocation.id.in_(loc_ids))).scalars()}
        if loc_ids
        else {}
    )
    images = (
        {a.id: a for a in db.execute(select(FileAsset).where(FileAsset.id.in_(img_ids))).scalars()}
        if img_ids
        else {}
    )
    return {"cats": cats, "parents": parents, "units": units, "locs": locs, "images": images}


def _base_fields(ing: Ingredient, lk: dict) -> dict:
    cat = lk["cats"].get(ing.category_id) if ing.category_id else None
    parent = lk["parents"].get(cat.parent_id) if cat and cat.parent_id else None
    q_unit = lk["units"].get(ing.default_quantity_unit_id) if ing.default_quantity_unit_id else None
    w_unit = lk["units"].get(ing.default_weight_unit_id) if ing.default_weight_unit_id else None
    loc = lk["locs"].get(ing.default_storage_location_id) if ing.default_storage_location_id else None

    if ing.default_unit_weight is not None and w_unit is not None:
        unit_weight_display = f"{_fmt_num(ing.default_unit_weight)}{w_unit.symbol or w_unit.name}"
    else:
        unit_weight_display = "未设置"

    if ing.minimum_weight and w_unit:
        min_display = f"{_fmt_num(ing.minimum_weight)}{w_unit.symbol or w_unit.name}"
    elif ing.minimum_quantity and q_unit:
        min_display = f"{_fmt_num(ing.minimum_quantity)}{q_unit.symbol or q_unit.name}"
    else:
        min_display = "未设置"

    return {
        "id": ing.id,
        "name": ing.name,
        "category_id": ing.category_id,
        "category_path": (_cat_brief(cat, parent).path if cat else "未分类"),
        "image_url": (f"/api/v1/files/{ing.image_asset_id}/raw" if ing.image_asset_id else None),
        "quantity_unit": _unit_brief(q_unit),
        "weight_unit": _unit_brief(w_unit),
        "unit_weight_display": unit_weight_display,
        "minimum_stock_display": min_display,
        "location_name": loc.name if loc else None,
        "is_active": ing.is_active,
        "updated_at": ing.updated_at,
    }


# ---------------------------------------------------------------- 校验


def _get_unit(db: Session, unit_id: uuid.UUID | None, expect: str, label: str) -> Unit | None:
    if unit_id is None:
        return None
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise not_found(f"{label}不存在")
    if unit.dimension != expect:
        raise validation_error(f"{label}必须是「{'数量' if expect == 'quantity' else '重量'}」类单位，当前是 {unit.dimension}")
    return unit


def _validate_conversion(
    *, unit_weight: Decimal | None, q_unit: Unit | None, w_unit: Unit | None
) -> None:
    """换算关系必须成对出现；有值则两个单位都要有。"""
    if unit_weight is None:
        return
    if unit_weight <= 0:
        raise validation_error("每包重量（换算值）必须大于 0")
    if q_unit is None or w_unit is None:
        raise validation_error("设置每包重量前，请先选择数量单位与重量单位")


def _resolve_refs(db: Session, data: dict) -> dict:
    """把引用 id 换成对象并校验存在性/维度，返回补齐后的上下文。"""
    if data.get("category_id"):
        if db.get(Category, data["category_id"]) is None:
            raise not_found("分类不存在")
    if data.get("default_storage_location_id"):
        if db.get(StorageLocation, data["default_storage_location_id"]) is None:
            raise not_found("储存位置不存在")
    if data.get("image_asset_id"):
        if db.get(FileAsset, data["image_asset_id"]) is None:
            raise not_found("图片不存在")
    if data.get("nutrition_basis_unit_id"):
        if db.get(Unit, data["nutrition_basis_unit_id"]) is None:
            raise not_found("营养基准单位不存在")

    q_unit = _get_unit(db, data.get("default_quantity_unit_id"), "quantity", "数量单位")
    w_unit = _get_unit(db, data.get("default_weight_unit_id"), "weight", "重量单位")
    if q_unit and w_unit and q_unit.id == w_unit.id:
        raise validation_error("数量单位与重量单位不能是同一个")
    return {"q_unit": q_unit, "w_unit": w_unit}


# ---------------------------------------------------------------- 列表 / 搜索


@router.get("", summary="食材列表（支持中文模糊、全拼、首字母搜索）")
def list_ingredients(
    request: Request,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    include_inactive: bool = False,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    if sort_by not in {"name", "updated_at", "created_at"}:
        raise validation_error("sort_by 只能是 name / updated_at / created_at")
    if sort_order not in {"asc", "desc"}:
        raise validation_error("sort_order 只能是 asc / desc")

    stmt = select(Ingredient)
    if q and q.strip():
        keyword = q.strip().lower()
        stmt = stmt.where(
            search_filter(Ingredient.name, Ingredient.name_pinyin, Ingredient.name_initials, keyword)
        )
    if category_id:
        # 选中父分类时连带其子分类
        child_ids = db.execute(
            select(Category.id).where(Category.parent_id == category_id)
        ).scalars().all()
        stmt = stmt.where(Ingredient.category_id.in_([category_id, *child_ids]))
    if location_id:
        stmt = stmt.where(Ingredient.default_storage_location_id == location_id)
    # 默认只列启用项；管理端需要看全部时传 include_inactive=true
    if not include_inactive:
        stmt = stmt.where(Ingredient.is_active.is_(True if is_active is None else is_active))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    if q and q.strip():
        stmt = stmt.order_by(relevance_order(Ingredient.name, Ingredient.name_pinyin, q.strip().lower()))
    col = getattr(Ingredient, sort_by)
    stmt = stmt.order_by(col.desc() if sort_order == "desc" else col.asc(), Ingredient.name)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = db.execute(stmt).scalars().all()
    lk = _lookups(db, rows)
    items = [
        IngredientListItem(**_base_fields(r, lk)).model_dump(mode="json") for r in rows
    ]
    return ok(request, {"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/search", summary="搜索建议（轻量，供输入框联想）")
def search_suggest(
    request: Request,
    q: str = "",
    limit: int = 8,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    keyword = (q or "").strip().lower()
    if not keyword:
        return ok(request, {"items": []})
    stmt = (
        select(Ingredient)
        .where(
            Ingredient.is_active.is_(True),
            search_filter(Ingredient.name, Ingredient.name_pinyin, Ingredient.name_initials, keyword),
        )
        .order_by(relevance_order(Ingredient.name, Ingredient.name_pinyin, keyword), Ingredient.name)
        .limit(min(max(1, limit), 20))
    )
    rows = db.execute(stmt).scalars().all()
    return ok(
        request,
        {"items": [{"id": str(r.id), "name": r.name, "pinyin": r.name_pinyin} for r in rows]},
    )


# ---------------------------------------------------------------- 详情


@router.get("/{ingredient_id}", summary="食材详情（含分类标签、单位、换算、储存位置）")
def detail(
    request: Request,
    ingredient_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        raise not_found("食材不存在")
    lk = _lookups(db, [ing])
    base = _base_fields(ing, lk)

    basis_unit = db.get(Unit, ing.nutrition_basis_unit_id) if ing.nutrition_basis_unit_id else None
    if ing.nutrition_basis_amount and basis_unit:
        basis_display = f"每{_fmt_num(ing.nutrition_basis_amount)}{basis_unit.symbol or basis_unit.name}"
    else:
        basis_display = "未设置（不参与营养统计）"

    defs = {d.id: d for d in db.execute(select(NutritionDefinition)).scalars()}
    nutrition = [
        {
            "code": defs[n.nutrition_definition_id].code if n.nutrition_definition_id in defs else "",
            "name": defs[n.nutrition_definition_id].name if n.nutrition_definition_id in defs else "",
            "unit": defs[n.nutrition_definition_id].unit if n.nutrition_definition_id in defs else "",
            "value": format(n.value.normalize(), "f"),
            "basis_amount": format(n.basis_amount.normalize(), "f"),
        }
        for n in sorted(ing.nutrition, key=lambda x: (defs.get(x.nutrition_definition_id).sort_order if defs.get(x.nutrition_definition_id) else 99))
        if n.is_current
    ]

    data = IngredientDetail(
        **base,
        brand=ing.brand,
        specification=ing.specification,
        note=ing.note,
        nutrition_basis_display=basis_display,
        default_unit_weight=ing.default_unit_weight,
        minimum_quantity=ing.minimum_quantity,
        minimum_weight=ing.minimum_weight,
        can_convert=ing.default_unit_weight is not None,
        barcodes=[BarcodeIn(barcode=b.barcode, barcode_type=b.barcode_type) for b in ing.barcodes],
        nutrition=nutrition,
        created_at=ing.created_at,
    )
    return ok(request, data.model_dump(mode="json"))


# ---------------------------------------------------------------- 新增 / 修改


def _apply_nutrition(db: Session, ing: Ingredient, items) -> None:
    """整体替换当前营养档案：旧行置 is_current=false 并升版本，插入新行。"""
    defs = {d.code: d for d in db.execute(select(NutritionDefinition)).scalars()}
    for old in list(ing.nutrition):
        if old.is_current:
            old.is_current = False
    for item in items:
        definition = defs.get(item.code)
        if definition is None:
            raise validation_error(f"未知营养项目：{item.code}")
        db.add(
            IngredientNutrition(
                ingredient_id=ing.id,
                nutrition_definition_id=definition.id,
                value=item.value,
                basis_amount=item.basis_amount,
                basis_unit_id=item.basis_unit_id,
                source="manual",
                version=1,
                is_current=True,
            )
        )


@router.post("", status_code=201, summary="新增食材")
def create(
    request: Request,
    payload: IngredientIn,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    data = payload.model_dump(exclude={"barcodes", "nutrition"})
    refs = _resolve_refs(db, data)
    _validate_conversion(
        unit_weight=data.get("default_unit_weight"),
        q_unit=refs["q_unit"],
        w_unit=refs["w_unit"],
    )

    full, initials = to_pinyin(data["name"])
    ing = Ingredient(**data, name_pinyin=full, name_initials=initials)
    db.add(ing)
    db.flush()

    for b in payload.barcodes:
        db.add(IngredientBarcode(ingredient_id=ing.id, barcode=b.barcode, barcode_type=b.barcode_type))
    if payload.nutrition:
        _apply_nutrition(db, ing, payload.nutrition)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "barcode" in str(exc.orig):
            raise conflict("该条码已绑定到其他食材") from None
        raise conflict("数据冲突，请检查唯一字段") from None

    db.refresh(ing)
    return ok(request, {"id": str(ing.id)}, "食材已创建")


@router.put("/{ingredient_id}", summary="编辑食材")
def update(
    request: Request,
    ingredient_id: uuid.UUID,
    payload: IngredientUpdate,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        raise not_found("食材不存在")

    changes = payload.model_dump(exclude_unset=True, exclude={"nutrition"})
    # 合并后整体校验，避免只改一半导致规则失效
    merged = {k: getattr(ing, k) for k in (
        "default_quantity_unit_id",
        "default_weight_unit_id",
        "default_unit_weight",
        "nutrition_basis_amount",
        "nutrition_basis_unit_id",
    )}
    merged.update({k: v for k, v in changes.items() if k in merged})
    refs = _resolve_refs(db, merged)
    _validate_conversion(
        unit_weight=merged["default_unit_weight"],
        q_unit=refs["q_unit"],
        w_unit=refs["w_unit"],
    )

    if changes.get("name") and changes["name"] != ing.name:
        full, initials = to_pinyin(changes["name"])
        ing.name_pinyin = full
        ing.name_initials = initials

    for key, value in changes.items():
        setattr(ing, key, value)
    if payload.nutrition is not None:
        _apply_nutrition(db, ing, payload.nutrition)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("数据冲突，请检查唯一字段") from None
    return ok(request, {"id": str(ing.id)}, "已保存")


@router.post("/{ingredient_id}/deactivate", summary="停用食材（有历史记录时的推荐做法）")
def deactivate(
    request: Request,
    ingredient_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        raise not_found("食材不存在")
    ing.is_active = False
    db.commit()
    return ok(request, {"is_active": False}, "已停用")


@router.post("/{ingredient_id}/activate", summary="重新启用食材")
def activate(
    request: Request,
    ingredient_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        raise not_found("食材不存在")
    ing.is_active = True
    db.commit()
    return ok(request, {"is_active": True}, "已启用")


@router.get("/{ingredient_id}/conversion", summary="按换算关系换算（无换算关系直接 422）")
def convert(
    request: Request,
    ingredient_id: uuid.UUID,
    quantity: Decimal = Decimal("1"),
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    """数量 → 重量。`default_unit_weight` 为空时**拒绝推算**，而不是返回 0 或猜一个值。"""
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        raise not_found("食材不存在")
    if ing.default_unit_weight is None:
        raise ApiError(
            "UNIT_NOT_CONVERTIBLE",
            "该食材未设置每包重量，数量与重量之间没有换算关系，不能自动推算",
            422,
        )
    if quantity <= 0:
        raise validation_error("quantity 必须大于 0")
    weight = (quantity * ing.default_unit_weight).quantize(Decimal("0.001"))
    return ok(
        request,
        {
            "quantity": format(quantity.normalize(), "f"),
            "weight": format(weight.normalize(), "f"),
            "unit_weight": format(ing.default_unit_weight.normalize(), "f"),
            "basis": "default_unit_weight（克）",
        },
    )


@router.put("/{ingredient_id}/nutrition", summary="整体替换营养档案（版本化）")
def replace_nutrition(
    request: Request,
    ingredient_id: uuid.UUID,
    payload: NutritionReplace,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current),
):
    """docs/api.md §3.2：旧行 is_current=false，插入 version+1 的新行，同一事务。

    历史 `consumption_nutrition` 快照不受影响（M4 验收用例 3 依赖这一点）。
    """
    if db.get(Ingredient, ingredient_id) is None:
        raise not_found("食材不存在")

    codes = [item.code for item in payload.items]
    if len(set(codes)) != len(codes):
        raise validation_error("同一营养项目不能重复提交")

    definitions = {
        d.code: d
        for d in db.scalars(
            select(NutritionDefinition).where(NutritionDefinition.code.in_(codes))
        ).all()
    } if codes else {}
    missing = [c for c in codes if c not in definitions]
    if missing:
        raise validation_error("营养项目不存在", codes=missing)

    for item in payload.items:
        if db.get(Unit, item.basis_unit_id) is None:
            raise validation_error("基准单位不存在", code=item.code)

    # 旧「当前」行全部退役（传入列表之外的项目也一并退役：整体替换语义）
    current = db.scalars(
        select(IngredientNutrition).where(
            IngredientNutrition.ingredient_id == ingredient_id,
            IngredientNutrition.is_current.is_(True),
        )
    ).all()
    versions: dict[str, int] = {}
    for row in current:
        row.is_current = False
        versions[row.nutrition_definition_id] = max(
            versions.get(row.nutrition_definition_id, 0), row.version
        )

    for item in payload.items:
        defn = definitions[item.code]
        db.add(
            IngredientNutrition(
                ingredient_id=ingredient_id,
                nutrition_definition_id=defn.id,
                value=item.value,
                basis_amount=item.basis_amount,
                basis_unit_id=item.basis_unit_id,
                source="manual",
                version=versions.get(defn.id, 0) + 1,
                is_current=True,
            )
        )
    db.commit()
    return ok(request, {"updated": len(payload.items)}, "营养档案已更新")
