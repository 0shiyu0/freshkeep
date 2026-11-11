"""菜谱与采购清单（阶段 8.11~8.13）。

口径：
- 需求以**重量**为主；只填数量时，有 `default_unit_weight` 就换算，否则该行 `unmeasured`；
- 匹配 = 需求（按份数缩放）− 当前库存，缺口为负取 0；
- 合并清单：同一食材跨菜谱需求**相加**后减库存，只保留仍有缺口的行；
- 清单只写 `shopping_lists` / `shopping_list_items`，**不触碰库存表**。
"""
from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.errors import not_found, validation_error
from app.models import Ingredient, Recipe, RecipeItem, RecipeStep, Unit

Q2, Q3, Q4 = Decimal("0.01"), Decimal("0.001"), Decimal("0.0001")


def _q(v: Decimal, unit: Decimal) -> Decimal:
    return v.quantize(unit, rounding=ROUND_HALF_UP)


def _s(v: Decimal | None, unit: Decimal = Q3) -> str | None:
    return None if v is None else format(_q(v, unit), "f")


def _require_amount(item) -> None:
    w = item.weight if isinstance(item.weight, Decimal) else Decimal(str(item.weight or 0))
    q = item.quantity if isinstance(item.quantity, Decimal) else Decimal(str(item.quantity or 0))
    if w <= 0 and q <= 0:
        raise validation_error("菜谱食材必须填写重量或数量")


def _recipe_out(db: Session, recipe: Recipe) -> dict:
    items = db.execute(
        select(RecipeItem, Ingredient.name)
        .join(Ingredient, Ingredient.id == RecipeItem.ingredient_id)
        .where(RecipeItem.recipe_id == recipe.id)
        .order_by(Ingredient.name)
    ).all()
    stock = {
        r.ingredient_id: Decimal(r.w)
        for r in db.execute(
            text("SELECT ingredient_id, total_weight AS w FROM v_inventory")
        ).all()
    }
    step_rows = db.scalars(
        select(RecipeStep).where(RecipeStep.recipe_id == recipe.id).order_by(RecipeStep.seq)
    ).all()
    if step_rows:
        steps = [
            {"seq": r.seq, "text": r.text, "duration_minutes": r.duration_minutes, "legacy": False}
            for r in step_rows
        ]
    else:
        # 兼容旧数据：把 text 按行拆开，标 legacy 让前端知道可一键结构化
        lines = [ln.strip() for ln in (recipe.steps or "").splitlines() if ln.strip()]
        steps = [
            {"seq": i, "text": t, "duration_minutes": None, "legacy": True}
            for i, t in enumerate(lines)
        ]

    return {
        "id": recipe.id,
        "name": recipe.name,
        "category": recipe.category,
        "servings": _s(Decimal(recipe.servings or 0), Q2),
        "duration_minutes": recipe.duration_minutes,
        "steps": steps,
        "steps_text": "\n".join(s["text"] for s in steps),
        "note": recipe.note,
        "created_at": recipe.created_at,
        "image_url": f"/api/v1/files/{recipe.image_asset_id}/raw" if recipe.image_asset_id else None,
        "items": [
            {
                "id": i.id,
                "ingredient_id": i.ingredient_id,
                "ingredient_name": name,
                "quantity": _s(i.quantity),
                "weight": _s(i.weight),
                "unit_id": i.unit_id,
                "note": i.note,
                "available_weight": _s(stock.get(i.ingredient_id, Decimal(0))),
            }
            for i, name in items
        ],
    }


def list_recipes(db: Session, *, q: str | None, page: int, page_size: int) -> dict:
    stmt = select(Recipe)
    keyword = (q or "").strip().lower()
    if keyword:
        stmt = stmt.where(
            or_(func.lower(Recipe.name).like(f"%{keyword}%"),
                func.lower(Recipe.category).like(f"%{keyword}%"))
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = db.scalars(
        stmt.order_by(Recipe.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    counts = {
        r[0]: int(r[1])
        for r in db.execute(
            select(RecipeItem.recipe_id, func.count()).group_by(RecipeItem.recipe_id)
        ).all()
    }
    return {
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "category": r.category,
                "servings": _s(Decimal(r.servings or 0), Q2),
                "duration_minutes": r.duration_minutes,
                "item_count": counts.get(r.id, 0),
                "created_at": r.created_at,
                "image_url": f"/api/v1/files/{r.image_asset_id}/raw" if r.image_asset_id else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_recipe(db: Session, recipe_id: uuid.UUID) -> dict:
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise not_found("菜谱不存在")
    return _recipe_out(db, recipe)


def _replace_items(db: Session, recipe: Recipe, items: list) -> None:
    for old in db.scalars(select(RecipeItem).where(RecipeItem.recipe_id == recipe.id)).all():
        db.delete(old)
    db.flush()
    for item in items:
        _require_amount(item)
        if db.get(Ingredient, item.ingredient_id) is None:
            raise not_found("菜谱里的食材不存在")
        db.add(
            RecipeItem(
                recipe_id=recipe.id,
                ingredient_id=item.ingredient_id,
                quantity=item.quantity,
                weight=item.weight,
                unit_id=item.unit_id,
                note=item.note or "",
            )
        )
    db.flush()


def _normalize_steps(raw) -> list[dict]:
    """把字符串或结构化数组统一成 [{text, duration_minutes}]，去空行。"""
    out: list[dict] = []
    if isinstance(raw, str):
        for line in raw.splitlines():
            text = line.strip().lstrip("0123456789.、)- ").strip() if line.strip() else ""
            if text:
                out.append({"text": text, "duration_minutes": None})
    else:
        for item in raw or []:
            text = (getattr(item, "text", "") or "").strip()
            if text:
                out.append({
                    "text": text,
                    "duration_minutes": getattr(item, "duration_minutes", None),
                })
    return out


def _replace_steps(db: Session, recipe: Recipe, raw) -> None:
    steps = _normalize_steps(raw)
    for old in db.scalars(select(RecipeStep).where(RecipeStep.recipe_id == recipe.id)).all():
        db.delete(old)
    db.flush()
    for seq, item in enumerate(steps):
        db.add(RecipeStep(
            recipe_id=recipe.id, seq=seq,
            text=item["text"], duration_minutes=item["duration_minutes"],
        ))
    # 保留旧列同步，便于 SQL 直接查看与旧客户端
    recipe.steps = "\n".join(s["text"] for s in steps)
    db.flush()


def create_recipe(db: Session, payload) -> dict:
    name = (payload.name or "").strip()
    if not name:
        raise validation_error("菜谱名称不能为空")
    if not payload.items:
        raise validation_error("菜谱至少需要一项食材")
    recipe = Recipe(
        name=name,
        category=(payload.category or "").strip(),
        servings=Decimal(str(payload.servings or 1)),
        duration_minutes=payload.duration_minutes,
        steps="",  # 由 _replace_steps 统一写入（避免把 list 塞进 text 列）
        note=payload.note or "",
    )
    db.add(recipe)
    db.flush()
    _replace_items(db, recipe, payload.items)
    _replace_steps(db, recipe, payload.steps)
    return _recipe_out(db, recipe)


def update_recipe(db: Session, recipe_id: uuid.UUID, payload) -> dict:
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise not_found("菜谱不存在")
    name = (payload.name or "").strip()
    if not name:
        raise validation_error("菜谱名称不能为空")
    if not payload.items:
        raise validation_error("菜谱至少需要一项食材")
    recipe.name = name
    recipe.category = (payload.category or "").strip()
    recipe.servings = Decimal(str(payload.servings or 1))
    recipe.duration_minutes = payload.duration_minutes
    recipe.note = payload.note or ""
    _replace_items(db, recipe, payload.items)
    _replace_steps(db, recipe, payload.steps)
    return _recipe_out(db, recipe)


def delete_recipe(db: Session, recipe_id: uuid.UUID) -> None:
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise not_found("菜谱不存在")
    db.delete(recipe)
    db.flush()


# ---------------------------------------------------------------- 匹配


def _requirements(db: Session, recipe_ids: list[uuid.UUID], servings_map: dict | None) -> dict:
    """聚合多个菜谱的食材需求（按份数缩放），返回 {ingredient_id: (重量, 名称, 是否不可计量)}。"""
    recipes = db.scalars(select(Recipe).where(Recipe.id.in_(recipe_ids))).all()
    if len(recipes) != len(set(recipe_ids)):
        raise not_found("菜谱不存在")
    by_id = {r.id: r for r in recipes}

    unit_weight = {
        r.id: (Decimal(r.uw) if r.uw else None)
        for r in db.execute(
            text("SELECT id, default_unit_weight AS uw FROM ingredients")
        ).all()
    }
    names = {
        r.id: r.name
        for r in db.execute(text("SELECT id, name FROM ingredients")).all()
    }
    rows = db.execute(
        select(RecipeItem).where(RecipeItem.recipe_id.in_(recipe_ids))
    ).scalars().all()

    need: dict[uuid.UUID, dict] = {}
    for item in rows:
        recipe = by_id[item.recipe_id]
        base = Decimal(recipe.servings or 1)
        target = Decimal(str((servings_map or {}).get(str(recipe.id)) or base))
        scale = target / base if base > 0 else Decimal(1)

        w = Decimal(item.weight or 0)
        unmeasured = False
        if w > 0:
            req = w * scale
        elif item.quantity and unit_weight.get(item.ingredient_id):
            req = Decimal(item.quantity) * unit_weight[item.ingredient_id] * scale
        else:
            req = Decimal(0)
            unmeasured = True

        slot = need.setdefault(
            item.ingredient_id,
            {"required": Decimal(0), "name": names.get(item.ingredient_id, ""), "unmeasured": False},
        )
        slot["required"] += req
        slot["unmeasured"] = slot["unmeasured"] or unmeasured
    return need


def match(db: Session, recipe_id: uuid.UUID, *, servings: Decimal | None = None) -> dict:
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise not_found("菜谱不存在")
    servings_map = {str(recipe_id): str(servings)} if servings else None
    need = _requirements(db, [recipe_id], servings_map)

    stock = {
        r.ingredient_id: Decimal(r.w)
        for r in db.execute(text("SELECT ingredient_id, total_weight AS w FROM v_inventory")).all()
    }
    items = []
    missing = 0
    for iid, slot in need.items():
        required = _q(slot["required"], Q3)
        available = _q(stock.get(iid, Decimal(0)), Q3)
        shortage = max(required - available, Decimal(0))
        if shortage > 0 and not slot["unmeasured"]:
            missing += 1
        items.append({
            "ingredient_id": iid,
            "ingredient_name": slot["name"],
            "required_weight": _s(required),
            "available_weight": _s(available),
            "shortage_weight": _s(_q(shortage, Q3)),
            "sufficient": shortage <= 0,
            "unmeasured": slot["unmeasured"],
        })
    items.sort(key=lambda x: (x["sufficient"], -(Decimal(x["shortage_weight"] or 0))))
    return {
        "recipe_id": recipe_id,
        "recipe_name": recipe.name,
        "servings": _s(Decimal(servings or recipe.servings or 1), Q2),
        "can_cook": missing == 0,
        "missing_count": missing,
        "items": items,
    }


# ---------------------------------------------------------------- 采购清单


def build_shopping_list(
    db: Session,
    *,
    recipe_ids: list[uuid.UUID],
    servings_map: dict | None,
    name: str | None,
) -> dict:
    if not recipe_ids:
        raise validation_error("至少选择一个菜谱")
    need = _requirements(db, recipe_ids, servings_map)
    stock = {
        r.ingredient_id: Decimal(r.w)
        for r in db.execute(text("SELECT ingredient_id, total_weight AS w FROM v_inventory")).all()
    }
    rows = []
    for iid, slot in need.items():
        if slot["unmeasured"]:
            continue
        shortage = _q(max(slot["required"] - stock.get(iid, Decimal(0)), Decimal(0)), Q3)
        if shortage > 0:
            rows.append({"ingredient_id": iid, "name": slot["name"], "weight": shortage})

    list_name = (name or "").strip() or f"采购清单（{len(recipe_ids)} 个菜谱）"
    lid = db.execute(
        text("INSERT INTO shopping_lists (name, status) VALUES (:n, 'open') RETURNING id"),
        {"n": list_name},
    ).scalar()

    for r in rows:
        db.execute(
            text(
                "INSERT INTO shopping_list_items "
                "(shopping_list_id, ingredient_id, suggested_weight, source, note) "
                "VALUES (CAST(:l AS uuid), CAST(:i AS uuid), CAST(:w AS numeric), 'recipe', :n)"
            ),
            {"l": str(lid), "i": str(r["ingredient_id"]), "w": _s(r["weight"]), "n": "来自菜谱"},
        )
    db.flush()
    return {
        "id": lid,
        "name": list_name,
        "status": "open",
        "items": [
            {
                "ingredient_id": r["ingredient_id"],
                "ingredient_name": r["name"],
                "suggested_weight": _s(r["weight"]),
                "source": "recipe",
            }
            for r in rows
        ],
        "message": "" if rows else "现有库存已满足所选菜谱，无需采购",
    }


def list_shopping_lists(db: Session, *, page: int, page_size: int) -> dict:
    total = db.execute(text("SELECT COUNT(*) FROM shopping_lists")).scalar() or 0
    rows = db.execute(
        text(
            """
            SELECT l.id, l.name, l.status, l.created_at, l.completed_at,
                   COUNT(i.id) AS item_count,
                   COUNT(i.id) FILTER (WHERE NOT i.is_completed) AS open_count
              FROM shopping_lists l
              LEFT JOIN shopping_list_items i ON i.shopping_list_id = l.id
             GROUP BY l.id
             ORDER BY l.created_at DESC
             LIMIT :limit OFFSET :offset
            """
        ),
        {"limit": page_size, "offset": (page - 1) * page_size},
    ).all()
    return {
        "items": [
            {
                "id": r.id, "name": r.name, "status": r.status,
                "item_count": int(r.item_count or 0), "open_count": int(r.open_count or 0),
                "created_at": r.created_at, "completed_at": r.completed_at,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_shopping_list(db: Session, list_id: uuid.UUID) -> dict:
    head = db.execute(
        text("SELECT id, name, status, created_at, completed_at FROM shopping_lists WHERE id = CAST(:i AS uuid)"),
        {"i": str(list_id)},
    ).first()
    if head is None:
        raise not_found("采购清单不存在")
    items = db.execute(
        text(
            """
            SELECT i.id, i.ingredient_id, COALESCE(g.name, i.free_text_name) AS name,
                   i.suggested_weight, i.suggested_quantity, i.source, i.is_completed, i.note
              FROM shopping_list_items i
              LEFT JOIN ingredients g ON g.id = i.ingredient_id
             WHERE i.shopping_list_id = CAST(:l AS uuid)
             ORDER BY i.is_completed, name
            """
        ),
        {"l": str(list_id)},
    ).all()
    return {
        "id": head.id, "name": head.name, "status": head.status,
        "created_at": head.created_at, "completed_at": head.completed_at,
        "items": [
            {
                "id": r.id, "ingredient_id": r.ingredient_id, "ingredient_name": r.name,
                "suggested_weight": _s(r.suggested_weight),
                "suggested_quantity": _s(r.suggested_quantity),
                "source": r.source, "is_completed": r.is_completed, "note": r.note,
            }
            for r in items
        ],
    }


def set_item_completed(db: Session, item_id: uuid.UUID, done: bool) -> dict:
    row = db.execute(
        text("UPDATE shopping_list_items SET is_completed = :d WHERE id = CAST(:i AS uuid) "
             "RETURNING id, is_completed"),
        {"d": done, "i": str(item_id)},
    ).first()
    if row is None:
        raise not_found("清单项不存在")
    db.flush()
    return {"id": row.id, "is_completed": row.is_completed}


def complete_list(db: Session, list_id: uuid.UUID) -> dict:
    head = db.execute(
        text("SELECT id FROM shopping_lists WHERE id = CAST(:i AS uuid)"), {"i": str(list_id)}
    ).first()
    if head is None:
        raise not_found("采购清单不存在")
    db.execute(
        text("UPDATE shopping_list_items SET is_completed = true WHERE shopping_list_id = CAST(:l AS uuid)"),
        {"l": str(list_id)},
    )
    db.execute(
        text("UPDATE shopping_lists SET status = 'completed', completed_at = now() "
             "WHERE id = CAST(:l AS uuid)"),
        {"l": str(list_id)},
    )
    db.flush()
    return {"id": list_id, "status": "completed"}


def build_from_low_stock(db: Session, *, name: str | None = None) -> dict:
    """把低库存建议合并成采购清单（source='low_stock'）。"""
    from app.services.purchase import suggestions as low_stock_suggestions

    data = low_stock_suggestions(db, limit=100)
    rows = [i for i in data["items"] if i.get("suggested_weight")]
    list_name = (name or "").strip() or f"低库存补货（{len(rows)} 项）"
    lid = db.execute(
        text("INSERT INTO shopping_lists (name, status) VALUES (:n, 'open') RETURNING id"),
        {"n": list_name},
    ).scalar()
    for r in rows:
        db.execute(
            text(
                "INSERT INTO shopping_list_items "
                "(shopping_list_id, ingredient_id, suggested_weight, source, note) "
                "VALUES (CAST(:l AS uuid), CAST(:i AS uuid), CAST(:w AS numeric), 'low_stock', :n)"
            ),
            {"l": str(lid), "i": str(r["ingredient_id"]), "w": r["suggested_weight"], "n": "低于最低库存"},
        )
    db.flush()
    return {
        "id": lid, "name": list_name, "status": "open",
        "items": [
            {"ingredient_id": r["ingredient_id"], "ingredient_name": r["name"],
             "suggested_weight": r["suggested_weight"], "source": "low_stock"}
            for r in rows
        ],
        "message": "" if rows else "没有低库存食材",
    }
