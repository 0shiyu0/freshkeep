"""条码：本地绑定与查询（阶段 2 只做"扫码定位食材"，不做外部商品库）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current
from app.core.errors import conflict, not_found
from app.db.session import get_db
from app.models import Ingredient, IngredientBarcode
from app.schemas.common import ok
from app.schemas.ingredient import BarcodeIn

router = APIRouter(prefix="/barcodes", tags=["barcodes"])


class BindRequest(BarcodeIn):
    ingredient_id: uuid.UUID


@router.get("/{code}", summary="按条码查食材")
def lookup(
    request: Request,
    code: str,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    row = db.execute(
        select(IngredientBarcode, Ingredient)
        .join(Ingredient, Ingredient.id == IngredientBarcode.ingredient_id)
        .where(IngredientBarcode.barcode == code.strip())
    ).first()
    if row is None:
        raise not_found("该条码尚未绑定任何食材")
    barcode, ing = row
    return ok(
        request,
        {
            "barcode": barcode.barcode,
            "barcode_type": barcode.barcode_type,
            "ingredient": {
                "id": str(ing.id),
                "name": ing.name,
                "is_active": ing.is_active,
                "image_url": f"/api/v1/files/{ing.image_asset_id}/raw" if ing.image_asset_id else None,
            },
        },
    )


@router.post("", status_code=201, summary="绑定条码到食材")
def bind(
    request: Request,
    payload: BindRequest,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    ing = db.get(Ingredient, payload.ingredient_id)
    if ing is None:
        raise not_found("食材不存在")
    row = IngredientBarcode(
        ingredient_id=payload.ingredient_id,
        barcode=payload.barcode.strip(),
        barcode_type=payload.barcode_type,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("该条码已绑定到其他食材") from None
    return ok(request, {"id": str(row.id), "barcode": row.barcode}, "条码已绑定")


@router.delete("/{barcode_id}", summary="解绑条码")
def unbind(
    request: Request,
    barcode_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(IngredientBarcode, barcode_id)
    if row is None:
        raise not_found("条码绑定不存在")
    db.delete(row)
    db.commit()
    return ok(request, {"deleted": True}, "已解绑")
